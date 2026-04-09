from fastapi import HTTPException, Request
from app.logs.logger import get_logger
import stripe
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError
from app.models import User, Payment, Order
from app.api.v1.schemas import (
    PaymentResponse,
    PaginatedMetadata,
    PaginatedResponse,
    StandardResponse,
)
from app.database.get import AsyncSessionLocal

logger = get_logger("payment")


async def create_payment(
    orderid: int,
    currency: str,
    db,
    payload,
):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized access.")
    order = (
        await db.execute(
            select(Order).where(
                Order.user_id == user_id, Order.id == orderid, Order.status == "pending"
            )
        )
    ).scalar_one_or_none()
    if not order:
        logger.warning(
            f"user_id: {user_id} attempted to create payment for non-existent or already processed order_id: {orderid}"
        )
        raise HTTPException(
            status_code=404, detail="Order not found or already processed."
        )
    async with AsyncSessionLocal() as session:
        try:
            intent = stripe.checkout.Session.create(
                payment_method_types=["card"],
                client_reference_id=str(order.id),
                metadata={"user_id": str(user_id), "order_id": str(order.id)},
                line_items=[
                    {
                        "price_data": {
                            "currency": currency,
                            "product_data": {
                                "name": f"Order {orderid} Payment",
                            },
                            "unit_amount": int(order.total_amount * 100),
                        },
                        "quantity": 1,
                    }
                ],
                mode="payment",
                success_url="https://yourdomain.com/success?session_id={CHECKOUT_SESSION_ID}",
                cancel_url="https://yourdomain.com/cancel",
            )
            payment = Payment(
                user_id=user_id,
                order_id=order.id,
                amount_paid=order.total_amount,
                currency=currency,
                payment_method="card",
                reference_id=intent.id,
                shipping_fee=order.shipping_fee,
                discount_amount=order.discount_amount,
                tax_amount=order.tax_amount,
                payment_status="pending",
            )
            session.add(payment)
            await session.commit()
            await session.refresh(payment)
            logger.info(
                f"Payment created successfully for user_id: {user_id}, amount: {order.total_amount} {currency}"
            )
            return {
                "status": "success",
                "checkout_url": intent.url,
                "data": PaymentResponse.model_validate(payment),
            }
        except stripe.StripeError as e:
            logger.error(f"Stripe error occurred: {e.user_message}")
            raise HTTPException(
                status_code=400, detail=f"Stripe error: {e.user_message}"
            )
        except IntegrityError:
            await session.rollback()
            logger.error(
                f"Database error occurred while creating payment for user_id: {user_id}"
            )
            raise HTTPException(
                status_code=500,
                detail="Database error occurred while processing payment.",
            )
        except Exception as e:
            await session.rollback()
            logger.exception(
                f"Unexpected error occurred while creating payment for user_id: {user_id}"
            )
            raise HTTPException(
                status_code=500,
                detail="An unexpected error occurred while processing payment.",
            )
