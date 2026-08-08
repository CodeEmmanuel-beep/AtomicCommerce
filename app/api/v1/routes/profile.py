from fastapi import APIRouter, Request, Response, Query, Depends
from app.services import profile_service
from typing import Annotated
from app.database.get import get_db
from app.api.v1.schemas import (
    StandardResponse,
    UserResponse,
    ProfileMode,
    QueryEnum,
    SuperUserResponse,
    PaginatedMetadata,
    UserState,
)
from app.models import BanUnit
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/profile", tags=["Profile"])

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]


@router.get(
    "/personal_profile",
    response_model=StandardResponse[UserResponse],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def get_personal_profile(request: Request, db: DatabaseDep):
    return await profile_service.view_profile(db=db, request=request)


@router.get(
    "/general_profile",
    response_model=StandardResponse[PaginatedMetadata[SuperUserResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_general_profile(
    request: Request,
    db: DatabaseDep,
    user_state: UserState = Query(None),
    cursor_id: int | None = Query(None, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await profile_service.view_profiles(
        request=request, cursor_id=cursor_id, db=db, state=user_state, limit=limit
    )


@router.put(
    "/update_profile", response_model=StandardResponse, response_model_exclude_none=True
)
async def update_personal_profile(
    request: Request, profile: ProfileMode, db: DatabaseDep
):
    return await profile_service.edit_profile(profile=profile, db=db, request=request)


@router.delete("/deactivate_personal_profile")
async def profile_deactivation(request: Request, response: Response, db: DatabaseDep):
    return await profile_service.deactivate_profile(
        db=db, response=response, request=request
    )


@router.delete("/ban_profile")
async def profile_ban(
    request: Request,
    db: DatabaseDep,
    userId: int,
    ban_period: int | None = None,
    ban_reason: str | None = None,
    indefinite: QueryEnum = Query(QueryEnum.No),
    ban_unit: BanUnit = Query(None),
):
    return await profile_service.ban_profile(
        userId=userId,
        db=db,
        ban_period=ban_period,
        ban_unit=ban_unit.value if ban_unit else None,
        indefinite=indefinite.value,
        request=request,
        ban_reason=ban_reason,
    )
