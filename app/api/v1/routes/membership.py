from fastapi import APIRouter, Depends, Query
from app.database.get import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.verify_jwt import verify_token
from app.services import membership_service
from app.api.v1.schemas import (
    StandardResponse,
    PaginatedMetadata,
    MembershipRes,
)

router = APIRouter(prefix="/member", tags=["Membership"])


@router.post("/create_membership/{store_id}")
async def membership(
    store_id: int,
    membership_type: str = Query("Regular", enum=["Standard", "Premium", "Regular"]),
    activate: str = Query("yes", enum=["no", "yes"]),
    activation_type: str = Query("subscription", enum=["one_time", "subscription"]),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.make_member(
        store_id=store_id,
        membership_type=membership_type,
        activate=activate,
        activation_type=activation_type,
        db=db,
        payload=payload,
    )


@router.put("/update_membership/{store_id}")
async def update_membership_type(
    store_id: int,
    membership_type: str = Query("Regular", enum=["Standard", "Premium", "Regular"]),
    activate: str = Query("yes", enum=["no", "yes"]),
    activation_type: str = Query("subscription", enum=["one_time", "subscription"]),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.update(
        store_id=store_id,
        membership_type=membership_type,
        activate=activate,
        activation_type=activation_type,
        db=db,
        payload=payload,
    )


@router.get(
    "/member_profile/{store_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_profile(
    store_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.view_membership(
        store_id=store_id, db=db, payload=payload
    )


@router.get(
    "/member_profiles",
    response_model=StandardResponse,
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_member_list(
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.view_memberships(db=db, payload=payload)


@router.get(
    "/active_profile/{store_id}",
    response_model=StandardResponse[PaginatedMetadata[MembershipRes]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def active_members(
    store_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.view_active_members(
        store_id=store_id, db=db, payload=payload, page=page, limit=limit
    )


@router.get(
    "/inactive_profile/{store_id}",
    response_model=StandardResponse[PaginatedMetadata[MembershipRes]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def inactive_members(
    store_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.view_inactive_members(
        store_id, db=db, payload=payload, page=page, limit=limit
    )


@router.get(
    "/paused_profile/{store_id}",
    response_model=StandardResponse[PaginatedMetadata[MembershipRes]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def paused_subscriptions(
    store_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.view_paused_members(
        store_id=store_id, db=db, payload=payload, page=page, limit=limit
    )


@router.get(
    "/deleted_profile/{store_id}",
    response_model=StandardResponse[PaginatedMetadata[MembershipRes]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def deleted_profile(
    store_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.view_inactive_members(
        store_id=store_id, db=db, payload=payload, page=page, limit=limit
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


@router.put("/restore_profile/{store_id}")
async def restore_deleted_member(
    store_id: int,
    membership_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.restore_membership(
        store_id=store_id, membership_id=membership_id, db=db, payload=payload
    )


@router.delete("/delete_membership?{store_id}/{membership_id}")
async def delete_membership(
    store_id: int,
    membership_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await membership_service.delete_member(
        store_id=store_id, membership_id=membership_id, db=db, payload=payload
    )
