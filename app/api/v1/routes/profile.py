from fastapi import APIRouter, Request, Response, Query
from app.services import profile_service
from app.database.get import async_db
from app.api.v1.schemas import StandardResponse, UserResponse, ProfileMode
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/profile", tags=["Profile"])


@router.get(
    "/personal_profile",
    response_model=StandardResponse[UserResponse],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def get_personal_profile(request: Request, db: AsyncSession = async_db):
    return await profile_service.view_profile(db=db, request=request)


@router.put(
    "/update_profile", response_model=StandardResponse, response_model_exclude_none=True
)
async def update_personal_profile(
    request: Request, profile: ProfileMode, db: AsyncSession = async_db
):
    return await profile_service.edit_profile(profile=profile, db=db, request=request)


@router.delete("/deactivate_personal_profile")
async def profile_deactivation(
    request: Request,
    response: Response,
    db: AsyncSession = async_db,
):
    return await profile_service.deactivate_profile(
        db=db, response=response, request=request
    )


@router.delete("/ban_profile")
async def profile_ban(
    request: Request,
    userId: int,
    ban_period: int | None = None,
    ban_reason: str | None = None,
    indefinite: str = Query("No", enum=["Yes", "No"]),
    ban_unit: str | None = Query("days", enum=["months", None, "days"]),
    db: AsyncSession = async_db,
):
    return await profile_service.ban_profile(
        userId=userId,
        db=db,
        ban_period=ban_period,
        ban_unit=ban_unit,
        indefinite=indefinite,
        request=request,
        ban_reason=ban_reason,
    )
