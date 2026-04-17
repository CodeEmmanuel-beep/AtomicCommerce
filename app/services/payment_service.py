from fastapi import HTTPException, Query
from app.logs.logger import get_logger
import stripe
from sqlalchemy import select, text, func, or_, update, case, literal
from sqlalchemy.exc import IntegrityError
from app.models import (
    Subscription,
    Payment,
    Order,
    Membership,
    PaymentStatus,
    OrderStatus,
)
from app.api.v1.schemas import PaymentResponse, SubscriptionResponse
from app.database.config import settings
from app.database.get import AsyncSessionLocal
from datetime import datetime, timezone, timedelta

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
                        Order.created_at
                        < datetime.now(timezone.utc) - timedelta(hours=5),
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
                                "unit_amount": (
                                    int(sub.plan_price * 100) if sub.plan_price else 0
                                ),
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
                            "price": sub.price_id if sub.price_id else "",
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


async def update_payment(sub_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthourized attempt at update_payment endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    sub = (
        await db.execute(select(Subscription)).where(Subscription.id == sub_id)
    ).scalar_one_or_none()
    if not sub:
        logger.warning(
            "user: %s, tried assessing update_payment endpoint withouth being a subscriber",
            user_id,
        )
        raise HTTPException(status_code=404, detail="subscription not found")
    portal_session = stripe.billing_portal.Session.create(
        customer=sub.customer_id, return_url="https://example.com/account"
    )
    return {"bill_update_linK": portal_session.url}


async def stripe_webhook(request, background_task):
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature")
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
            sub_id = session.get("subscription", None)
            event_type = literal(event["type"])
            expire_case = case(
                (
                    event_type == "checkout.session.completed",
                    func.greatest(
                        Subscription.expire_at, func.now() + text("INTERVAL '30 days'")
                    ),
                ),
                (
                    event_type == "invoice.paid",
                    datetime.fromtimestamp(
                        session["current_period_end"], tz=timezone.utc
                    ),
                ),
                (
                    event_type == "customer.subscription.updated",
                    datetime.fromtimestamp(
                        session["current_period_end"], tz=timezone.utc
                    ),
                ),
                else_=Subscription.expire_at,
            )
            status_case = case(
                (event_type == "checkout.session.completed", "active"),
                (event_type == "invoice.paid", "active"),
                (event_type == "customer.subscription.updated", "active"),
                (event_type == "customer.subscription.deleted", "cancelled"),
                (event_type == "checkout.session.failed", "past_due"),
                (event_type == "invoice.payment_failed", "past_due"),
                (event_type == "checkout.session.expired", "past_due"),
                else_=Subscription.status,
            )
            reference_status = case(
                (event_type == "checkout.session.completed", session["id"]),
                (event_type == "invoice.paid", session.get("subscription")),
                (
                    event_type == "customer.subscription.updated",
                    session.get("subscription"),
                ),
                (
                    event_type == "customer.subscription.deleted",
                    session.get("subscription"),
                ),
                (event_type == "checkout.session.failed", session["id"]),
                (
                    event_type == "invoice.payment_failed",
                    session.get("subscription"),
                ),
                (event_type == "checkout.session.expired", session["id"]),
                else_=Subscription.reference_id,
            )
            idem = await db.execute(
                update(Subscription)
                .where(
                    or_(
                        Subscription.reference_id == stripe_session_id,
                        Subscription.reference_id == sub_id,
                    ),
                    Subscription.last_event_at < event["created"],
                    Subscription.last_event_id != event["id"],
                )
                .values(
                    last_event_id=event["id"],
                    customer_id=session.get("customer", Subscription.customer_id),
                    expire_at=expire_case,
                    status=status_case,
                    reference_id=reference_status,
                    last_event_at=func.now(),
                )
                .returning(Subscription.id)
            )
            if not idem.scalar():
                logger.info(
                    f"Subscription {membership_id} already processed. Skipping."
                )
                return {"status": "success", "message": "already processed"}
        if metadata.get("type") == "order_payment":
            logger.info(
                f"Received webhook for order payment event: {event['type']} with metadata: {metadata}"
            )
            actual_transaction_id = session["payment_intent"]
            event_type = literal(event["type"])
            payment_status_case = case(
                (event_type == "checkout.session.completed", PaymentStatus.SUCCESS),
                (event_type == "checkout.session.expired", PaymentStatus.FAILED),
                else_=Payment.payment_status,
            )
            order_status_case = case(
                (event_type == "checkout.session.completed", OrderStatus.processing),
                (event_type == "checkout.session.expired", OrderStatus.pending),
                else_=Order.status,
            )
            transaction_id_case = case(
                (event_type == "checkout.session.completed", actual_transaction_id),
                else_=Payment.transaction_id,
            )
            idemp = await db.execute(
                update(Payment)
                .where(
                    Payment.reference_id == stripe_session_id,
                    Payment.last_event_id != event["id"],
                )
                .values(
                    last_event_id=event["id"],
                    transaction_id=transaction_id_case,
                    payment_status=payment_status_case,
                )
                .returning(Payment.order_id)
            )
            if not idemp.scalar():
                logger.info(f"Payment {stripe_session_id} already processed. Skipping.")
                return {"status": "success", "message": "already processed"}
            order_ids = [row[0] for row in idemp.fetchall()]
            await db.execute(
                update(Order)
                .where(Order.id.in_(order_ids))
                .values(status=order_status_case)
                .returning(Order.id)
            )
        if metadata.get("type") not in ["membership", "order_payment"]:
            logger.warning(
                f"Received unhandled event type: {event['type']} with metadata: {metadata}"
            )
            return {"status": "ignored", "message": "event type not tracked"}
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
        background_task.add_task(membership_activation, membership_id)
        return {
            "status": "success",
            "message": "webhook payment processed",
        }
