from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from strawberry.fastapi import GraphQLRouter
import strawberry
import time
from app.api.v1.routes import auth
from strawberry.types import Info
from app.api.v1.routes.auth import graph_refresh
from app.exceptions import (
    exceptions_handler,
    http_exceptions_handler,
    validation_error_handler,
)
from pydantic import ValidationError
from app.exceptions import get_logger
from contextlib import asynccontextmanager
from supabase import create_async_client
from app.database.config import settings


@asynccontextmanager
async def get_supabase(app: FastAPI):
    supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    app.state.supabase = supabase
    yield


app = FastAPI(title="E Commerce", version="1.0", lifespan=get_supabase)


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


app.mount("/images", StaticFiles(directory="images"), name="images")


@strawberry.type
class Querry:
    @strawberry.field
    def hello(self, name: str = "World") -> str:
        return f"hello dear {name}!"

    def me(self, info: Info) -> str:
        user = graph_refresh(info)
        return f"HELLO {user['name']}"


schema = strawberry.Schema(query=Querry)
graph = GraphQLRouter(schema, graphiql=True)

app.include_router(graph, prefix="/check")
app.include_router(auth.router)
app.include_router(HTTPException, http_exceptions_handler)
app.include_router(Exception, exceptions_handler)
app.include_router(ValidationError, validation_error_handler)
