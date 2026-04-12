from fastapi import HTTPException, Query
from app.logs.logger import get_logger
import stripe
from sqlalchemy import select, text, func, or_
from sqlalchemy.exc import IntegrityError
from app.models import Subscription, Payment, Order, Membership, PaymentStatus
from app.api.v1.schemas import PaymentResponse, SubscriptionResponse
from app.database.config import settings
from app.database.get import AsyncSessionLocal
from datetime import datetime, timezone
from app.database.config import settings

logger = get_logger("payment")

stripe.api_key = settings.STRIPE_SECRET_KEY


async def membership_activation(membership_id):
    async with AsyncSessionLocal() as db:
        try:
            async with db.begin():
                stmt = await db.execute(
                    select(Membership, Subscription).where(
                        Membership.id == membership_id
                    )
                )
                result = stmt.first()
                if not result:
                    logger.error(
                        "membership_id: %s not linked to subscription table",
                        membership_id,
                    )
                    return
                member, subscription = result
                now = datetime.now(timezone.utc)
                up_to_date = subscription.expire_at > now
                if member.is_active == up_to_date:
                    logger.info(
                        f"Membership status for membership_id: {membership_id} is already up to date. No changes made."
                    )
                    return
                member.is_active = up_to_date
                logger.info(
                    f"Membership status of member: {membership_id} updated successfully in background task."
                )
        except IntegrityError:
            logger.error(
                f"Database error occurred while updating membership_id: {membership_id} in background task"
            )
        except Exception:
            logger.exception(
                f"Unexpected error occurred while updating membership_id: {membership_id} in background task"
            )


async def create_payment(
    membership_id,
    order_id,
    currency,
    payload,
    one_time_subscription: str = Query("one_time", enum=["one_time", "subscription"]),
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
            try:
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
            except stripe.StripeError as e:
                logger.error(f"Stripe error occurred: {e.user_message}")
                raise HTTPException(
                    status_code=400, detail=f"Stripe error: {e.user_message}"
                )
            try:
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
            except IntegrityError:
                await session.rollback()
                logger.error(
                    f"Database error occurred while creating payment for user_id: {user_id}"
                )
                raise HTTPException(
                    status_code=500,
                    detail="Database error occurred while processing payment.",
                )
            except Exception:
                await session.rollback()
                logger.exception(
                    f"Unexpected error occurred while creating payment for user_id: {user_id}"
                )
                raise HTTPException(
                    status_code=500,
                    detail="An unexpected error occurred while processing payment.",
                )
        if membership_id and one_time_subscription == "one_time":
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
            try:
                subscription = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    client_reference_id=str(user_id),
                    metadata={
                        "user_id": str(user_id),
                        "type": "membership",
                        "payment_type": "one_time",
                        "membership_id": str(membership_id),
                    },
                    line_items=[
                        {
                            "price_data": {
                                "currency": currency,
                                "product_data": {
                                    "name": f"membership one time payment for {sub.plan_name} plan"
                                },
                                "unit_amount": int(sub.plan_price * 100),
                            },
                            "quantity": 1,
                        }
                    ],
                    mode="payment",
                    success_url="https://yourdomain.com/success?session_id={CHECKOUT_SESSION_ID}",
                    cancel_url="https://yourdomain.com/cancel",
                )
                logger.info(
                    f"subscription payment created successfully for user_id: {user_id}, subscription_plan: {sub.plan_name}"
                )
            except stripe.StripeError as e:
                logger.error(f"Stripe error occurred: {e.user_message}")
                raise HTTPException(
                    status_code=400, detail=f"Stripe error: {e.user_message}"
                )
            try:
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
            except IntegrityError:
                await session.rollback()
                logger.error(
                    f"Database error occurred while creating payment for user_id: {user_id}"
                )
                raise HTTPException(
                    status_code=500,
                    detail="Database error occurred while processing payment.",
                )
            except Exception:
                await session.rollback()
                logger.exception(
                    f"Unexpected error occurred while creating payment for user_id: {user_id}"
                )
                raise HTTPException(
                    status_code=500,
                    detail="An unexpected error occurred while processing payment.",
                )
        if membership_id and one_time_subscription == "subscription":
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
            try:
                subscription = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    client_reference_id=str(user_id),
                    metadata={
                        "user_id": str(user_id),
                        "type": "membership",
                        "payment_type": "subscription",
                        "membership_id": str(membership_id),
                    },
                    subscription_data={
                        "metadata": {
                            "user_id": str(user_id),
                            "type": "membership",
                            "payment_type": "subscription",
                            "membership_id": str(membership_id),
                        },
                    },
                    line_items=[
                        {
                            "price": sub.price_id,
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
            except stripe.StripeError as e:
                logger.error(f"Stripe error occurred: {e.user_message}")
                raise HTTPException(
                    status_code=400, detail=f"Stripe error: {e.user_message}"
                )
            try:
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
            except IntegrityError:
                await session.rollback()
                logger.error(
                    f"Database error occurred while creating payment for user_id: {user_id}"
                )
                raise HTTPException(
                    status_code=500,
                    detail="Database error occurred while processing payment.",
                )
            except Exception:
                await session.rollback()
                logger.exception(
                    f"Unexpected error occurred while creating payment for user_id: {user_id}"
                )
                raise HTTPException(
                    status_code=500,
                    detail="An unexpected error occurred while processing payment.",
                )


async def update_payment(sub_id, db):
    sub = (
        await db.execute(select(Subscription)).where(Subscription.id == sub_id)
    ).scalar_one_or_none()
    portal_session = stripe.billing_portal.Session.create(
        customer=sub.customer_id, return_url="https://example.com/account"
    )
    return {"bill_update_linK": portal_session.url}


async def stripe_webhook(request, background_task):
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
    async with AsyncSessionLocal() as db:
        session = event["data"]["object"]
        stripe_session_id = (
            session.get("id")
            if "checkout.session" in event["type"]
            else session.get("subscription")
        )
        metadata = session.get("metadata", {})
        sub_details = session.get("subscription_details", {})
        subscription_metadata = sub_details.get("metadata", {})
        if "membership" in [metadata.get("type"), subscription_metadata.get("type")]:
            logger.info(
                f"Received webhook for membership subscription event: {event['type']} with metadata: {metadata}"
            )
            membership_id = metadata.get("membership_id")
            sub_id = session["subscription"] if "subscription" in session else None
            stmt = await db.execute(
                select(Subscription)
                .where(
                    or_(
                        Subscription.reference_id == stripe_session_id,
                        Subscription.reference_id == sub_id,
                    )
                )
                .with_for_update()
            )
            sub = stmt.scalar_one_or_none()
            if not sub:
                logger.error(
                    "subscription table was not initialised for payment_ref: %s, subscription_id: %s",
                    stripe_session_id,
                    sub_id,
                )
                return {
                    "status": "failed",
                    "message": "subscription record not found in database",
                }
            if sub.last_event_id == event["id"]:
                logger.info(
                    f"Subscription {membership_id} already processed. Skipping."
                )
                return {"status": "success", "message": "already processed"}
            sub.last_event_id = event["id"]
            sub.customer_id = session["customer"]
            if event["type"] in ["checkout.session.completed", "invoice.paid"]:
                now = datetime.now(timezone.utc)
                sub.expire_at = func.greatest(sub.expire_at, now) + text(
                    "INTERVAL '30 days'"
                )
                sub.reference_id = sub_id if sub_id else sub.reference_id
                sub.status = "active"
                try:
                    await db.commit()
                except IntegrityError:
                    await db.rollback()
                    logger.error(
                        "database error while saving subscription status and transaction id on webhook endpoint"
                    )
                    raise HTTPException(status_code=400, detail="database error")
                except Exception:
                    await db.rollback()
                    logger.exception(
                        "error while saving subscription status and transaction id on webhook endpoint"
                    )
                    raise HTTPException(status_code=500, detail="internal server error")
                logger.info(
                    f"Subscription {stripe_session_id} marked as completed and active."
                )
                background_task.add_task(membership_activation, membership_id)
                return {
                    "status": "success",
                    "message": "subscription status updated",
                }
            elif event["type"] == "customer.subscription.updated":
                sub.expire_at = datetime.fromtimestamp(
                    session["current_period_end"], tz=timezone.utc
                )
                sub.status = session["status"]
                try:
                    await db.commit()
                except IntegrityError:
                    await db.rollback()
                    logger.error(
                        "database error updating subscription %s", sub.reference_id
                    )
                    raise HTTPException(status_code=400, detail="database error")
                except Exception:
                    await db.rollback()
                    logger.exception("error updating subscription %s", sub.reference_id)
                    raise HTTPException(status_code=500, detail="internal server error")
                background_task.add_task(membership_activation, membership_id)
                return {"status": "success", "message": "subscription updated"}
            elif event["type"] in ["checkout.session.failed", "invoice.payment_failed"]:
                sub.status = "past_due"
                background_task.add_task(membership_activation, membership_id)
                try:
                    await db.commit()
                except IntegrityError:
                    await db.rollback()
                    logger.error(
                        "database error while saving failed subscription status on webhook endpoint"
                    )
                    raise HTTPException(status_code=400, detail="database error")
                except Exception:
                    await db.rollback()
                    logger.exception(
                        "error while saving failed subscription status on webhook endpoint"
                    )
                    raise HTTPException(status_code=500, detail="internal server error")
                logger.info("Membership subscription marked as failed and inactive.")
                return {
                    "status": "failed",
                    "message": "subscription payment failed, membership deactivated",
                }
            elif event["type"] == "customer.subscription.deleted":
                sub.status = "canceled"
                background_task.add_task(membership_activation, sub.membership_id)
                try:
                    await db.commit()
                except IntegrityError:
                    await db.rollback()
                    logger.exception(
                        "database error deleting subscription %s", sub.reference_id
                    )
                    raise HTTPException(status_code=400, detail="database error")
                except Exception:
                    await db.rollback()
                    logger.exception("error deleting subscription %s", sub.reference_id)
                    raise HTTPException(status_code=500, detail="internal server error")
                return {"status": "success", "message": "subscription canceled"}
            elif event["type"] == "checkout.session.expired":
                background_task.add_task(membership_activation, membership_id)
                try:
                    await db.commit()
                except IntegrityError:
                    await db.rollback()
                    logger.error(
                        "database error updating subscription %s", sub.reference_id
                    )
                    raise HTTPException(status_code=400, detail="database error")
                except Exception:
                    await db.rollback()
                    logger.exception("error updating subscription %s", sub.reference_id)
                    raise HTTPException(status_code=500, detail="internal server error")
                return {
                    "status": "failed",
                    "message": "membership subscription payment expired, membership deactivated",
                }
        if metadata.get("type") == "order_payment":
            logger.info(
                f"Received webhook for order payment event: {event['type']} with metadata: {metadata}"
            )
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
            if payment.last_event_id == event["id"]:
                logger.info(f"Payment {stripe_session_id} already processed. Skipping.")
                return {"status": "success", "message": "already processed"}
            payment.last_event_id = event["id"]
            if event["type"] == "checkout.session.completed":
                payment.transaction_id = actual_transaction_id
                payment.payment_status = PaymentStatus.SUCCESS
                payment.order.status = "processing"
                try:
                    await db.commit()
                except IntegrityError:
                    await db.rollback()
                    logger.error(
                        "database error while saving payment status and transaction id on webhook endpoint"
                    )
                    raise HTTPException(status_code=400, detail="database error")
                except Exception:
                    await db.rollback()
                    logger.exception(
                        "error while saving payment status and transaction id on webhook endpoint"
                    )
                    raise HTTPException(status_code=500, detail="internal server error")
                logger.info(f"Payment {stripe_session_id} marked as completed.")
                return {"status": "success", "message": "payment status updated"}
            elif event["type"] == "checkout.session.expired":
                payment.payment_status = PaymentStatus.FAILED
                payment.order.status = "pending"
                try:
                    await db.commit()
                except IntegrityError:
                    await db.rollback()
                    logger.error(
                        "database error while saving expired payment status on webhook endpoint"
                    )
                    raise HTTPException(status_code=400, detail="database error")
                except Exception:
                    await db.rollback()
                    logger.exception(
                        "error while saving expired payment status on webhook endpoint"
                    )
                    raise HTTPException(status_code=500, detail="internal server error")
                logger.info("Payment marked as expired and failed.")
                return {
                    "status": "failed",
                    "message": "payment expired, order status reverted to pending",
                }
        if metadata.get("type") not in ["membership", "order_payment"]:
            logger.warning(
                f"Received unhandled event type: {event['type']} with metadata: {metadata}"
            )
            return {"status": "ignored", "message": "event type not tracked"}
