from app.database.config import settings
from fastapi import HTTPException
from jose import jwt, JWTError, ExpiredSignatureError


def decode_token(token: str):
    credentials_exception = HTTPException(
        status_code=401,
        detail="not authenticated",
        headers={"www-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.REFRESH_KEY, algorithms=[settings.ALGORITHM]
        )
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
        return payload
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="expired session")
    except JWTError:
        raise credentials_exception
