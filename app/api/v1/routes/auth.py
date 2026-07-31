from app.api.v1.schemas import LoginResponse, StandardResponse
from fastapi import APIRouter, Depends, Response, Request, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.schemas import RegistrationModel
from app.database.get import async_db
from app.services import auth_service
from app.utils.supabase_url import _supabase

router = APIRouter(prefix="/auth", tags=["Authentication"])

s_base = Depends(_supabase)
picture = File(...)


@router.post(
    "/register", response_model=StandardResponse, response_model_exclude_none=True
)
async def registration(registration: RegistrationModel, db: AsyncSession = async_db):
    return await auth_service.reg(
        registration=registration,
        db=db,
    )


@router.post(
    "/profile_picture",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def upload(
    request: Request,
    profile_picture: UploadFile = picture,
    db: AsyncSession = async_db,
    get_supabase=s_base,
):
    return await auth_service.upload_profile_picture(
        request=request,
        profile_picture=profile_picture,
        db=db,
        get_supabase=get_supabase,
    )


@router.post(
    "/login", response_model=StandardResponse, response_model_exclude_none=True
)
async def logins(login: LoginResponse, response: Response, db: AsyncSession = async_db):
    return await auth_service.logins(login=login, response=response, db=db)


@router.post(
    "/make_role", response_model=StandardResponse, response_model_exclude_none=True
)
async def create_roles(
    id_number: int,
    request: Request,
    assigned_role: str = Query("user", enum=["Admin", "customer_care", "user"]),
    db: AsyncSession = async_db,
):
    return await auth_service.create_role(
        id_number=id_number, request=request, assigned_role=assigned_role, db=db
    )


@router.post(
    "/refresh", response_model=StandardResponse, response_model_exclude_none=True
)
async def refresh_token(request: Request, response: Response):
    return await auth_service.refresh_token(request=request, response=response)


@router.post(
    "/logout", response_model=StandardResponse, response_model_exclude_none=True
)
async def logout_user(request: Request, response: Response):
    return await auth_service.logout(request=request, response=response)
