from fastapi import FastAPI, HTTPException, Request
import time
from app.api.v1.routes import auth
from app.exceptions import (
    exceptions_handler,
    http_exceptions_handler,
    validation_error_handler,
)
from pydantic import ValidationError
from app.logs.logger import get_logger
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
