from fastapi import FastAPI, HTTPException, Request
import time
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
)
from app.exceptions import (
    make_exception_handler,
    make_http_exception_handler,
    make_validation_error_handler,
)
from fastapi.exceptions import RequestValidationError
from app.logs.logger import get_logger
from contextlib import asynccontextmanager
from supabase import create_async_client
from app.database.config import settings
from cryptography.fernet import Fernet


@asynccontextmanager
async def lifespan(app: FastAPI):
    supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    app.state.supabase = supabase
    if not settings.CIPHER_KEY:
        raise RuntimeError("key not found")
    app.state.cipher = Fernet(settings.CIPHER_KEY.encode())
    yield


app = FastAPI(title="AtomicCommerce", version="1.0", lifespan=lifespan)


@app.middleware("http")
async def requests(request: Request, call_next):
    start = time.time()
    try:
        process = await call_next(request)
    except Exception as exc:
        duration = time.time() - start
        logger = get_logger("requests")
        logger.error(
            f"{request.method}-{request.url.path}|error:{exc}|duration:{duration:.3f}s"
        )
        raise
    duration = time.time() - start
    logger = get_logger("requests")
    logger.info(
        f"{request.method}-{request.url.path}|status:{process.status_code}|duration:{duration:.3f}s"
    )
    return process


@app.get("/", include_in_schema=False)
def home():
    return {
        "message": "Welcome to Emmanuel's E-Commerce API. Append /docs to the existing url address to explore the endpoints"
    }


app.include_router(auth.router)
app.include_router(category.router)
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
app.include_router(store_analytics.router)
app.include_router(payment.router)
app.include_router(customer_support.router)
app.include_router(store_reviews.router)
app.include_router(store_reply.router)
app.add_exception_handler(RequestValidationError, make_validation_error_handler())
app.add_exception_handler(HTTPException, make_http_exception_handler())
app.add_exception_handler(Exception, make_exception_handler())
