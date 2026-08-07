from fastapi import FastAPI, HTTPException, Request, status, Response
import time
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from app.database.config import settings
from jose import jwt, JWTError, ExpiredSignatureError
from app.database.get import async_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.routes import (
    auth,
    product,
    product_reply,
    product_reviews,
    store_reply,
    store_reviews,
    cart,
    category,
    order,
    membership,
    store_analytics,
    store,
    payment,
    customer_support,
    delivery_address,
    reactions,
    inventory,
    sub_category,
    profile,
    store_account_and_address,
    notifications,
)
from app.utils.redis import (
    run_router,
    add_commit_periodically,
    notification_queue,
    redis_client,
)
import asyncio
from app.exceptions import (
    make_exception_handler,
    make_http_exception_handler,
    make_validation_error_handler,
)
from sqlalchemy import text
from fastapi.exceptions import RequestValidationError
from app.logs.logger import get_logger
from contextlib import asynccontextmanager
from supabase import create_async_client
from cryptography.fernet import Fernet


@asynccontextmanager
async def lifespan(app: FastAPI):
    supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    app.state.supabase = supabase
    if not settings.CIPHER_KEY:
        raise RuntimeError("key not found")
    app.state.cipher = Fernet(settings.CIPHER_KEY.encode())
    app.state.router = asyncio.create_task(run_router())
    app.state.notification_worker = asyncio.create_task(
        add_commit_periodically(notification_queue)
    )
    try:
        yield
    finally:
        app.state.router.cancel()
        app.state.notification_worker.cancel()
        try:
            await app.state.router
            await app.state.notification_worker
        except asyncio.CancelledError:
            print("Router task cancelled successfully.")


app = FastAPI(title="AtomicCommerce", version="1.0", lifespan=lifespan)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title="AtomicCommerce Backend",
        version="1.0.0",
        description="API Documentation with JWT Bearer Authentication",
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    }
    openapi_schema["security"] = [{"BearerAuth": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

PUBLIC_PREFIX_PATHS = (
    "/auth/register",
    "/auth/login",
    "/category/get_category",
    "/product/search_product",
    "/product/view_product_images",
    "/product/list",
    "/store_analytics/store_public_dashboard",
    "/store/view_stores_global",
    "/sub_category/get_sub_category",
    "/store_replies/view_store_replies",
    "/store_reviews/view_store_reviews",
    "/product_replies/view_product_replies",
    "/product_reviews/view_product_reviews",
    "/docs",
    "/redoc",
    "/openapi.json",
)
PUBLIC_EXACT_PATHS = (
    "/payment/webhook",
    "/healthcheck",
    "/",
)


@app.middleware("http")
async def auth_requests(request: Request, call_next):
    normalized_path = (
        request.url.path if request.url.path == "/" else request.url.path.rstrip("/")
    )
    is_public = normalized_path in PUBLIC_EXACT_PATHS or normalized_path.startswith(
        PUBLIC_PREFIX_PATHS
    )
    if not is_public:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "Missing token"})
        parts = auth_header.split()
        if parts[0].lower() != "bearer" or len(parts) != 2:
            return JSONResponse(
                status_code=401, content={"detail": "Invalid auth header"}
            )
        is_refresh_endpoint = normalized_path == "/auth/refresh"
        token = parts[1]
        try:
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
            )
            user_id = payload.get("user_id")
            jti = payload.get("jti")
            if not user_id:
                return JSONResponse(
                    status_code=401, content={"detail": "Not authenticated"}
                )
            if not jti:
                return JSONResponse(
                    status_code=401, content={"detail": "Invalid token payload."}
                )
            try:
                async with redis_client.pipeline(transaction=False) as pipe:
                    pipe.exists(f"banned_client:{user_id}")
                    pipe.exists(f"blacklist:{jti}")
                    is_banned, is_blacklist = await pipe.execute()
            except Exception:
                return JSONResponse(
                    status_code=500, content={"detail": "Authentication store error"}
                )
            if is_banned:
                return JSONResponse(
                    status_code=403, content={"detail": "User is banned"}
                )
            if is_blacklist:
                return JSONResponse(
                    status_code=401, content={"detail": "User is logged out"}
                )
            request.state.user = payload
            return await call_next(request)
        except ExpiredSignatureError:
            if is_refresh_endpoint:
                try:
                    request.state.user = jwt.decode(
                        token,
                        settings.SECRET_KEY,
                        algorithms=[settings.ALGORITHM],
                        options={"verify_exp": False},
                    )
                except JWTError:
                    return JSONResponse(
                        status_code=401, content={"detail": "Invalid token payload"}
                    )
                return await call_next(request)
            return JSONResponse(status_code=401, content={"detail": "Token expired"})
        except JWTError:
            return JSONResponse(status_code=401, content={"detail": "Invalid token"})
    return await call_next(request)


error_logger = get_logger("middleware_error_requests")
request_logger = get_logger("middleware_requests")


@app.middleware("http")
async def requests(request: Request, call_next):
    start = time.time()
    try:
        process = await call_next(request)
    except Exception as exc:
        duration = time.time() - start
        error_logger.error(
            f"{request.method}-{request.url.path}|error:{exc}|duration:{duration:.3f}s"
        )
        raise
    duration = time.time() - start
    request_logger.info(
        f"{request.method}-{request.url.path}|status:{process.status_code}|duration:{duration:.3f}s"
    )
    return process


@app.get("/healthcheck", include_in_schema=False, status_code=status.HTTP_200_OK)
async def healthcheck(response: Response, db: AsyncSession = async_db):
    try:
        await db.execute(text("SELECT 1"))
        return {
            "status": "healthy",
            "database": "connected",
            "service": "marketplace_api",
        }
    except Exception as e:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unhealthy", "database": str(e)}


@app.get("/", include_in_schema=False)
def home():
    return {
        "message": "Welcome to Emmanuel's E-Commerce API. Append /docs to the existing url address to explore the endpoints"
    }


app.include_router(auth.router)
app.include_router(notifications.router)
app.include_router(profile.router)
app.include_router(category.router)
app.include_router(sub_category.router)
app.include_router(product.router)
app.include_router(inventory.router)
app.include_router(cart.router)
app.include_router(order.router)
app.include_router(delivery_address.router)
app.include_router(product_reviews.router)
app.include_router(product_reply.router)
app.include_router(reactions.router)
app.include_router(membership.router)
app.include_router(store.router)
app.include_router(store_account_and_address.router)
app.include_router(store_analytics.router)
app.include_router(payment.router)
app.include_router(customer_support.router)
app.include_router(store_reviews.router)
app.include_router(store_reply.router)
app.add_exception_handler(RequestValidationError, make_validation_error_handler())
app.add_exception_handler(HTTPException, make_http_exception_handler())
app.add_exception_handler(Exception, make_exception_handler())
