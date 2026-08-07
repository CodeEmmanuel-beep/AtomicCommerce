from app.api.v1.schemas import LoginResponse, StandardResponse, RegistrationModel
from fastapi import APIRouter, Depends, Response, Request, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import RoleEnum
from typing import Annotated
from app.database.get import get_db
from app.services import auth_service
from supabase import AsyncClient
from app.utils.supabase_url import _supabase

router = APIRouter(prefix="/auth", tags=["Authentication"])

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]
SupabaseDep = Annotated[AsyncClient, Depends(_supabase)]


@router.post(
    "/register", response_model=StandardResponse, response_model_exclude_none=True
)
async def registration(registration: RegistrationModel, db: DatabaseDep):
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
    db: DatabaseDep,
    get_supabase: SupabaseDep,
    profile_picture: UploadFile = File(...),
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
async def logins(login: LoginResponse, response: Response, db: DatabaseDep):
    return await auth_service.logins(login=login, response=response, db=db)


@router.post(
    "/make_role", response_model=StandardResponse, response_model_exclude_none=True
)
async def create_roles(
    id_number: int,
    request: Request,
    db: DatabaseDep,
    assigned_role: RoleEnum = Query(RoleEnum.user),
):
    return await auth_service.create_role(
        id_number=id_number, request=request, assigned_role=assigned_role.value, db=db
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
