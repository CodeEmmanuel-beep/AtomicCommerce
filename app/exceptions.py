from fastapi import Request, status, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import logging
import os


def get_logger(name: str):
    logs = "logs"
    os.makedirs(logs, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(f"{logs}/{name}.log")
    formatter = logging.Formatter("%(asctime)s-%(levelname)s-%(message)s")
    handler.setFormatter(formatter)
    if not logger.handlers:
        logger.propagate = False
        logger.addHandler(handler)
    return logger


def make_http_exception_handler():
    async def http_exceptions_handler(request: Request, exc: Exception):
        if isinstance(exc, HTTPException):
            logger = get_logger("httpexceptions")
            logger.warning(f"HTTPEXCEPTION: {exc.detail}-PATH:{request.url.path}")
            return JSONResponse(
                status_code=exc.status_code,
                content={"status": "error", "message": exc.detail},
            )
        logger = get_logger("exceptions")
        logger.warning(f"UNHANDLED ERROR: PATH-{request.url.path}| ERROR {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"STATUS": "ERROR", "MESSAGE": "INTERNAL SERVER ERROR"},
        )

    return http_exceptions_handler


def make_validation_error_handler():
    async def validation_error_handler(request: Request, exc: Exception):
        if isinstance(exc, RequestValidationError):
            logger = get_logger("validation_error")
            logger.warning(f"PATH:{request.url.path}- ERROR{exc.errors()}")
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={
                    "status": "FAILED",
                    "message": "VALIDATION ERROR",
                    "details": exc.errors(),
                },
            )
        logger = get_logger("exceptions")
        logger.warning(f"UNHANDLED ERROR: PATH-{request.url.path}| ERROR {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"STATUS": "ERROR", "MESSAGE": "INTERNAL SERVER ERROR"},
        )

    return validation_error_handler


def make_exception_handler():
    async def exceptions_handler(request: Request, exc: Exception):
        logger = get_logger("exceptions")
        logger.warning(f"UNHANDLED ERROR: PATH-{request.url.path}| ERROR {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"STATUS": "ERROR", "MESSAGE": "INTERNAL SERVER ERROR"},
        )

    return exceptions_handler
