from fastapi import HTTPException, Request
from app.logs.logger import get_logger
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError
from app.models import User, Payment
from app.api.v1.schemas import (
    PaymentResponse,
    PaginatedMetadata,
    PaginatedResponse,
    StandardResponse,
)

logger = get_logger("payment")
