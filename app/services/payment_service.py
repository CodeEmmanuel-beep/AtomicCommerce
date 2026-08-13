from fastapi import HTTPException
from app.logs.logger import get_logger
from sqlalchemy import select, func, exists
from sqlalchemy.exc import IntegrityError
from app.models import (
    Subscription,
    Payment,
    SubscriptionStatus,
    Order,
    Membership,
    PaymentStatus,
    Refund,
    Store,
    OrderStatus,
)
from decimal import Decimal
from app.api.v1.schemas import (
    PaymentResponse,
    SubscriptionResponse,
    PaginatedMetadata,
    StandardResponse,
    PaginatedResponse,
    CursorPaginatedResponse,
)
from dateutil.relativedelta import relativedelta
from app.database.config import settings
from app.database.get import AsyncSessionLocal
from datetime import datetime, timezone
from app.utils.redis import cache, cached
from sqlalchemy.orm import selectinload, contains_eager
from app.utils.helper import unique_id, user_role, store_auth
import stripe

logger = get_logger("payment")

stripe_client = stripe.StripeClient(settings.STRIPE_SECRET_KEY)


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
    request,
    one_time_subscription,
):
    user_id = unique_id(request)
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
            if order.delivery_address_id is None:
                logger.warning(
                    f"user_id: {user_id} attempted to create payment for an order_id: {order_id} without a delivery address"
                )
                raise HTTPException(
                    status_code=400,
                    detail="order must have delivery address before payment can proceed",
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
                        "success_url": "https://atomiccommerce.local/docs/?session_id={CHECKOUT_SESSION_ID}",
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
                    locked_payment = (
                        await session.execute(
                            select(Payment)
                            .where(Payment.id == payment_exist.id)
                            .with_for_update()
                        )
                    ).scalar_one_or_none()
                    updated_fields = {
                        "payment_status": PaymentStatus.PENDING.value,
                        "subtotal": order.subtotal,
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
                        setattr(locked_payment, attr, field)
                    log_action = "updated"
                    target_payment = locked_payment
                else:
                    payment = Payment(
                        user_id=user_id,
                        order_id=order.id,
                        subtotal=order.subtotal,
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
                        "success_url": "https://atomiccommerce.local/docs/member?session_id={CHECKOUT_SESSION_ID}",
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
                    f"user_id: {user_id} attempted to create payment for subscription_plan without a membership or subscription plan"
                )
                raise HTTPException(
                    status_code=404,
                    detail="register as a member or update membership before subscribing to a plan.",
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
                        "success_url": "https://atomiccommerce.local/docs/member?session_id={CHECKOUT_SESSION_ID}",
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


async def update_payment(sub_id, db, request):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized attempt at update_payment endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    sub = (
        await db.execute(
            select(Subscription)
            .join(Membership, Subscription.membership_id == Membership.id)
            .where(Membership.user_id == user_id, Subscription.id == sub_id)
        )
    ).scalar_one_or_none()
    if not sub:
        logger.warning(
            "user: %s, tried assessing update_payment endpoint without being a subscriber",
            user_id,
        )
        raise HTTPException(status_code=404, detail="subscription not found")
    portal_session = await stripe_client.v1.billing_portal.sessions.create_async(
        params={
            "customer": str(sub.customer_id),
            "return_url": "https://atomiccommerce.local/docs",
        }
    )
    data = {"billing_portal_url": portal_session.url}
    return StandardResponse(
        status="success",
        message="follow the link below to update your subscription",
        data=data,
    )


async def charge_refund(payment_id, amount, reason, db, request):
    user_id = unique_id(request)
    role = user_role(request)
    allowed_roles = ("Admin", "Owner")
    if not user_id or role not in allowed_roles:
        logger.error(
            "possible security and financial breach at charge_refund endpoint by user %s",
            user_id,
        )
        raise HTTPException(status_code=401, detail="Luke 13:3")
    stmt = (
        select(Payment)
        .options(selectinload(Payment.order))
        .where(Payment.id == payment_id)
        .with_for_update()
    )
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
            "user: %s, tried reufunding a payment that was not successful", user_id
        )
        raise HTTPException(status_code=400, detail="payment was not successful")
    if amount > payment.total_amount:
        logger.warning(
            "user: %s, tried overrefunding",
            user_id,
        )
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
    total_refund = amount + refunded_so_far
    if amount > remaining:
        logger.warning(
            "user: %s, tried overrefunding subsequent payments %s, %s",
            user_id,
            amount,
            remaining,
        )
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
        await db.rollback()
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
        if total_refund >= payment.total_amount:
            payment.order.status = OrderStatus.pending
        logger.info(
            "order status %s total refund %s total amount %s",
            payment.order.status,
            total_refund,
            payment.total_amount,
        )
        await db.commit()
    except Exception as db_err:
        logger.critical(
            f"FATAL STATE MISMATCH: Stripe refund {refund.id} succeeded for amount {amount}, "
            f"but database tracking write failed! Manual reconcile required for order_id {payment.order_id}. Error: {str(db_err)}"
        )
        raise HTTPException(status_code=500, detail="internal server error")
    data = {"refund_id": refund.id}
    return StandardResponse(status="success", message="refund logged", data=data)


async def get_payment(
    store_id, payment_status, time_frame, cursor_id, limit, db, request
):
    user_id = unique_id(request)
    role = user_role(request)
    allowed_roles = ("Admin", "Owner")
    if not user_id:
        logger.warning("unauthorized attempt at get_payment endpoint")
        raise HTTPException(status_code=401, detail="unauthorized attempt")
    if role not in allowed_roles:
        await store_auth(store_id=store_id, db=db, request=request)
    status_map = {
        "success": PaymentStatus.SUCCESS.value,
        "pending": PaymentStatus.PENDING.value,
        "refunds": PaymentStatus.REFUNDED.value,
        "failed": PaymentStatus.FAILED.value,
    }
    status_value = status_map.get(payment_status, None)
    if not status_value:
        raise HTTPException(status_code=400, detail="invalid payment status selected")
    cache_key = (
        f"payment_list:{store_id}:{payment_status}:{time_frame}:{cursor_id}:{limit}"
    )
    payment_cache = await cache(cache_key)
    if payment_cache:
        logger.info(
            "cache hit at get_payment endpoint for payment_status: %s", payment_status
        )
        return StandardResponse(**payment_cache)
    store_time = (
        await db.execute(select(Store.founded).where(Store.id == store_id))
    ).scalar_one_or_none()
    if not store_time:
        logger.warning(
            "user: %s, search for payment history for a store that does not exist store: %s",
            user_id,
            store_id,
        )
        raise HTTPException(status_code=404, detail="store not found")
    now = datetime.now(timezone.utc)
    time_map = {
        "total": store_time,
        "1 year": now - relativedelta(years=1),
        "6 months": now - relativedelta(months=6),
        "3 months": now - relativedelta(months=3),
        "1 month": now - relativedelta(months=1),
        "1 week": now - relativedelta(days=7),
    }
    time_period = time_map.get(time_frame)
    if not time_period:
        raise HTTPException(status_code=400, detail="invalid time frame selected")
    if store_time > time_period:
        raise HTTPException(
            status_code=400, detail=f"store's existence is below {time_frame}"
        )
    is_refunded = status_value == PaymentStatus.REFUNDED.value
    payment_list_stmt = (
        select(Payment)
        .join(Order, Payment.order_id == Order.id)
        .options(contains_eager(Payment.order))
        .where(Order.store_id == store_id)
    )
    if cursor_id is not None:
        payment_list_stmt = payment_list_stmt.where(Payment.id > cursor_id)
    if is_refunded:
        payment_list_stmt = payment_list_stmt.options(selectinload(Payment.refunds))
    payment_list = (
        payment_list_stmt.where(
            Payment.payment_status == status_value, Payment.payment_date >= time_period
        )
        .order_by(Payment.id.asc())
        .limit(limit + 1)
    )
    result = (await db.execute(payment_list)).scalars().all()
    if not result:
        logger.info(
            f"store: {store_id}, has no {payment_status} payments in the past {time_frame}"
        )
    has_more = len(result) > limit
    if has_more:
        result = result[:limit]
    next_cursor = result[-1].id if result else None
    items = []
    for pay in result:
        paid = PaymentResponse.model_validate(pay)
        if is_refunded:
            paid.total_refund = sum(
                (Decimal(str(r.refund_amount)) for r in pay.refunds), Decimal("0.00")
            )
        items.append(paid)
    data = PaginatedMetadata[PaymentResponse](
        items=items,
        cursor_pagination=CursorPaginatedResponse(
            next_cursor=next_cursor, limit=limit, has_more=has_more
        ),
    )
    full_response = StandardResponse(
        status="success", message=f"{payment_status} payments", data=data
    )
    await cached(cache_key, full_response, ttl=300)
    logger.info(
        "user %s queried %s payments within %s for store %s, data returned successfully",
        user_id,
        payment_status,
        time_frame,
        store_id,
    )
    return full_response


async def get_personal_receipt_list(store_id, payment_status, page, limit, db, request):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized attempt at get_payment endpoint")
        raise HTTPException(status_code=401, detail="unauthorized attempt")
    cache_key = f"payment_list:{user_id}:{store_id}:{payment_status}:{page}:{limit}"
    payment_cache = await cache(cache_key)
    if payment_cache:
        logger.info(
            f"cache hit at get_personal_payment_list endpoint for payment_status: {payment_status}, page:{page}"
        )
        return StandardResponse(**payment_cache)
    status_map = {
        "success": PaymentStatus.SUCCESS.value,
        "pending": PaymentStatus.PENDING.value,
        "refunded": PaymentStatus.REFUNDED.value,
        "failed": PaymentStatus.FAILED.value,
    }
    status_value = status_map.get(payment_status, None)
    if not status_value:
        raise HTTPException(status_code=400, detail="invalid payment status selected")
    offset = (page - 1) * limit
    total = (
        await db.execute(
            select(func.count(Payment.id))
            .join(Order, Payment.order_id == Order.id)
            .where(
                Order.store_id == store_id,
                Payment.payment_status == status_value,
                Payment.user_id == user_id,
            )
        )
    ).scalar() or 0
    if total == 0:
        store_exists = (
            await db.execute(select(exists().where(Store.id == store_id)))
        ).scalar()
        if not store_exists:
            logger.warning(
                "user: %s searched non-existent store: %s", user_id, store_id
            )
            raise HTTPException(status_code=404, detail="store not found")

        logger.info(
            "user: %s has no %s payments for store: %s",
            user_id,
            payment_status,
            store_id,
        )
        empty_data = PaginatedMetadata[PaymentResponse](
            items=[],
            pagination=PaginatedResponse(page=page, limit=limit, total=0),
        )
        full_response = StandardResponse(
            status="success", message=f"{payment_status} payments", data=empty_data
        )
        await cached(cache_key, full_response, ttl=300)
        return full_response
    logger.info("total '%s', payments is: %s", payment_status, total)
    is_refunded = status_value == PaymentStatus.REFUNDED.value
    payment_list_stmt = (
        select(Payment)
        .join(Order, Payment.order_id == Order.id)
        .options(contains_eager(Payment.order))
        .where(Order.store_id == store_id, Payment.user_id == user_id)
    )
    if is_refunded:
        payment_list_stmt = payment_list_stmt.options(selectinload(Payment.refunds))
    payment_list = payment_list_stmt.where(
        Payment.payment_status == status_value
    ).order_by(Payment.payment_date.desc())
    result = (
        (await db.execute(payment_list.offset(offset).limit(limit))).scalars().all()
    )
    items = []
    for pay in result:
        paid = PaymentResponse.model_validate(pay)
        if is_refunded:
            paid.total_refund = sum(
                (Decimal(str(r.refund_amount)) for r in pay.refunds), Decimal("0.00")
            )
        items.append(paid)
    data = PaginatedMetadata[PaymentResponse](
        items=items,
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    full_response = StandardResponse(
        status="success", message=f"{payment_status} payments", data=data
    )
    await cached(cache_key, full_response, ttl=300)
    logger.info(
        "user %s queried %s payments for store %s, data returned successfully",
        user_id,
        payment_status,
        store_id,
    )
    return full_response


async def get_personal_receipt(store_id, order_id, db, request):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized attempt at get_payment endpoint")
        raise HTTPException(status_code=401, detail="unauthorized attempt")
    cache_key = f"payment:{user_id}:{store_id}:{order_id}"
    payment_cache = await cache(cache_key)
    if payment_cache:
        logger.info("cache hit at get_personal_payment endpoint")
        return StandardResponse(**payment_cache)
    payment_stmt = (
        select(Payment)
        .join(Order, Payment.order_id == Order.id)
        .options(selectinload(Payment.refunds))
        .options(selectinload(Payment.order).selectinload(Order.store))
        .where(
            Order.store_id == store_id, Order.id == order_id, Payment.user_id == user_id
        )
    )
    result = (await db.execute(payment_stmt)).scalar_one_or_none()
    if not result:
        logger.info(f"user: {user_id}, has no payment receipt for order: {order_id}")
        store = (
            await db.execute(
                select(
                    exists().where(Store.id == store_id),
                )
            )
        ).scalar()
        if not store:
            logger.warning(
                "user: %s, search for payment history for a store that does not exist store: %s",
                user_id,
                store_id,
            )
            raise HTTPException(status_code=404, detail="store not found")
        return StandardResponse(
            status="success",
            message=f"you have no payment receipt for order {order_id}",
            data=None,
        )
    paid = PaymentResponse.model_validate(result)
    if result.payment_status == PaymentStatus.REFUNDED.value:
        paid.total_refund = sum(
            (Decimal(str(r.refund_amount)) for r in result.refunds), Decimal("0.00")
        )
    full_response = StandardResponse(
        status="success", message=f"payment for order: '{order_id}", data=paid
    )
    await cached(cache_key, full_response, ttl=300)
    logger.info(
        "user %s queried payment for order %s in store %s, data returned successfully",
        user_id,
        order_id,
        store_id,
    )
    return full_response
