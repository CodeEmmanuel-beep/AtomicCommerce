from fastapi import APIRouter, Depends
from app.services import profile_service
from app.database.get import get_db
from app.api.v1.schemas import StandardResponse, UserResponse, ProfileMode
from app.auth.verify_jwt import verify_token
from sqlalchemy.ext.asyncio import AsyncSession

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


@router.put(
    "/update_profile", response_model=StandardResponse, response_model_exclude_none=True
)
async def update_personal_profile(
    profile: ProfileMode,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await profile_service.edit_profile(
        profile=profile,
        db=db,
        payload=payload,
    )


@router.delete("/delete_personal_profile")
async def profile_deletion(
    userId: int | None = None,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await profile_service.delete_profile(userId=userId, db=db, payload=payload)
