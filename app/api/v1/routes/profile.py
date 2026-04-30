from fastapi import APIRouter, Depends, File, UploadFile, Form
from app.services import profile_service
from app.database.get import get_db
from app.api.v1.schemas import StandardResponse, UserResponse
from app.auth.verify_jwt import verify_token
from sqlalchemy.ext.asyncio import AsyncSession
from app.utils.supabase_url import _supabase

router = APIRouter(prefix="/profile", tags=["Profile"])


@router.get(
    "/personal_profile",
    response_model=StandardResponse[UserResponse],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def get_personal_profile(
    db: AsyncSession = Depends(get_db), payload: dict = Depends(verify_token)
):
    return await profile_service.view_profile(db, payload)


@router.put("/update_profile")
async def update_personal_profile(
    profile_picture: UploadFile = File(None),
    first_name: str = Form(None),
    middle_name: str = Form(None),
    surname: str = Form(None),
    email: str = Form(None),
    nationality: str = Form(None),
    phone_number: str = Form(None),
    address: str = Form(None),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
    get_supabase=Depends(_supabase),
):
    return await profile_service.edit_profile(
        profile_picture=profile_picture,
        first_name=first_name,
        middle_name=middle_name,
        surname=surname,
        email=email,
        nationality=nationality,
        phone_number=phone_number,
        address=address,
        db=db,
        payload=payload,
        get_supabase=get_supabase,
    )


@router.delete("/delete_personal_profile")
async def profile_deletion(
    userId: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await profile_service.delete_profile(userId=userId, db=db, payload=payload)
