from fastapi import HTTPException
from app.logs.logger import get_logger
from sqlalchemy import (
    select,
    text,
    func,
    or_,
    update,
    case,
    literal,
    exists,
    cast,
)
from sqlalchemy.exc import IntegrityError
from app.models import (
    Subscription,
    Payment,
    SubscriptionStatus,
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
target_enum = Payment.payment_status.type


async def membership_activation(membership_id, user_id):
    async with AsyncSessionLocal() as db:
        try:
            async with db.begin():
                stmt = await db.execute(
                    select(Membership, Subscription)
                    .join(Subscription, Membership.id == Subscription.membership_id)
                    .where(
                        Membership.id == membership_id, Membership.user_id == user_id
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
            if not order:
                logger.warning(
                    f"user_id: {user_id} attempted to create payment for non-existent or already processed order_id: {order_id}"
                )
                raise HTTPException(
                    status_code=404, detail="Order not found or already processed."
                )
            payment_exist = (
                await session.execute(
                    select(Payment).where(
                        Payment.order_id == order_id,
                    )
                )
            ).scalar_one_or_none()
            if (
                payment_exist
                and payment_exist.payment_status == PaymentStatus.PENDING.value
            ):
                return StandardResponse(
                    status="success",
                    message="follow the link below to complete payment",
                    data=payment_exist.checkout_url,
                )
            if (
                payment_exist
                and payment_exist.payment_status == PaymentStatus.SUCCESS.value
            ):
                logger.info(
                    f"user_id: {user_id} attempted to pay for order_id: {order_id} which is already paid"
                )
                raise HTTPException(
                    status_code=409,
                    detail="payment for this order has already been completed",
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
                if payment_exist:
                    await session.execute(
                        select(Payment)
                        .where(Payment.id == payment_exist.id)
                        .with_for_update()
                    )
                    updated_fields = {
                        "payment_status": PaymentStatus.PENDING.value,
                        "total_amount": order.total_amount,
                        "currency": currency,
                        "payment_method": "card",
                        "reference_id": intent.id,
                        "checkout_url": intent.url,
                        "transaction_id": None,
                        "last_event_id": None,
                        "last_event_at": None,
                    }
                    for attr, field in updated_fields.items():
                        setattr(payment_exist, attr, field)
                    log_action = "updated"
                    target_payment = payment_exist
                else:
                    payment = Payment(
                        user_id=user_id,
                        order_id=order.id,
                        total_amount=order.total_amount,
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
                    log_action = "created"
                    target_payment = payment
                await session.commit()
                await session.refresh(target_payment)
                logger.info(
                    f"Payment {log_action} successfully for user_id: {user_id}, amount: {order.total_amount} {currency}"
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
            except Exception:
                await session.rollback()
                logger.exception(
                    f"Unexpected error occurred while creating payment for user_id: {user_id}"
                )
                raise HTTPException(
                    status_code=500,
                    detail="An unexpected error occurred while processing payment.",
                )
            data = {
                "checkout_url": intent.url,
                "payment details": PaymentResponse.model_validate(
                    target_payment
                ).model_dump(exclude_none=True),
            }
            return StandardResponse(
                status="success",
                message="follow the link below to complete your payment",
                data=data,
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
                member_payment = await stripe_client.v1.checkout.sessions.create_async(
                    params={
                        "payment_method_types": ["card"],
                        "client_reference_id": str(user_id),
                        "metadata": {
                            "user_id": str(user_id),
                            "type": "membership",
                            "payment_type": "one_time",
                            "membership_id": str(membership_id),
                        },
                        "line_items": [
                            {
                                "price_data": {
                                    "currency": currency,
                                    "product_data": {
                                        "name": f"membership one time payment for {sub.plan_name} plan"
                                    },
                                    "unit_amount": (
                                        int(sub.plan_price * 100)
                                        if sub.plan_price
                                        else 0
                                    ),
                                },
                                "quantity": 1,
                            }
                        ],
                        "mode": "payment",
                        "success_url": "http://localhost:8000/docs?session_id={CHECKOUT_SESSION_ID}",
                        "cancel_url": "https://yourdomain.com/cancel",
                    }
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
                await session.execute(
                    select(Subscription)
                    .where(Subscription.id == sub.id)
                    .with_for_update()
                )
                sub.reference_id = member_payment.id
                session.add(sub)
                await session.commit()
                await session.refresh(sub)
                data = {
                    "checkout_url": member_payment.url,
                    "subscription details": SubscriptionResponse.model_validate(
                        sub
                    ).model_dump(exclude_none=True),
                }
                return StandardResponse(
                    status="success",
                    message="subscription payment initiated, complete payment to activate membership",
                    data=data,
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
            if sub.status == SubscriptionStatus.active:
                raise HTTPException(
                    status_code=409, detail="you have already subscribed"
                )
            try:
                member_subscription = await stripe_client.v1.checkout.sessions.create_async(
                    params={
                        "payment_method_types": ["card"],
                        "client_reference_id": str(user_id),
                        "metadata": {
                            "user_id": str(user_id),
                            "type": "membership",
                            "payment_type": "subscription",
                            "membership_id": str(membership_id),
                        },
                        "subscription_data": {
                            "metadata": {
                                "user_id": str(user_id),
                                "type": "membership",
                                "payment_type": "subscription",
                                "membership_id": str(membership_id),
                            },
                        },
                        "line_items": [
                            {
                                "price": sub.price_id if sub.price_id else "",
                                "quantity": 1,
                            }
                        ],
                        "mode": "subscription",
                        "success_url": "http://localhost:8000?session_id={CHECKOUT_SESSION_ID}",
                        "cancel_url": "https://yourdomain.com/cancel",
                    }
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
                await session.execute(
                    select(Subscription)
                    .where(Subscription.id == sub.id)
                    .with_for_update()
                )
                sub.reference_id = member_subscription.id
                session.add(sub)
                await session.commit()
                await session.refresh(sub)
                data = {
                    "checkout_url": member_subscription.url,
                    "subscription details": SubscriptionResponse.model_validate(
                        sub
                    ).model_dump(exclude_none=True),
                }
                return StandardResponse(
                    status="success",
                    message="subscription payment initiated, complete payment to activate membership",
                    data=data,
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
    data = {"bill_update_linK": portal_session.url}
    return StandardResponse(
        status="success",
        message="follow the link below to update your subscription",
        data=data,
    )


async def charge_refund(payment_id, amount, reason, db, payload):
    user_id = payload.get("user_id")
    role = payload.get("role")
    allowed_roles = ["Admin", "Owner"]
    if not user_id or role not in allowed_roles:
        logger.error("possible security and financial breach at charge_refund endpoint")
        raise HTTPException(status_code=401, detail="Luke 13:3")
    stmt = select(Payment).where(Payment.id == payment_id).with_for_update()
    result = await db.execute(stmt)
    payment = result.scalar_one_or_none()
    if not payment:
        logger.warning("payment: %s, queried but not found", payment_id)
        raise HTTPException(status_code=404, detail="Payment record not found")
    if payment.payment_status not in [
        PaymentStatus.SUCCESS.value,
        PaymentStatus.REFUNDED.value,
    ]:
        logger.critical(
            "user: %s, tried reufunding a payment that was nopt successful", user_id
        )
        raise HTTPException(status_code=400, detail="payment was not successful")
    if amount > payment.total_amount:
        logger.warning("user: %s, tried overrefunding", user_id)
        raise HTTPException(
            status_code=400, detail="Refund amount exceeds the original payment"
        )
    refunded_so_far = (
        await db.execute(
            select(func.coalesce(func.sum(Refund.refund_amount), 0)).where(
                Refund.payment_id == payment.id
            )
        )
    ).scalar()
    remaining = payment.total_amount - refunded_so_far
    if amount > remaining:
        raise HTTPException(
            status_code=400, detail="Refund amount exceeds remaining refundable balance"
        )
    try:
        refund = await stripe_client.v1.refunds.create_async(
            params={
                "payment_intent": payment.transaction_id,
                "amount": int(round(amount * 100)),
                "metadata": {
                    "type": "order_refund",
                    "reason": reason,
                    "order_id": str(payment.order_id),
                },
            }
        )
    except stripe.StripeError as e:
        logger.error(f"stripe refund failed: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"payment processor declined refund: {e.user_message}",
        )
    try:
        refund_log = Refund(
            user_id=payment.user_id,
            payment_id=payment.id,
            refund_reason=reason,
            order_id=payment.order_id,
            refund_id=refund.id,
            refund_amount=amount,
        )
        db.add(refund_log)
        await db.commit()
    except Exception as db_err:
        logger.critical(
            f"FATAL STATE MISMATCH: Stripe refund {refund.id} succeeded for amount {amount}, "
            f"but database tracking write failed! Manual reconcile required for order_id {payment.order_id}. Error: {str(db_err)}"
        )
        raise HTTPException(status_code=500, detail="internal server error")
    data = {"refund_id": refund.id}
    return StandardResponse(status="success", message="refund logged", data=data)


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
        user_id = None
        session = event["data"]["object"]
        stripe_session_id = getattr(session, "id", None)
        created_at = getattr(session, "created", None)
        created_timestamp = (
            datetime.fromtimestamp(created_at, tz=timezone.utc)
            if created_at
            else datetime.now(timezone.utc)
        )
        metadata = getattr(session, "metadata", None)
        type_metadata = getattr(metadata, "type", None)
        sub_details = getattr(session, "subscription_details", {})
        subscription_metadata = getattr(sub_details, "metadata", {})
        type_subscription_metadata = getattr(subscription_metadata, "type", None)
        VALID_SUCCESS_EVENTS = (
            "checkout.session.completed",
            "payment_intent.succeeded",
            "charge.succeeded",
        )
        VALID_FAILURE_EVENTS = (
            "checkout.session.expired",
            "payment_intent.payment_failed",
            "charge.failed",
        )
        if (
            "membership" in [type_metadata, type_subscription_metadata]
            and event["type"] != "charge.updated"
        ):
            logger.info(
                f"Received webhook for membership subscription event: {event['type']} with metadata: {metadata}"
            )
            membership_id_str = (
                getattr(metadata, "membership_id", None)
                if hasattr(metadata, "membership_id")
                else metadata.get("membership_id") if metadata else None
            )
            sub_id = getattr(session, "subscription", None)
            membership_id = int(membership_id_str) if membership_id_str else None
            user_id_str = (
                getattr(metadata, "user_id", None)
                if hasattr(metadata, "user_id")
                else metadata.get("user_id") if metadata else None
            )
            sub_id = getattr(session, "subscription", None)
            user_id = int(user_id_str) if user_id_str else None
            payment_type = (
                getattr(metadata, "payment_type", None)
                if hasattr(metadata, "payment_type")
                else metadata.get("payment_type") if metadata else None
            )
            sub_id = getattr(session, "subscription", None)
            if not sub_id:
                sub_id = stripe_session_id
            event_type = literal(event["type"])
            subscription_days = None
            if event["type"].startswith("customer.subscription"):
                sub_items = (
                    getattr(session, "items", None)
                    if hasattr(session, "items")
                    else session.get("items")
                )
                if sub_items:
                    item_data = (
                        getattr(sub_items, "data", [])
                        if hasattr(sub_items, "data")
                        else sub_items.get("data")
                    )
                    if item_data:
                        first_data = item_data[0]
                        subscription_days = (
                            getattr(first_data, "current_period_end")
                            if hasattr(first_data, "current_period_end")
                            else first_data.get("current_period_end")
                        )
            elif event["type"].startswith("invoice"):
                lines = getattr(session, "lines", {})
                if lines:
                    lines_data = (
                        getattr(lines, "data", [])
                        if hasattr(lines, "data")
                        else lines.get("data")
                    )
                    if lines_data:
                        first_data = lines_data[0]
                        line_period = (
                            getattr(first_data, "period", {})
                            if hasattr(first_data, "period")
                            else first_data.get("period")
                        )
                        if line_period:
                            subscription_days = (
                                getattr(line_period, "end")
                                if hasattr(line_period, "end")
                                else line_period.get("end")
                            )
            if not subscription_days:
                subscription_days = getattr(session, "period_end", None)
            expire_case = case(
                (
                    event_type.in_(
                        ("checkout.session.completed", "payment_intent.succeeded")
                    ),
                    func.greatest(Subscription.expire_at, func.now())
                    + text("INTERVAL '30 days'"),
                ),
                (
                    event_type.in_(("customer.subscription.updated", "invoice.paid")),
                    func.to_timestamp(subscription_days),
                ),
                else_=Subscription.expire_at,
            )
            status_case = case(
                (
                    event_type.in_(
                        (
                            "checkout.session.completed",
                            "invoice.paid",
                            "payment_intent.succeeded",
                        )
                    ),
                    SubscriptionStatus.active,
                ),
                (
                    event_type == "customer.subscription.deleted",
                    SubscriptionStatus.cancelled,
                ),
                (
                    event_type.in_(
                        (
                            "invoice.payment_failed",
                            "checkout.session.expired",
                        )
                    ),
                    SubscriptionStatus.past_due,
                ),
                else_=Subscription.status,
            )
            reference_id = Subscription.reference_id
            if payment_type == "one_time":
                reference_id = case(
                    (
                        event_type.in_(
                            ("checkout.session.completed", "checkout.session.expired")
                        ),
                        getattr(session, "payment_intent", None),
                    ),
                    (
                        event_type.in_(
                            (
                                "payment_intent.payment_failed",
                                "payment_intent.succeeded",
                            )
                        ),
                        getattr(session, "id", None),
                    ),
                    (
                        event_type.in_(
                            (
                                "invoice.payment_failed",
                                "customer.subscription.deleted",
                                "invoice.paid",
                            )
                        ),
                        getattr(session, "subscription", None),
                    ),
                    else_=Subscription.reference_id,
                )
            elif payment_type == "subscription":
                reference_id = case(
                    (
                        event_type.in_(
                            (
                                "checkout.session.completed",
                                "checkout.session.expired",
                                "invoice.payment_failed",
                                "customer.subscription.deleted",
                                "invoice.paid",
                            )
                        ),
                        getattr(session, "subscription", None),
                    ),
                    else_=Subscription.reference_id,
                )
            membership_status_case = case(
                (
                    event_type.in_(
                        (
                            "checkout.session.completed",
                            "invoice.paid",
                            "payment_intent.succeeded",
                        )
                    ),
                    True,
                ),
                else_=Membership.is_active,
            )
            if membership_id:
                idem = await db.execute(
                    update(Subscription)
                    .where(
                        Subscription.membership_id == membership_id,
                        or_(
                            Subscription.last_event_at.is_(None),
                            Subscription.last_event_at <= created_timestamp,
                        ),
                        or_(
                            Subscription.last_event_id.is_(None),
                            Subscription.last_event_id != event["id"],
                        ),
                    )
                    .values(
                        last_event_id=event["id"],
                        customer_id=getattr(session, "customer", None)
                        or Subscription.customer_id,
                        expire_at=func.greatest(Subscription.expire_at, expire_case),
                        status=status_case,
                        reference_id=reference_id,
                        last_event_at=created_timestamp,
                    )
                    .returning(Subscription.membership_id)
                )
                returned_id = idem.scalar()
                if not returned_id:
                    logger.info(
                        f"Subscription {membership_id} already processed. Skipping."
                    )
                    return {"status": "success", "message": "already processed"}
                idempo = await db.execute(
                    update(Membership)
                    .where(Membership.id == returned_id)
                    .values(is_active=membership_status_case)
                )
        if type_metadata == "order_payment" and event["type"] in (
            "checkout.session.completed",
            "payment_intent.succeeded",
            "checkout.session.expired",
            "payment_intent.payment_failed",
            "charge.succeeded",
            "charge.failed",
        ):
            logger.info(
                f"Received webhook for order payment event: {event['type']} with metadata: {metadata}"
            )
            if event["type"].startswith("checkout.session."):
                actual_transaction_id = getattr(session, "payment_intent", None)
            else:
                actual_transaction_id = getattr(session, "id", None)
            event_type = literal(event["type"])
            payment_status_case = case(
                (
                    event_type.in_(VALID_SUCCESS_EVENTS),
                    cast(PaymentStatus.SUCCESS.value, target_enum),
                ),
                (
                    event_type.in_(VALID_FAILURE_EVENTS),
                    cast(PaymentStatus.FAILED.value, target_enum),
                ),
                else_=Payment.payment_status,
            )
            if event["type"] in VALID_SUCCESS_EVENTS:
                order_status = OrderStatus.processing
            elif event["type"] in VALID_FAILURE_EVENTS:
                order_status = OrderStatus.pending
            else:
                order_status = None
            transaction_id_case = case(
                (event_type.in_(VALID_SUCCESS_EVENTS), actual_transaction_id),
                (
                    event_type.in_(VALID_FAILURE_EVENTS),
                    actual_transaction_id,
                ),
                else_=Payment.transaction_id,
            )
            order_id = (
                int(metadata["order_id"])
                if metadata and "order_id" in metadata
                else None
            )
            if order_id:
                idemp = await db.execute(
                    update(Payment)
                    .where(
                        or_(
                            Payment.reference_id == stripe_session_id,
                            Payment.order_id == order_id,
                        ),
                        or_(
                            Payment.last_event_at.is_(None),
                            Payment.last_event_at <= created_timestamp,
                        ),
                        or_(
                            Payment.last_event_id.is_(None),
                            Payment.last_event_id != event["id"],
                        ),
                    )
                    .values(
                        last_event_id=event["id"],
                        last_event_at=created_timestamp,
                        transaction_id=transaction_id_case,
                        payment_status=payment_status_case,
                    )
                    .returning(Payment.order_id)
                )
                row = idemp.scalar()
                if not row:
                    logger.info(
                        f"Payment {stripe_session_id} already processed. Skipping."
                    )
                    return {"status": "success", "message": "already processed"}
                await db.execute(
                    update(Order)
                    .where(Order.id == row)
                    .values(status=order_status)
                    .returning(Order.id)
                )
        if type_metadata == "order_refund" and event["type"] in [
            "charge.refunded",
            "refund.updated",
        ]:
            logger.info(
                f"Received webhook for order payment event: {event['type']} with metadata: {metadata}"
            )
            if event["type"] == "charge.refunded":
                refunds_obj = getattr(session, "refunds", {})
                if refunds_obj:
                    refunds_list = (
                        getattr(refunds_obj, "data", [])
                        if hasattr(refunds_obj, "data")
                        else refunds_obj.get("data", [])
                    )
                    if refunds_list:
                        stripe_session_id = (
                            getattr(refunds_list[-1], "id", None)
                            if hasattr(refunds_list[-1], "id")
                            else refunds_list[-1].get("id")
                        )
            target_status = PaymentStatus.REFUNDED.value
            if (
                getattr(session, "object", None) == "refund"
                and getattr(session, "status", None) == "failed"
            ):
                target_status = PaymentStatus.SUCCESS.value
                logger.error(
                    f"Bank rejected refund {stripe_session_id}. Reverting parent payment status."
                )
            idempo = await db.execute(
                update(Refund)
                .where(
                    Refund.refund_id == stripe_session_id,
                    or_(
                        Refund.last_event_at.is_(None),
                        Refund.last_event_at <= created_timestamp,
                    ),
                    or_(
                        Refund.last_event_id.is_(None),
                        Refund.last_event_id != event["id"],
                    ),
                )
                .values(last_event_id=event["id"], last_event_at=created_timestamp)
                .returning(Refund.payment_id)
            )
            refunded = idempo.scalar_one_or_none()
            if not refunded:
                logger.info(f"Payment {stripe_session_id} already processed. Skipping.")
                return {"status": "success", "message": "already processed"}
            payment_id = int(refunded)
            await db.execute(
                update(Payment)
                .where(Payment.id == payment_id)
                .values(payment_status=cast(target_status, target_enum))
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
        logger.info(f"Payment {stripe_session_id} processed successfully.")
        if membership_id:
            background_task.add_task(membership_activation, membership_id, user_id)
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
    row = (
        await db.execute(
            select(
                Store,
                or_(
                    exists().where(
                        store_owners.c.users_id == user_id,
                        store_owners.c.stores_id == store_id,
                    ),
                    exists().where(
                        store_staffs.c.users_id == user_id,
                        store_staffs.c.stores_id == store_id,
                    ),
                ),
            ).where(Store.id == store_id)
        )
    ).fetchone()
    store, auth = row if row else (None, False)
    if not auth and role not in allowed_roles:
        logger.warning(
            "user: %s, tried accessing get_payment endpoint without appropriate credentials",
            user_id,
        )
        raise HTTPException(status_code=403, detail="restricted access")
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
        return StandardResponse(
            status="error", message="invalid time frame selected", data=None
        )
    if store.founded > time_period:
        return StandardResponse(
            status="error",
            message=f"store's existence is below {time_frame}",
            data=None,
        )
    status_map = {
        "approved": PaymentStatus.SUCCESS.value,
        "pending": PaymentStatus.PENDING.value,
        "refunds": PaymentStatus.REFUNDED.value,
        "failed": PaymentStatus.FAILED.value,
    }
    status_value = status_map.get(payment_status, None)
    if not status_value:
        return StandardResponse(
            status="error", message="invalid payment status selected", data=None
        )
    payment_list = payment_list_stmt.where(
        Payment.payment_status == status_value, Payment.payment_date >= time_period
    ).order_by(Payment.payment_date.desc())
    result = (
        (await db.execute(payment_list.offset(offset).limit(limit))).scalars().all()
    )
    if not result:
        logger.info(f"store: {store_id}, has no {payment_status} payments")
        return StandardResponse(
            status="success",
            message=f"this store has no {payment_status} payments",
            data=None,
        )
    total = (
        await db.execute(
            select(func.count(Payment.id))
            .join(Order, Payment.order_id == Order.id)
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
