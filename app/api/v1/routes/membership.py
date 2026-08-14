from fastapi import APIRouter, Request, Query, BackgroundTasks, Depends
from app.database.get import get_db
from app.models import MembershipType
from sqlalchemy.ext.asyncio import AsyncSession
from app.services import membership_service
from app.api.v1.schemas import (
    StandardResponse,
    PaginatedMetadata,
    MembershipRes,
    MembershipResponse,
    SubscriptionResponse,
    MemberStatus,
    SubscriptionTypeEnum,
)
from typing import Annotated

router = APIRouter(prefix="/member", tags=["Membership"])

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/create_membership/{store_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def membership(
    store_id: int,
    request: Request,
    db: DatabaseDep,
    background_task: BackgroundTasks,
    membership_type: MembershipType = Query(MembershipType.Standard),
    activation_type: SubscriptionTypeEnum = Query(SubscriptionTypeEnum.subscription),
):
    return await membership_service.make_member(
        store_id=store_id,
        background_task=background_task,
        membership_type=membership_type.value,
        activation_type=activation_type.value,
        db=db,
        request=request,
    )


@router.put(
    "/update_membership/{store_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def update_membership_type(
    store_id: int,
    request: Request,
    background_task: BackgroundTasks,
    db: DatabaseDep,
    membership_type: MembershipType = Query(MembershipType.Standard),
    activation_type: SubscriptionTypeEnum = Query(SubscriptionTypeEnum.subscription),
):
    return await membership_service.update(
        store_id=store_id,
        background_task=background_task,
        membership_type=membership_type.value,
        activation_type=activation_type.value,
        db=db,
        request=request,
    )


@router.get(
    "/member_profile/{store_id}",
    response_model=StandardResponse[MembershipResponse],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_profile(store_id: int, request: Request, db: DatabaseDep):
    return await membership_service.view_membership(
        store_id=store_id, db=db, request=request
    )


@router.get(
    "/subscription_data/{member_id}",
    response_model=StandardResponse[SubscriptionResponse],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_subscription_data(member_id: int, request: Request, db: DatabaseDep):
    return await membership_service.view_subscription(
        member_id=member_id, db=db, request=request
    )


@router.get(
    "/member_profiles",
    response_model=StandardResponse,
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_member_list(request: Request, db: DatabaseDep):
    return await membership_service.view_memberships(db=db, request=request)


@router.get(
    "/selected_profiles/{store_id}",
    response_model=StandardResponse[PaginatedMetadata[MembershipRes]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def selected_members(
    store_id: int,
    request: Request,
    db: DatabaseDep,
    member_status: MemberStatus = Query(MemberStatus.active_members),
    cursor_id: int = Query(None, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await membership_service.view_selected_members(
        store_id=store_id,
        request=request,
        db=db,
        member_status=member_status.value,
        cursor_id=cursor_id,
        limit=limit,
    )


@router.get(
    "/members_subscription_list/{store_id}",
    response_model=StandardResponse[PaginatedMetadata[SubscriptionResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def subscription_list(
    store_id: int,
    request: Request,
    db: DatabaseDep,
    cursor_id: int = Query(None, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await membership_service.view_members_subscriptions(
        store_id=store_id,
        request=request,
        db=db,
        cursor_id=cursor_id,
        limit=limit,
    )


@router.get(
    "/member_subscription/{store_id}/{member_id}",
    response_model=StandardResponse[SubscriptionResponse],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def subscription(
    store_id: int,
    member_id: int,
    request: Request,
    db: DatabaseDep,
):
    return await membership_service.view_member_subscription(
        store_id=store_id,
        request=request,
        db=db,
        member_id=member_id,
    )


@router.put(
    "/restore_profile/{store_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def restore_deleted_member(
    store_id: int, request: Request, membership_id: int, db: DatabaseDep
):
    return await membership_service.restore_membership(
        store_id=store_id, membership_id=membership_id, db=db, request=request
    )


@router.delete(
    "/delete_membership/{store_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_membership(
    store_id: int,
    request: Request,
    db: DatabaseDep,
    background_task: BackgroundTasks,
    membership_id: int | None = None,
):
    return await membership_service.delete_member(
        store_id=store_id,
        background_task=background_task,
        membership_id=membership_id,
        db=db,
        request=request,
    )
