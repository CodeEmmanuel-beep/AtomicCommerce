from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os
from fastapi import Security, HTTPException
from jose import jwt, JWTError, ExpiredSignatureError
from dotenv import load_dotenv


load_dotenv()
sk = os.getenv("SECRET_KEY")
if not sk:
    raise RuntimeError("Could not access SECRET_KEY")
SECRET_KEY = sk
al = os.getenv("ALGORITHM")
if not al:
    raise RuntimeError("Could not access ALGORITH")
ALGORITHM = al

security_scheme = HTTPBearer()


def verify_token(credentials: HTTPAuthorizationCredentials = Security(security_scheme)):
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=403,
        detail="not authenticated",
        headers={"www-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="expired session")
    except JWTError:
        raise credentials_exception


def decode_token(token: str):
    credentials_exception = HTTPException(
        status_code=403,
        detail="not authenticated",
        headers={"www-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="expired session")
    except JWTError:
        raise credentials_exception
