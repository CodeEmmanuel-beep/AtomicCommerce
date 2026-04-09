from fastapi import HTTPException
from app.logs.logger import get_logger
import stripe
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError
from app.models import User, Payment, Order
from app.api.v1.schemas import (
    PaymentResponse,
)
from app.database.get import AsyncSessionLocal

logger = get_logger("payment")


async def create_payment(
    orderid,
    currency,
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


async def stripe_webhook(request, db):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    event = None
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, "your_webhook_signing_secret"
        )
    except Exception:
        logger.exception("error verifying signature")
        raise HTTPException(status_code=400, detail="invalid signature")
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        stripe_session_id = session["id"]
        actual_transaction_id = session["payment_intent"]
        stmt = await db.execute(
            select(Payment).where(Payment.reference_id == stripe_session_id)
        )
        payment = stmt.scalar_one_or_none()
        if not payment:
            logger.error(
                "payment table was not initialised for payment_ref: %s, transaction_id: %s",
                stripe_session_id,
                actual_transaction_id,
            )
            return {
                "status": "failed",
                "message": "payment record not found in database",
            }
        if payment.payment_status == "success":
            return {"status": "success", "message": "Already processed"}
        payment.transaction_id = actual_transaction_id
        payment.payment_status = "success"
        payment.order.status = "processing"
        try:
            await db.commit()
        except IntegrityError:
            logger.error(
                "database error while saving payment status and transaction id on webhook endpoint"
            )
            raise HTTPException(status_code=400, detail="database error")
        except Exception:
            logger.exception(
                "error while saving payment status and transaction id on webhook endpoint"
            )
            raise HTTPException(status_code=500, detail="internal server error")
        logger.info(f"Payment {stripe_session_id} marked as completed.")
        return {"status": "success", "message": "payment status updated"}
    elif event["type"] == "checkout.session.expired":
        session = event["data"]["object"]
        stripe_session_id = session["id"]
        stmt = await db.execute(
            select(Payment).where(Payment.reference_id == stripe_session_id)
        )
        payment = stmt.scalar_one_or_none()
        if not payment:
            logger.error(
                "payment table was not initialised for expired payment_ref: %s",
                stripe_session_id,
            )
            return {
                "status": "failed",
                "message": "payment record not found in database",
            }
        if payment.payment_status == "failed":
            return {"status": "success", "message": "Already processed"}
        payment.payment_status = "failed"
        payment.order.status = "pending"
        try:
            await db.commit()
        except IntegrityError:
            logger.error(
                "database error while saving expired payment status on webhook endpoint"
            )
            raise HTTPException(status_code=400, detail="database error")
        except Exception:
            logger.exception(
                "error while saving expired payment status on webhook endpoint"
            )
            raise HTTPException(status_code=500, detail="internal server error")
        logger.info(f"Payment marked as expired and failed.")
        return {
            "status": "failed",
            "message": "payment expired, order status reverted to pending",
        }
    elif event["type"] == "checkout.session.failed":
        session = event["data"]["object"]
        stripe_session_id = session["id"]
        stmt = await db.execute(
            select(Payment).where(Payment.reference_id == stripe_session_id)
        )
        payment = stmt.scalar_one_or_none()
        if not payment:
            logger.error(
                "payment table was not initialised for failed payment_ref: %s",
                stripe_session_id,
            )
            return {
                "status": "failed",
                "message": "payment record not found in database",
            }
        if payment.payment_status == "failed":
            return {"status": "success", "message": "Already processed"}
        payment.payment_status = "failed"
        payment.order.status = "pending"
        try:
            await db.commit()
        except IntegrityError:
            logger.error(
                "database error while saving failed payment status on webhook endpoint"
            )
            raise HTTPException(status_code=400, detail="database error")
        except Exception:
            logger.exception(
                "error while saving failed payment status on webhook endpoint"
            )
            raise HTTPException(status_code=500, detail="internal server error")
        logger.info(f"Payment marked as failed.")
        return {
            "status": "failed",
            "message": "payment  failed, order status reverted to pending",
        }
