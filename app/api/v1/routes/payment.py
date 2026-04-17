from fastapi import APIRouter, Query, Depends
from app.services import payment_service
from app.auth.verify_jwt import verify_token
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db

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


@router.put("/update_membership/{subscription_id}")
async def update_plan(
    subscription_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await payment_service.update_payment(
        sub_id=subscription_id, db=db, payload=payload
    )
