from jose import jwt
from fastapi import HTTPException
from datetime import datetime, timezone, timedelta
from passlib.context import CryptContext
from app.database.config import settings
import re

password_context = CryptContext(schemes=["argon2"], deprecated="auto")


def verify_password(plain_password: str, hash_password: str):
    return password_context.verify(plain_password, hash_password)


def hashed_password(password):
    return password_context.hash(password)


def create_access_token(data: dict, expire_delta: timedelta | None = None):
    to_encode = data.copy()
    to_encode["type"] = "access_token"
    expire = datetime.now(timezone.utc) + (
        expire_delta or timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(data: dict, expire_delta: timedelta | None = None):
    to_encode = data.copy()
    to_encode["type"] = "refresh_token"
    expire = datetime.now(timezone.utc) + (expire_delta or timedelta(days=7))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.REFRESH_KEY, algorithm=settings.ALGORITHM)
