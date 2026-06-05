from fastapi import HTTPException
from app.logs.logger import get_logger
from sqlalchemy import select, text, func, or_, update, case, literal, exists, cast
from sqlalchemy.exc import IntegrityError
from app.models import (
    Subscription,
    Payment,
    Order,
    Membership,
    PaymentStatus,
    OrderStatus,
    store_owners,
    store_staffs,
    Refund,
    Store,
)
from app.api.v1.schemas import (
    PaymentResponse,
    SubscriptionResponse,
    PaginatedMetadata,
    StandardResponse,
    PaginatedResponse,
)
from dateutil.relativedelta import relativedelta
from app.database.config import settings
from app.database.get import AsyncSessionLocal
from datetime import datetime, timezone
from app.utils.redis import cache, cached
from sqlalchemy.orm import selectinload
import stripe

logger = get_logger("payment")

stripe_client = stripe.StripeClient(settings.STRIPE_SECRET_KEY)


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
    one_time_subscription,
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
            payment_exists = (
                await session.execute(
                    select(Payment).where(Payment.order_id == order_id)
                )
            ).scalar_one_or_none()
            if payment_exists:
                return {
                    "message": "follow the link below to complete payment",
                    "checkout_url": payment_exists.checkout_url,
                }
            if not order:
                logger.warning(
                    f"user_id: {user_id} attempted to create payment for non-existent or already processed order_id: {order_id}"
                )
                raise HTTPException(
                    status_code=404, detail="Order not found or already processed."
                )
            try:
                intent = await stripe_client.v1.checkout.sessions.create_async(
                    params={
                        "payment_method_types": ["card"],
                        "client_reference_id": str(order.id),
                        "metadata": {
                            "user_id": str(user_id),
                            "type": "order_payment",
                            "order_id": str(order.id),
                        },
                        "line_items": [
                            {
                                "price_data": {
                                    "currency": currency,
                                    "product_data": {
                                        "name": f"Order {order.id} Payment",
                                    },
                                    "unit_amount": int(round(order.total_amount * 100)),
                                },
                                "quantity": 1,
                            }
                        ],
                        "mode": "payment",
                        "success_url": "http://localhost:8000/docs/?session_id={CHECKOUT_SESSION_ID}",
                        "cancel_url": "https://yourdomain.com/cancel",
                    }
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
                    checkout_url=intent.url,
                    shipping_fee=order.shipping_fee,
                    discount_amount=order.discount_amount,
                    tax_rate=order.tax_rate,
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
                    success_url="http://localhost:8000/docs?session_id={CHECKOUT_SESSION_ID}",
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
        logger.warning("unauthorized attempt at update_payment endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    sub = (
        await db.execute(select(Subscription).where(Subscription.id == sub_id))
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


async def charge_refund(payment_id, amount, reason, db, payload):
    user_id = payload.get("user_id")
    role = payload.get("role")
    allowed_roles = ["Admin", "Owner"]
    if not user_id or role not in allowed_roles:
        logger.error("possible security and financial breach at charge_refund endpoint")
        return {"message": "Luke 13:3"}
    stmt = select(Payment).where(Payment.id == payment_id)
    result = await db.execute(stmt)
    payment = result.scalar_one_or_none()
    if not payment:
        logger.warning("payment: %s, queried but not found", payment_id)
        raise HTTPException(status_code=404, detail="Payment record not found")
    if amount > payment.amount_paid:
        logger.warning("user: %s, tried overrefunding", user_id)
        raise HTTPException(
            status_code=400, detail="Refund amount exceeds the original payment"
        )
    try:
        refund = stripe.Refund.create(
            payment_intent=payment.transaction_id,
            amount=amount * 100,
            metadata={
                "type": "order_refund",
                "reason": reason,
                "order_id": payment.order_id,
            },
        )
    except stripe.StripeError as e:
        logger.error(f"stripe refund failed: {str(e)}")
        raise HTTPException(status_code=400, detail="payment processor declined refund")
    try:
        refund_log = Refund(
            user_id=payment.user_id,
            payment_id=payment.id,
            order_id=payment.order_id,
            refund_id=refund.id,
            refund_amount=amount,
        )
        db.add(refund_log)
        await db.commit()
    except IntegrityError:
        logger.error("database error at charge_refund endpoint")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        logger.exception("internal server error at charge_refund endpoint")
        raise HTTPException(status_code=500, detail="internal server error")
    return {"status": "success", "message": "refund logged", "refund_id": refund.id}


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
        membership_id = None
        session = event["data"]["object"]
        stripe_session_id = (
            getattr(session, "id", None)
            if "checkout.session" in event["type"]
            else getattr(session, "subscription", None)
        )
        metadata = getattr(session, "metadata", None)
        type_metadata = getattr(metadata, "type", None)
        sub_details = getattr(session, "subscription_details", {})
        subscription_metadata = getattr(sub_details, "metadata", {})
        type_subscription_metadata = getattr(subscription_metadata, "type", None)
        if "membership" in [type_metadata, type_subscription_metadata]:
            logger.info(
                f"Received webhook for membership subscription event: {event['type']} with metadata: {metadata}"
            )
            membership_id = getattr(metadata, "membership_id", None)
            sub_id = getattr(session, "subscription", None)
            event_type = literal(event["type"])
            expire_case = case(
                (
                    event_type == "checkout.session.completed",
                    func.greatest(
                        Subscription.expire_at, func.now() + text("INTERVAL '30 days'")
                    ),
                ),
                (
                    event_type == "payment_intent.succeeded",
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
                (event_type == "payment_intent.succeeded", "active"),
                (event_type == "payment_intent.payment_failed", "inactive"),
                (event_type == "invoice.paid", "active"),
                (event_type == "customer.subscription.updated", "active"),
                (event_type == "customer.subscription.deleted", "cancelled"),
                (event_type == "checkout.session.failed", "past_due"),
                (event_type == "invoice.payment_failed", "past_due"),
                (event_type == "checkout.session.expired", "past_due"),
                else_=Subscription.status,
            )
            reference_id = case(
                (event_type == "checkout.session.completed", session["id"]),
                (event_type == "invoice.paid", getattr(session, "subscription", None)),
                (
                    event_type == "customer.subscription.updated",
                    getattr(session, "subscription", None),
                ),
                (
                    event_type == "customer.subscription.deleted",
                    getattr(session, "subscription", None),
                ),
                (event_type == "payment_intent.payment_failed", session["id"]),
                (
                    event_type == "invoice.payment_failed",
                    getattr(session, "subscription", None),
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
                    customer_id=getattr(session, "customer", Subscription.customer_id),
                    expire_at=expire_case,
                    status=status_case,
                    reference_id=reference_id,
                    last_event_at=func.now(),
                )
                .returning(Subscription.id)
            )
            if not idem.scalar():
                logger.info(
                    f"Subscription {membership_id} already processed. Skipping."
                )
                return {"status": "success", "message": "already processed"}
        if type_metadata == "order_payment":
            logger.info(
                f"Received webhook for order payment event: {event['type']} with metadata: {metadata}"
            )
            if event["type"].startswith("checkout.session."):
                actual_transaction_id = getattr(session, "payment_intent", None)
            else:
                actual_transaction_id = getattr(session, "id", None)
            event_type = literal(event["type"])
            target_enum = Payment.payment_status.type
            payment_status_case = case(
                (
                    event_type == "checkout.session.completed",
                    cast(PaymentStatus.SUCCESS.value, target_enum),
                ),
                (
                    event_type == "payment_intent.succeeded",
                    cast(PaymentStatus.SUCCESS.value, target_enum),
                ),
                (
                    event_type == "checkout.session.expired",
                    cast(PaymentStatus.FAILED.value, target_enum),
                ),
                (
                    event_type == "payment_intent.payment_failed",
                    cast(PaymentStatus.FAILED.value, target_enum),
                ),
                else_=Payment.payment_status,
            )
            order_status_case = case(
                (event_type == "checkout.session.completed", OrderStatus.processing),
                (event_type == "payment_intent.succeeded", OrderStatus.processing),
                (event_type == "payment_intent.payment_failed", OrderStatus.pending),
                (event_type == "checkout.session.expired", OrderStatus.pending),
                else_=Order.status,
            )
            transaction_id_case = case(
                (event_type == "checkout.session.completed", actual_transaction_id),
                (event_type == "payment_intent.succeeded", actual_transaction_id),
                (event_type == "payment_intent.payment_failed", actual_transaction_id),
                else_=Payment.transaction_id,
            )
            event_timer = event["created"]
            event_timestamp = datetime.fromtimestamp(event_timer, tz=timezone.utc)
            idemp = await db.execute(
                update(Payment)
                .where(
                    Payment.reference_id == stripe_session_id,
                    or_(
                        Payment.last_event_at.is_(None),
                        Payment.last_event_at < event_timestamp,
                    ),
                    or_(
                        Payment.last_event_id.is_(None),
                        Payment.last_event_id != event["id"],
                    ),
                )
                .values(
                    last_event_id=event["id"],
                    last_event_at=event_timestamp,
                    transaction_id=transaction_id_case,
                    payment_status=payment_status_case,
                )
                .returning(Payment.order_id)
            )
            rows = idemp.fetchall()
            if not rows:
                logger.info(f"Payment {stripe_session_id} already processed. Skipping.")
                return {"status": "success", "message": "already processed"}
            order_ids = [row[0] for row in rows]
            await db.execute(
                update(Order)
                .where(Order.id.in_(order_ids))
                .values(status=order_status_case)
                .returning(Order.id)
            )
        if type_metadata == "order_refund":
            if event["type"] == "charge.refunded":
                idempo = await db.execute(
                    update(Refund)
                    .where(
                        Refund.refund_id == stripe_session_id,
                        Refund.last_event_id != event["id"],
                    )
                    .values(last_event_id=event["id"])
                    .returning(Refund.payment_id)
                )
                refunded = idempo.scalar_one_or_none()
                if not refunded:
                    logger.info(
                        f"Payment {stripe_session_id} already processed. Skipping."
                    )
                    return {"status": "success", "message": "already processed"}
                payment_id = int(refunded)
                await db.execute(
                    update(Payment)
                    .where(Payment.id == payment_id)
                    .values(
                        payment_status=cast(PaymentStatus.REFUNDED.value, target_enum)
                    )
                )
        if type_metadata not in ["membership", "order_payment", "order_refund"]:
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
        if membership_id:
            background_task.add_task(membership_activation, membership_id)
        return {
            "status": "success",
            "message": "webhook payment processed",
        }


async def get_payment(store_id, payment_status, time_frame, page, limit, db, payload):
    user_id = payload.get("user_id")
    role = payload.get("role")
    allowed_roles = ["Admin", "Owner"]
    if not user_id:
        logger.warning("unauthorized attempt at get_payment endpoint")
        raise HTTPException(status_code=401, detail="unauthorized attempt")
    cache_key = f"payment_list:{store_id}:{payment_status}:{time_frame}:{page}:{limit}"
    payment_cache = await cache(cache_key)
    if payment_cache:
        logger.info(
            f"cache hit at get_payment_endpoint for payment_status: {payment_status}, page:{page}"
        )
        return StandardResponse(**payment_cache)
    if page <= 0 or limit <= 0:
        raise HTTPException(
            status_code=400, detail="page and limit should be atleast 1"
        )
    check = (
        await db.execute(
            select(
                or_(
                    exists().where(
                        store_owners.c.users_id == user_id,
                        store_owners.c.stores_id == store_id,
                    ),
                    exists().where(
                        store_staffs.c.users_id == user_id,
                        store_staffs.c.stores_id == store_id,
                    ),
                )
            )
        )
    ).scalar()
    if not check and role not in allowed_roles:
        logger.warning(
            "user: %s, tried accessing get_payment endpoint without appropriate credentials",
            user_id,
        )
        raise HTTPException(status_code=403, detail="restricted access")
    store = (
        await db.execute(select(Store).where(Store.id == store_id))
    ).scalar_one_or_none()
    if not store:
        logger.warning(
            "user: %s, search for payment history for a store that does not exist store: %s",
            user_id,
            store_id,
        )
        raise HTTPException(status_code=404, detail="store not found")
    offset = (page - 1) * limit
    payment_list_stmt = (
        select(Payment)
        .join(Order, Payment.order_id == Order.id)
        .options(selectinload(Payment.order).selectinload(Order.store))
        .where(Order.store_id == store_id)
    )
    now = datetime.now(timezone.utc)
    time_map = {
        "1 year": now - relativedelta(years=1),
        "6 months": now - relativedelta(months=6),
        "3 months": now - relativedelta(months=3),
        "1 month": now - relativedelta(months=1),
        "1 week": now - relativedelta(days=7),
    }
    time_period = time_map.get(time_frame)
    if not time_period:
        return {
            "status": "error",
            "message": "invalid time frame selected",
        }
    if store.founded > time_period:
        return {
            "status": "error",
            "message": f"store's existence is below {time_frame}",
        }
    status_map = {
        "approved": PaymentStatus.SUCCESS.value,
        "pending": PaymentStatus.PENDING.value,
        "refunds": PaymentStatus.REFUNDED.value,
        "failed": PaymentStatus.FAILED.value,
    }
    status_value = status_map.get(payment_status, None)
    if not status_value:
        return {
            "status": "error",
            "message": "invalid payment status selected",
        }
    payment_list = payment_list_stmt.where(
        Payment.payment_status == status_value, Payment.payment_date >= time_period
    ).order_by(Payment.payment_date.desc())
    result = (
        (await db.execute(payment_list.offset(offset).limit(limit))).scalars().all()
    )
    if not result:
        logger.info(f"store: {store_id}, has no {payment_status} payments")
        return {
            "status": "success",
            "message": f"this store has no {payment_status} payments",
        }
    total = (
        await db.execute(
            select(func.count(Payment.id))
            .join(Order)
            .where(
                Order.store_id == store_id,
                Payment.payment_status == status_value,
                Payment.payment_date >= time_period,
            )
        )
    ).scalar() or 0
    logger.info("total '%s', payments is: %s", payment_status, total)
    data = PaginatedMetadata[PaymentResponse](
        items=[PaymentResponse.model_validate(res) for res in result],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    full_response = StandardResponse(
        status="success", message=f"{payment_status} payments", data=data
    )
    await cached(cache_key, full_response, ttl=360)
    return full_response
