from fastapi import APIRouter, Query, Request, BackgroundTasks, Depends
from app.services import payment_service, stripe_webhook_service
from app.api.v1.schemas import (
    PaymentResponse,
    StandardResponse,
    PaginatedMetadata,
    SubscriptionTypeEnum,
    TimeFrameEnum,
)
from typing import Annotated
from app.models import PaymentStatus
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db
from decimal import Decimal

router = APIRouter(prefix="/payment", tags=["Payment"])

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]


@router.post("/make_payment")
async def initiate_payment(
    request: Request,
    membership_id: int | None = None,
    order_id: int | None = None,
    currency: str = "usd",
    one_time_subscription: SubscriptionTypeEnum = Query(SubscriptionTypeEnum.one_time),
):
    return await payment_service.create_payment(
        membership_id=membership_id,
        order_id=order_id,
        currency=currency,
        request=request,
        one_time_subscription=one_time_subscription.value,
    )


@router.post("/webhook")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    return await stripe_webhook_service.stripe_webhook(
        request=request, background_task=background_tasks
    )


@router.put("/update_membership/{subscription_id}")
async def update_plan(request: Request, subscription_id: int, db: DatabaseDep):
    return await payment_service.update_payment(
        sub_id=subscription_id, db=db, request=request
    )


@router.get(
    "/payment_list",
    response_model=StandardResponse[PaginatedMetadata[PaymentResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def get_store_payment_list(
    request: Request,
    store_id: int,
    db: DatabaseDep,
    payment_status: PaymentStatus = Query(PaymentStatus.SUCCESS),
    time_frame: TimeFrameEnum = Query(TimeFrameEnum.one_week),
    cursor_id: int | None = Query(None, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await payment_service.get_payment(
        store_id=store_id,
        payment_status=payment_status.value,
        time_frame=time_frame.value,
        cursor_id=cursor_id,
        limit=limit,
        db=db,
        request=request,
    )


@router.post("/refund_client")
async def log_refund(
    request: Request, payment_id: int, amount: Decimal, reason: str, db: DatabaseDep
):
    return await payment_service.charge_refund(
        payment_id=payment_id, amount=amount, reason=reason, db=db, request=request
    )


@router.get(
    "/personal_payment_list/{store_id}",
    response_model=StandardResponse[PaginatedMetadata[PaymentResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def get_personal_payment_list(
    request: Request,
    store_id: int,
    db: DatabaseDep,
    payment_status: PaymentStatus = Query(PaymentStatus.SUCCESS),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await payment_service.get_personal_receipt_list(
        store_id=store_id,
        payment_status=payment_status.value,
        page=page,
        limit=limit,
        db=db,
        request=request,
    )


@router.get(
    "/personal_payment/{store_id}/{order_id}",
    response_model=StandardResponse[PaymentResponse],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def get_personal_payment(
    request: Request, store_id: int, order_id: int, db: DatabaseDep
):
    return await payment_service.get_personal_receipt(
        store_id=store_id, order_id=order_id, db=db, request=request
    )
