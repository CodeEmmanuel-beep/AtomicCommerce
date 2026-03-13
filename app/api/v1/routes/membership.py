from fastapi import APIRouter, Depends, Query
from app.database.get import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.verify_jwt import verify_token
from app.services import membership_service
from app.api.v1.models import (
    StandardResponse,
    PaginatedMetadata,
    MembershipResponse,
    MembershipRes,
)

router = APIRouter(prefix="/member", tags=["Membership"])


@router.post("/create_membership")
async def membership(
    membership_type: str = Query("Regular", enum=["Standard", "Premium", "Regular"]),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.make_member(
        membership_type=membership_type,
        db=db,
        payload=payload,
    )


@router.put("/update_membership")
async def update_membership_type(
    membership_type: str = Query("Regular", enum=["Standard", "Premium", "Regular"]),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.update(
        membership_type=membership_type, db=db, payload=payload
    )


@router.get(
    "/member_profile",
    response_model=StandardResponse[PaginatedMetadata[MembershipResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_profile(
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.view_member(db=db, payload=payload)


@router.get(
    "/active_profile",
    response_model=StandardResponse[PaginatedMetadata[MembershipRes]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def active_members(
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.view_active_members(
        db=db, payload=payload, page=page, limit=limit
    )


@router.get(
    "/inactive_profile",
    response_model=StandardResponse[PaginatedMetadata[MembershipRes]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def inactive_members(
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.view_inactive_members(
        db=db, payload=payload, page=page, limit=limit
    )


@router.get(
    "/paused_profile",
    response_model=StandardResponse[PaginatedMetadata[MembershipRes]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def paused_subscriptions(
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.view_paused_members(
        db=db, payload=payload, page=page, limit=limit
    )


@router.get(
    "/deleted_profile",
    response_model=StandardResponse[PaginatedMetadata[MembershipRes]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def deleted_profile(
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.view_inactive_members(
        db=db, payload=payload, page=page, limit=limit
    )


@router.put("/pause_membership")
async def take_a_break(
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.pause_membership(db=db, payload=payload)


@router.put("/reactivate_membership")
async def reactivation(
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.reactivate_membership(db=db, payload=payload)


@router.put("/restore_profile")
async def restore_deleted_member(
    membership_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.restore_membership(
        membership_id=membership_id, db=db, payload=payload
    )


@router.delete("/delete_membership")
async def delete_membership(
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.delete_member(db=db, payload=payload)
