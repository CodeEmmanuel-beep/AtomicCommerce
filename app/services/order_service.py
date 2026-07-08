from app.api.v1.schemas import (
    OrderResponse,
    PaginatedMetadata,
    PaginatedResponse,
    StandardResponse,
    OrderItemRes,
)
from app.models import (
    Cart,
    Order,
    OrderItem,
    CartItem,
    Product,
    Inventory,
    OrderStatus,
    Membership,
)
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from app.logs.logger import get_logger
from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.exc import IntegrityError
from app.utils.redis import (
    cache,
    cached,
    order_invalidation,
    cart_invalidation,
    cache_version,
)
from app.utils.helper import restore_inventory
from decimal import Decimal
import asyncio

logger = get_logger("order")


async def order_expiration(store_id, order_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Unauthorized attempt at the order_expiration endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    stmt = select(Order).where(
        ~Order.order_delete,
        Order.id == order_id,
        Order.store_id == store_id,
        Order.user_id == user_id,
    )
    order = (await db.execute(stmt)).scalar_one_or_none()
    if not order:
        logger.warning("order: '%s' not found", order_id)
        raise HTTPException(status_code=404, detail="order not found")
    now = datetime.now(timezone.utc)
    if order.re_order_time:
        delta = order.re_order_time + timedelta(minutes=30)
    else:
        delta = order.created_at + timedelta(hours=1)
    count_down = (delta - now).total_seconds()
    if order.status == OrderStatus.cancelled:
        data = {"total seconds remaining": 0, "order expires in": "0 seconds"}
        return StandardResponse(status="success", message="order expired", data=data)
    if count_down <= 0:
        data = {"total seconds remaining": 0, "order expires in": "0 seconds"}
        return StandardResponse(status="success", message="order expired", data=data)
    minutes = int(count_down // 60)
    seconds = int(count_down % 60)
    data = None
    if minutes > 1:
        data = {
            "total seconds remaining": int(count_down),
            "order expires in": f"{minutes} minutes and {seconds} seconds",
        }
    elif minutes == 1:
        data = {
            "total seconds remaining": int(count_down),
            "order expires in": f"{minutes} minute and {seconds} seconds",
        }
    elif minutes < 1:
        data = {
            "total seconds remaining": int(count_down),
            "order expires in": f"{seconds} seconds",
        }
    return StandardResponse(status="success", message="order active", data=data)


DISCOUNT_MAP = {
    "Standard": Decimal("0.02"),
    "Regular": Decimal("0.01"),
    "Premium": Decimal("0.03"),
}

TWO_PLACES = Decimal("0.01")


async def invalidate_cache(user_id):
    return await asyncio.gather(order_invalidation(user_id), cart_invalidation(user_id))


async def create_orders(store_id, cart_id, db, payload, background_task):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Unauthorized attempt to create order")
        raise HTTPException(
            status_code=401, detail="you must be a registered user to make orders"
        )
    try:
        stmt = (
            select(Cart)
            .options(
                joinedload(Cart.store),
                selectinload(Cart.cartitems)
                .selectinload(CartItem.product)
                .selectinload(Product.inventory),
            )
            .where(
                Cart.id == cart_id,
                ~Cart.check_out,
                Cart.user_id == user_id,
                Cart.store_id == store_id,
            )
            .with_for_update(of=Cart)
        )
        result = await db.execute(stmt)
        cart = result.scalar_one_or_none()
        logger.info(f"Fetched cart items for cart_id: {cart_id}")
        if not cart:
            logger.warning(
                "user: %s, tried making an order with a non existent cart", user_id
            )
            raise HTTPException(status_code=404, detail="cart not found")
        if not cart.cartitems:
            raise HTTPException(status_code=404, detail="no cart items found")
        logger.info("Creating order for user_id: %s", user_id)
        membership = (
            await db.execute(
                select(Membership).where(
                    Membership.user_id == user_id,
                    Membership.store_id == store_id,
                    Membership.is_active,
                )
            )
        ).scalar_one_or_none()
        membership_id = membership.id if membership else None
        order = Order(
            user_id=user_id,
            store_id=store_id,
            member_id=membership_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(order)
        await db.flush()
        if not order.id:
            logger.warning("No order created")
            raise HTTPException(status_code=404, detail="no order created")
        product_ids = sorted([items.product_id for items in cart.cartitems])
        inventory = (
            (
                await db.execute(
                    select(Inventory)
                    .where(Inventory.product_id.in_(product_ids), ~Inventory.is_deleted)
                    .with_for_update(),
                )
            )
            .scalars()
            .all()
        )
        cart_product_ids = {i.product_id for i in cart.cartitems}
        inventory_product_ids = {inv.product_id for inv in inventory}
        if cart_product_ids != inventory_product_ids:
            logger.warning(
                "inventory mismatch at create_order_items endpoint",
            )
            raise HTTPException(404, "inventory mismatch")
        inventory_map = {inv.product_id: inv for inv in inventory}
        items = [
            i
            for i in cart.cartitems
            if i.product.is_deleted
            or i.product.product_availability != "available"
            or i.quantity > inventory_map[i.product_id].stock_quantity
        ]
        if items:
            raise HTTPException(
                status_code=400,
                detail="there is an update on your cart, please update cart before check out",
            )
        new_orderitems = []
        total_quantity = 0
        subtotal = Decimal("0.00")
        for cartitem in cart.cartitems:
            product = cartitem.product
            price = (
                cartitem.product.product_price * Decimal(str(cartitem.quantity))
            ).quantize(TWO_PLACES)
            new_orderitems.append(
                OrderItem(
                    order_id=order.id,
                    product_id=cartitem.product_id,
                    quantity=cartitem.quantity,
                    price=price,
                )
            )
            target_inventory = inventory_map[cartitem.product_id]
            target_inventory.stock_quantity = max(
                target_inventory.stock_quantity - cartitem.quantity, 0
            )
            total_quantity += cartitem.quantity
            subtotal += price
            if target_inventory.stock_quantity == 0:
                product.product_availability = "out_of_stock"
        order.total_quantity = total_quantity
        order.subtotal = subtotal.quantize(TWO_PLACES)
        order.discount_amount = Decimal("0.00")
        has_premium = membership and membership.membership_type == "Premium"
        if membership:
            order.discount_amount = (
                subtotal * Decimal(str(DISCOUNT_MAP[membership.membership_type]))
            ).quantize(TWO_PLACES)
        order.shipping_fee = Decimal("0.00") if has_premium else cart.store.shipping_fee
        tax_amount = (
            (subtotal * Decimal(str(cart.store.tax_rate))) / Decimal("100")
        ).quantize(TWO_PLACES)
        order.tax_rate = cart.store.tax_rate
        order.tax_amount = tax_amount
        order.total_amount = (
            (subtotal + order.shipping_fee + tax_amount) - order.discount_amount
        ).quantize(TWO_PLACES)
        db.add_all(new_orderitems)
        update_result = (
            await db.execute(
                update(Cart)
                .where(
                    Cart.id == cart_id,
                    ~Cart.check_out,
                    Cart.user_id == user_id,
                )
                .values(check_out=True)
                .returning(Cart.id)
            )
        ).scalar()
        if update_result is None:
            raise HTTPException(status_code=409, detail="cart already checked out")
        order_id = order.id
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database integrity error while creating order items {e}")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while creating order items")
        raise HTTPException(status_code=500, detail="internal server error")
    background_task.add_task(invalidate_cache, user_id)
    logger.info("order items created successfully for order_id: %s", order_id)
    return StandardResponse(
        status="success",
        message="order item successfully created",
        data=f"you have one hour to check out the order, order_id: '{order_id}'",
    )


async def view_orders(store_id, page, limit, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.error("Unauthorized attempt to view orders")
        raise HTTPException(status_code=401, detail="not a registered buyer")
    offset = (page - 1) * limit
    if page < 1 or limit < 1:
        raise HTTPException(
            status_code=400, detail="page number and limit must be greater than 0"
        )
    version = await cache_version("order_key")
    order_key = f"orders:v{version}:{user_id}:{store_id}:{page}:{limit}"
    cache_key = await cache(order_key)
    if cache_key:
        return StandardResponse(**cache_key)
    stmt = (
        select(Order)
        .options(
            selectinload(Order.orderitems)
            .selectinload(OrderItem.product)
            .selectinload(Product.inventory),
            selectinload(Order.membership),
            selectinload(Order.user),
        )
        .where(
            Order.user_id == user_id, Order.store_id == store_id, ~Order.order_delete
        )
    )
    total = (
        await db.execute(
            select(func.count(Order.id)).where(
                Order.user_id == user_id,
                Order.store_id == store_id,
                ~Order.order_delete,
            )
        )
    ).scalar() or 0
    logger.info("total orders found: '%s' for user: %s", total, user_id)
    order = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    if not order:
        logger.warning("search for orders returned no result")
        return StandardResponse(status="success", message="no orders found", data=None)
    logger.info("preparing paginated response for orders of user: %s", user_id)
    data = PaginatedMetadata[OrderResponse](
        items=[OrderResponse.model_validate(od) for od in order],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    logger.info(f"Orders retrieved successfully for user_id: {user_id}")
    full_response = StandardResponse(status="success", message="orders", data=data)
    await cached(order_key, full_response, ttl=3600)
    return full_response


async def view_order(store_id, order_id, page, limit, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.error("Unauthorized attempt to view order")
        raise HTTPException(status_code=401, detail="not a registered buyer")
    offset = (page - 1) * limit
    version = await cache_version("order_key")
    order_key = f"orders:v{version}:{user_id}:{store_id}:{order_id}:{page}:{limit}"
    cache_key = await cache(order_key)
    if cache_key:
        return StandardResponse(**cache_key)
    stmt = (
        select(Order)
        .options(
            selectinload(Order.orderitems)
            .selectinload(OrderItem.product)
            .selectinload(Product.inventory),
            selectinload(Order.payment),
            selectinload(Order.user),
            selectinload(Order.membership),
        )
        .where(
            Order.user_id == user_id,
            Order.store_id == store_id,
            Order.id == order_id,
            ~Order.order_delete,
        )
    )
    order = (await db.execute(stmt.offset(offset).limit(limit))).scalar_one_or_none()
    logger.info(f"Fetched order details for order_id: {order_id}")
    if not order:
        logger.error("Order with order_id: '%s' not found", order_id)
        raise HTTPException(
            status_code=404, detail=f"order with the order id: {order_id} not found"
        )
    order_data = OrderResponse.model_validate(order)
    total = len(order.orderitems)
    items = order.orderitems[offset : offset + limit]
    logger.info(f"Total order items found: {total} for order_id: {order_id}")
    logger.info(f"Preparing paginated response for order items of order_id: {order_id}")
    data = PaginatedMetadata[OrderItemRes](
        items=[OrderItemRes.model_validate(item) for item in items],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    response = {"order": order_data, "ordered_items": data}
    full_response = StandardResponse(
        status="success", message="order retrieved successfully", data=response
    )
    await cached(order_key, full_response, ttl=3600)
    logger.info(f"Order details retrieved successfully for order_id: {order_id}")
    return full_response


async def reactivate_order(store_id, order_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at checkout endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    try:
        stmt = (
            select(Order)
            .options(
                joinedload(Order.store),
                selectinload(Order.orderitems)
                .selectinload(OrderItem.product)
                .selectinload(Product.inventory),
            )
            .where(
                Order.user_id == user_id,
                Order.store_id == store_id,
                Order.id == order_id,
                ~Order.order_delete,
                Order.status == OrderStatus.cancelled,
            )
            .with_for_update(of=Order)
        )
        res = await db.execute(stmt)
        order = res.scalar_one_or_none()
        if not order:
            logger.warning(
                "user: '%s', tried to re-order a non existent order", user_id
            )
            raise HTTPException(status_code=404, detail="order not found")
        if not order.orderitems:
            logger.warning("order: '%s' was created without orderitems", order_id)
            raise HTTPException(status_code=400, detail="order contains no items")
        product_ids = sorted([item.product_id for item in order.orderitems])
        inventory = (
            (
                await db.execute(
                    select(Inventory)
                    .where(Inventory.product_id.in_(product_ids), ~Inventory.is_deleted)
                    .with_for_update(),
                )
            )
            .scalars()
            .all()
        )
        order_product_ids = {item.product_id for item in order.orderitems}
        inventory_product_ids = {inv.product_id for inv in inventory}
        if order_product_ids != inventory_product_ids:
            logger.warning(
                "user: '%s', reactivation failed. Some products are no longer available in catalog",
                user_id,
            )
            raise HTTPException(
                status_code=404,
                detail="Cannot reactivate order. Some items in this order are no longer available.",
            )
        membership_stmt = select(Membership).where(
            Membership.store_id == store_id,
            Membership.user_id == user_id,
            Membership.is_active,
        )
        membership_result = await db.execute(membership_stmt)
        membership = membership_result.scalar_one_or_none()
        has_premium = membership and membership.membership_type == "Premium"
        inventory_map = {inv.product_id: inv for inv in inventory}
        failed_item = None
        for item in order.orderitems:
            if (
                inventory_map[item.product_id].stock_quantity < item.quantity
                or item.product.is_deleted
                or item.product.product_availability != "available"
            ):
                failed_item = item
                break
        if failed_item:
            product = failed_item.product
            available_inventory = inventory_map[failed_item.product_id].stock_quantity
            reason = None
            if available_inventory < failed_item.quantity:
                reason = "insufficient stock"
            elif product.is_deleted:
                reason = "product deleted"
            elif product.product_availability != "available":
                reason = "product unavailable"
            logger.warning("user '%s' reactivation failed, reason: %s", user_id, reason)
            raise HTTPException(status_code=400, detail=reason)
        new_subtotal = Decimal("0.00")
        order.status = OrderStatus.pending
        tax_rate = order.store.tax_rate
        shipping_fee = Decimal("0.00") if has_premium else order.store.shipping_fee
        order.re_order_time = datetime.now(timezone.utc)
        for orderitems in order.orderitems:
            product = orderitems.product
            current_item_price = product.product_price * Decimal(
                str(orderitems.quantity)
            )
            orderitems.price = current_item_price
            new_subtotal += current_item_price
            target_inventory = inventory_map[orderitems.product_id]
            target_inventory.stock_quantity -= orderitems.quantity
            if target_inventory.stock_quantity == 0:
                product.product_availability = "out_of_stock"
        tax_amount = (new_subtotal * Decimal(str(tax_rate)) / Decimal("100")).quantize(
            TWO_PLACES
        )
        order.discount_amount = Decimal("0.00")
        if membership:
            order.discount_amount = (
                new_subtotal * Decimal(str(DISCOUNT_MAP[membership.membership_type]))
            ).quantize(TWO_PLACES)
        order.tax_rate = tax_rate
        order.tax_amount = tax_amount
        order.shipping_fee = shipping_fee
        order.subtotal = new_subtotal.quantize(TWO_PLACES)
        order.total_amount = (
            (new_subtotal + tax_amount + shipping_fee) - order.discount_amount
        ).quantize(TWO_PLACES)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database integrity error at re-order endpoint")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error at re-order endpoint")
        raise HTTPException(status_code=500, detail="internal server error")
    await order_invalidation(user_id=user_id)
    logger.info("Order: '%s' successfully re-ordered", order_id)
    return StandardResponse(
        status="success",
        message="re-order successful",
        data="you have 30 minutes to check out this order, if this order is not checked out after 30 minutes, it will be automatically deleted",
    )


async def proceed_to_payment_portal(store_id, order_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning(
            "user: %s, attempted to access non-existent order_id=%s", user_id, order_id
        )
        raise HTTPException(status_code=401, detail="unauthorized access")
    checkout = (
        await db.execute(
            select(Order)
            .options(
                selectinload(Order.orderitems)
                .selectinload(OrderItem.product)
                .selectinload(Product.inventory)
            )
            .where(
                Order.user_id == user_id,
                ~Order.order_delete,
                Order.id == order_id,
                Order.store_id == store_id,
                Order.status == OrderStatus.pending,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not checkout:
        logger.warning(
            "user: %s attempted payment for non-existent or invalid order %s",
            user_id,
            order_id,
        )
        raise HTTPException(
            status_code=404,
            detail="order not found, if you think this is a mistake try again shortly",
        )
    now = datetime.now(timezone.utc)
    retry_limit = now - timedelta(minutes=30)
    time_limit = now - timedelta(hours=1)
    is_expired = False
    if checkout.re_order_time and checkout.re_order_time <= retry_limit:
        checkout.order_delete = True
        is_expired = True
    elif not checkout.re_order_time and checkout.created_at <= time_limit:
        is_expired = True
    if is_expired:
        try:
            checkout.status = OrderStatus.cancelled
            if checkout.orderitems:
                restore_inventory(checkout)
            await db.commit()
        except IntegrityError:
            await db.rollback()
            logger.error("Database integrity error while  updating checked out order")
            raise HTTPException(status_code=400, detail="database integrity error")
        except Exception:
            await db.rollback()
            logger.exception("error while updating checked out order")
            raise HTTPException(status_code=500, detail="internal server error")
        raise HTTPException(
            status_code=409, detail="Order session expired. Please re-initiate order"
        )
    if not checkout.delivery_address:
        await db.commit()
        logger.warning(
            "user: %s attempted payment for order %s without delivery address",
            user_id,
            order_id,
        )
        raise HTTPException(
            status_code=400,
            detail="Delivery address required before proceeding to payment",
        )
    added_twenty = timedelta(minutes=20)
    if checkout.re_order_time:
        checkout.re_order_time += added_twenty
    elif not checkout.re_order_time:
        checkout.created_at += added_twenty
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception(
            "Failed to persist checkout window update for order: %s", order_id
        )
        raise HTTPException(status_code=500, detail="Database transaction failure")
    logger.info(
        "Order %s validated successfully. Proceeding to payment portal.", order_id
    )


async def cancel_order(
    store_id,
    order_id,
    db,
    payload,
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.error("Unauthorized attempt to cancel order")
        raise HTTPException(status_code=401, detail="not authorized")
    stmt = (
        select(Order)
        .options(
            selectinload(Order.payment),
            selectinload(Order.orderitems)
            .selectinload(OrderItem.product)
            .selectinload(Product.inventory),
        )
        .where(
            Order.user_id == user_id,
            Order.store_id == store_id,
            Order.id == order_id,
            ~Order.order_delete,
            Order.status.in_([OrderStatus.pending, OrderStatus.cancelled]),
        )
        .with_for_update(of=Order)
    )
    logger.info("fetching order to cancel for order_id: %s", order_id)
    result = (await db.execute(stmt)).scalar_one_or_none()
    if not result:
        logger.error("Order with order_id: '%s' not found for cancellation", order_id)
        raise HTTPException(status_code=404, detail="order not found")
    payment_status = result.payment.payment_status if result.payment else "pending"
    if payment_status == "pending":
        if result.status == OrderStatus.cancelled:
            return StandardResponse(
                status="success", message="order already cancelled", data=None
            )
        result.status = OrderStatus.cancelled
        if result.orderitems:
            restore_inventory(result)
        logger.info("Order with order_id: '%s' cancelled successfully", order_id)
    else:
        logger.error(
            "Order with order_id: '%s' cannot be cancelled, payment triggered", order_id
        )
        raise HTTPException(
            status_code=400, detail="payment is triggered, cannot cancel order"
        )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error("Database integrity error while cancelling order")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while cancelling order")
        raise HTTPException(status_code=500, detail="internal server error")
    await order_invalidation(user_id=user_id)
    logger.info("Order cancellation process completed for order_id: %s", order_id)
    return StandardResponse(status="success", message="order cancelled", data=None)


async def delete_order(
    store_id,
    order_id,
    db,
    payload,
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.error("Unauthorized attempt to delete order")
        raise HTTPException(status_code=401, detail="not authorized")
    stmt = (
        select(Order)
        .where(
            Order.user_id == user_id,
            ~Order.order_delete,
            Order.store_id == store_id,
            Order.id == order_id,
        )
        .with_for_update()
    )
    result = (await db.execute(stmt)).scalar_one_or_none()
    logger.info(f"Fetching order to delete for order_id: {order_id}")
    if not result:
        logger.error(f"Order with order_id: {order_id} not found for deletion")
        raise HTTPException(status_code=404, detail="order not found")
    if result.status not in [
        OrderStatus.cancelled,
        OrderStatus.delivered,
        OrderStatus.shipped,
    ]:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete an active order. Please cancel it first.",
        )
    result.order_delete = True
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error("Database integrity error while deleting order")
        raise HTTPException(status_code=500, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while deleting order")
        raise HTTPException(status_code=500, detail="internal server error")
    await order_invalidation(user_id=user_id)
    logger.info(f"Order deletion process completed for order_id: {order_id}")
    return StandardResponse(status="success", message="order deleted", data=None)
