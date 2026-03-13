from jose import jwt
from fastapi import HTTPException
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from passlib.context import CryptContext
import os
import re

load_dotenv()
sk = os.getenv("SECRET_KEY")
if not sk:
    raise RuntimeError("Could not access SECRET_KEY")
SECRET_KEY = sk
al = os.getenv("ALGORITHM")
if not al:
    raise RuntimeError("Could not access ALGORITH")
ALGORITHM = al
minutes_env = os.getenv("ACCESS_TOKEN_MINUTES")
if not minutes_env:
    raise RuntimeError("Could not access ACCESS_TOKEN_MINUTES")
ACCESS_TOKEN_MINUTES = int(minutes_env)

password_context = CryptContext(schemes=["argon2"], deprecated="auto")


def verify_password(plain_password: str, hash_password: str):
    return password_context.verify(plain_password, hash_password)


def hashed_password(password):
    if len(password) < 8:
        raise HTTPException(
            status_code=400, detail="password should be atleast 8 characters"
        )
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise HTTPException(
            status_code=400, detail="password should be letters and numbers"
        )
    return password_context.hash(password)


def create_access_token(data: dict, expire_delta: timedelta | None = None):
    to_encode = data.copy()
    to_encode["type"] = "access_token"
    expire = datetime.now(timezone.utc) + (
        expire_delta or timedelta(minutes=ACCESS_TOKEN_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict, expire_delta: timedelta | None = None):
    to_encode = data.copy()
    to_encode["type"] = "refresh_token"
    expire = datetime.now(timezone.utc) + (expire_delta or timedelta(days=7))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
