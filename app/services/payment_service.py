from fastapi import HTTPException, BackgroundTasks
from app.logs.logger import get_logger
import stripe
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from app.models import Subscription, Payment, Order, Membership
from app.api.v1.schemas import PaymentResponse, SubscriptionResponse
from app.database.config import settings
from app.database.get import AsyncSessionLocal
from datetime import datetime, timezone

logger = get_logger("payment")


async def membership_activation(membership_id, db):
    stmt = await db.execute(
        select(Subscription)
        .join(Membership, Subscription.membership_id == membership_id)
        .where(Membership.id == membership_id)
    )
    sub = stmt.scalar_one_or_none()
    if not sub:
        logger.error(
            "membership_id: %s not linked to subscription table",
            membership_id,
        )
        return
    membership = await db.get(Membership, membership_id)
    if not membership:
        logger.error(
            "membership record not found for membership_id: %s during background activation task",
            membership_id,
        )
        return
    if sub.expire_at < datetime.now(timezone.utc) and membership.is_active == True:
        membership.is_active = False
    if sub.expire_at > datetime.now(timezone.utc) and membership.is_active == False:
        membership.is_active = True
    else:
        return
    try:
        await db.commit()
        logger.info(
            f"Membership status of member: {membership_id} updated successfully in background task."
        )
    except IntegrityError:
        await db.rollback()
        logger.error(
            f"Database error occurred while updating membership_id: {membership_id} in background task"
        )
    except Exception:
        await db.rollback()
        logger.exception(
            f"Unexpected error occurred while updating membership_id: {membership_id} in background task"
        )


async def create_payment(
    membership_id,
    order_id,
    currency,
    payload,
):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized access.")
    async with AsyncSessionLocal() as session:
        if order_id and membership_id:
            logger.warning(
                f"user_id: {user_id} attempted to create payment with both order_id: {order_id} and membership_id: {membership_id}, which is not allowed"
            )
            raise HTTPException(
                status_code=400,
                detail="Cannot specify both order_id and membership_id. Please choose one.",
            )
        if order_id is None and membership_id is None:
            logger.warning(
                f"user_id: {user_id} attempted to create payment without specifying order_id or membership_id"
            )
            raise HTTPException(
                status_code=400,
                detail="Must specify either order_id or membership_id.",
            )
        try:
            if order_id is not None:
                order = (
                    await session.execute(
                        select(Order).where(
                            Order.user_id == user_id,
                            Order.id == order_id,
                            Order.status == "pending",
                        )
                    )
                ).scalar_one_or_none()
                if not order:
                    logger.warning(
                        f"user_id: {user_id} attempted to create payment for non-existent or already processed order_id: {order_id}"
                    )
                    raise HTTPException(
                        status_code=404, detail="Order not found or already processed."
                    )
                intent = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    client_reference_id=str(order.id),
                    metadata={
                        "user_id": str(user_id),
                        "type": "order_payment",
                        "order_id": str(order.id),
                    },
                    line_items=[
                        {
                            "price_data": {
                                "currency": currency,
                                "product_data": {
                                    "name": f"Order {order.id} Payment",
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
            if membership_id is not None:
                sub = (
                    await session.execute(
                        select(Subscription)
                        .join(Membership, Subscription.membership_id == Membership.id)
                        .where(
                            Membership.user_id == user_id,
                            Membership.id == membership_id,
                        )
                    )
                ).scalar_one_or_none()
                if not sub:
                    logger.warning(
                        f"user_id: {user_id} attempted to create payment for subscription_plan without a membership"
                    )
                    raise HTTPException(
                        status_code=404,
                        detail="register as a member before subscribing to a plan.",
                    )
                subscription = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    client_reference_id=str(user_id),
                    metadata={
                        "user_id": str(user_id),
                        "type": "membership",
                        "membership_id": membership_id,
                    },
                    line_items=[
                        {
                            "price": sub.plan_name.value,
                            "quantity": 1,
                        }
                    ],
                    mode="subscription",
                    success_url="https://yourdomain.com/success?session_id={CHECKOUT_SESSION_ID}",
                    cancel_url="https://yourdomain.com/cancel",
                )
                logger.info(
                    f"subscription payment created successfully for user_id: {user_id}, subscription_plan: {sub.plan_name}"
                )
                sub.reference_id = subscription.id
                session.add(sub)
                await session.commit()
                await session.refresh(sub)
                return {
                    "status": "success",
                    "message": "subscription payment initiated, complete payment to activate membership",
                    "checkout_url": subscription.url,
                    "data": SubscriptionResponse.model_validate(sub),
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


async def stripe_webhook(request, background_task, db):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    event = None
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except Exception:
        logger.exception("error verifying signature")
        raise HTTPException(status_code=400, detail="invalid signature")
    metadata = event["data"]["object"].get("metadata", {})
    if metadata.get("type") == "membership":
        logger.info(
            f"Received webhook for membership subscription event: {event['type']} with metadata: {metadata}"
        )
        membership_id = metadata.get("membership_id")
        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            stripe_session_id = session["id"]
            stmt = await db.execute(
                select(Subscription).where(
                    Subscription.reference_id == stripe_session_id
                )
            )
            sub = stmt.scalar_one_or_none()
            if not sub:
                logger.error(
                    "subscription table was not initialised for payment_ref: %s",
                    stripe_session_id,
                )
                return {
                    "status": "failed",
                    "message": "subscription record not found in database",
                }
            now = datetime.now(timezone.utc)
            if sub.expire_at > now:
                sub.expire_at = sub.expire_at + text("INTERVAL '30 days'")
            background_task.add_task(membership_activation, membership_id)
            try:
                await db.commit()
            except IntegrityError:
                logger.error(
                    "database error while saving subscription status and transaction id on webhook endpoint"
                )
                raise HTTPException(status_code=400, detail="database error")
            except Exception:
                logger.exception(
                    "error while saving subscription status and transaction id on webhook endpoint"
                )
                raise HTTPException(status_code=500, detail="internal server error")
            logger.info(
                f"Subscription {stripe_session_id} marked as completed and active."
            )
            return {
                "status": "success",
                "message": "subscription status updated",
            }
        elif event["type"] == "checkout.session.failed":
            session = event["data"]["object"]
            stripe_session_id = session["id"]
            stmt = await db.execute(
                select(Subscription).where(
                    Subscription.reference_id == stripe_session_id
                )
            )
            sub = stmt.scalar_one_or_none()
            if not sub:
                logger.error(
                    "subscription table was not initialised for failed payment_ref: %s",
                    stripe_session_id,
                )
                return {
                    "status": "failed",
                    "message": "subscription record not found in database",
                }
            background_task.add_task(membership_activation, membership_id)
            try:
                await db.commit()
            except IntegrityError:
                logger.error(
                    "database error while saving failed membership subscription status on webhook endpoint"
                )
                raise HTTPException(status_code=400, detail="database error")
            except Exception:
                logger.exception(
                    "error while saving failed membership subscription status on webhook endpoint"
                )
                raise HTTPException(status_code=500, detail="internal server error")
            logger.info(f"Membership subscription marked as failed and inactive.")
            return {
                "status": "failed",
                "message": "subscription payment failed, membership deactivated",
            }
        elif event["type"] == "checkout.session.expired":
            session = event["data"]["object"]
            stripe_session_id = session["id"]
            stmt = await db.execute(
                select(Subscription).where(
                    Subscription.reference_id == stripe_session_id
                )
            )
            sub = stmt.scalar_one_or_none()
            if not sub:
                logger.error(
                    "subscription table was not initialised for expired payment_ref: %s",
                    stripe_session_id,
                )
                return {
                    "status": "failed",
                    "message": "subscription record not found in database",
                }
            background_task.add_task(membership_activation, membership_id)
            try:
                await db.commit()
            except IntegrityError:
                logger.error(
                    "database error while saving expired membership subscription status on webhook endpoint"
                )
                raise HTTPException(status_code=400, detail="database error")
            except Exception:
                logger.exception(
                    "error while saving expired membership subscription status on webhook endpoint"
                )
                raise HTTPException(status_code=500, detail="internal server error")
            logger.info(f"Membership subscription marked as expired and inactive.")
            return {
                "status": "failed",
                "message": "membership subscription payment expired, membership deactivated",
            }
    if metadata.get("type") == "order_payment":
        logger.info(
            f"Received webhook for order payment event: {event['type']} with metadata: {metadata}"
        )
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
