from app.api.v1.models import LoginResponse
from app.auth.verify_jwt import verify_token
from fastapi import (
    APIRouter,
    Depends,
    Response,
    Request,
    UploadFile,
    File,
    Query,
    Form,
)
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register")
async def registration(
    name: str = Form(...),
    username: str = Form(...),
    email: str = Form(...),
    nationality: str = Form(...),
    address: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    profile_picture: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
):
    return await auth_service.reg(
        name=name,
        username=username,
        email=email,
        nationality=nationality,
        address=address,
        password=password,
        confirm_password=confirm_password,
        profile_picture=profile_picture,
        db=db,
    )


@router.post("/login")
async def logins(
    login: LoginResponse, response: Response, db: AsyncSession = Depends(get_db)
):
    return await auth_service.logins(login=login, response=response, db=db)


@router.post("/make_role")
async def create_roles(
    username: str,
    role: str = Query("user", enum=["Admin", "customer_care", "user"]),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await auth_service.create_role(
        username=username, role=role, db=db, payload=payload
    )


@router.post("/deactivate_admin")
async def delete_admin(
    username: str,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await auth_service.delete_admin(username=username, db=db, payload=payload)


@router.post("/make_customer_care")
async def create_customer_care(
    username: str,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await auth_service.create_admin(username=username, db=db, payload=payload)


@router.post("/deactivate_customer_care")
async def delete_customer_care(
    username: str,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await auth_service.delete_admin(username=username, db=db, payload=payload)


@router.post("/refresh")
async def refresh_token(request: Request, response: Response):
    return await auth_service.refresh_token(request=request, response=response)
