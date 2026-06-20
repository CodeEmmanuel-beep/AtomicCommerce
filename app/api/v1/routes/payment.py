from fastapi import APIRouter, Query, Depends, Request, BackgroundTasks
from app.services import payment_service, stripe_webhook_service
from app.auth.verify_jwt import verify_token
from app.api.v1.schemas import PaymentResponse, StandardResponse, PaginatedMetadata
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db
from decimal import Decimal

router = APIRouter(prefix="/payment", tags=["Payment"])


@router.post("/make_payment")
async def initiate_payment(
    membership_id: int | None = None,
    order_id: int | None = None,
    currency: str = "usd",
    payload: dict = Depends(verify_token),
    one_time_subscription: str = Query("one_time", enum=["one_time", "subscription"]),
):
    return await payment_service.create_payment(
        membership_id=membership_id,
        order_id=order_id,
        currency=currency,
        payload=payload,
        one_time_subscription=one_time_subscription,
    )


@router.post("/webhook")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    return await stripe_webhook_service.stripe_webhook(
        request=request, background_task=background_tasks
    )


@router.put("/update_membership/{subscription_id}")
async def update_plan(
    subscription_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await payment_service.update_payment(
        sub_id=subscription_id, db=db, payload=payload
    )


@router.get(
    "/payment_list/{store_id}",
    response_model=StandardResponse[PaginatedMetadata[PaymentResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def get_payment_list(
    store_id: int,
    payment_status: str = Query("approved", enum=["failed", "pending", "refunds"]),
    time_frame: str = Query(
        "1 week", enum=["1 month", "3 months", "6 months", "1 year", "1 week"]
    ),
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await payment_service.get_payment(
        store_id=store_id,
        payment_status=payment_status,
        time_frame=time_frame,
        page=page,
        limit=limit,
        db=db,
        payload=payload,
    )


@router.post("/refund_client")
async def log_refund(
    payment_id: int,
    amount: Decimal,
    reason: str,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await payment_service.charge_refund(
        payment_id=payment_id, amount=amount, reason=reason, db=db, payload=payload
    )
