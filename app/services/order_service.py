from app.api.v1.schemas import (
    OrderResponse,
    PaginatedMetadata,
    PaginatedResponse,
    StandardResponse,
    OrderItemRes,
    AddressResponse,
)
from app.database.async_config import AsyncSessionLocal
from app.models import (
    Cart,
    Order,
    OrderItem,
    CartItem,
    Payment,
    Product,
    Inventory,
    Address,
)
from datetime import datetime, timezone
from fastapi import HTTPException
from app.logs.logger import get_logger
from sqlalchemy import select, func, update, and_
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from app.utils.redis import (
    cache,
    cached,
    order_invalidation,
    cart_invalidation,
    cache_version,
    order_address_invalidation,
)
import asyncio


logger = get_logger("order")


async def product_availability(product_ids: list[int]):
    if isinstance(product_ids, int):
        product_ids = [product_ids]
    async with AsyncSessionLocal() as conn:
        try:
            async with conn.begin():
                out_of_stock_ids = (
                    select(Inventory.product_id)
                    .where(Inventory.stock_quantity == 0)
                    .scalar_subquery()
                )
                await conn.execute(
                    update(Product)
                    .where(
                        and_(
                            Product.id.in_(out_of_stock_ids),
                            Product.id.in_(product_ids),
                        ),
                        Product.product_availability != "out_of_stock",
                    )
                    .values(product_availability="out_of_stock")
                    .execution_options(synchronize_session="fetch")
                )
                logger.info("Background availability sync complete.")
        except Exception:
            logger.exception("failed to update product availability")


async def create_orders(store_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.error("Unauthorized attempt to create order")
        raise HTTPException(
            status_code=401, detail="you must be a registered user to make orders"
        )
    logger.info(f"Creating order for user_id: {user_id}")
    order = Order(
        user_id=user_id,
        store_id=store_id,
        created_at=datetime.now(timezone.utc),
    )
    try:
        db.add(order)
        await db.commit()
        await order_invalidation(user_id=user_id)
    except IntegrityError:
        await db.rollback()
        logger.error("Database integrity error while creating order")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while creating order")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"Order created successfully with order_id: {order.id}")
    return {"status": "success", "message": "order successfully created"}


async def create_order_items(
    store_id, cart_id, order_id, background_tasks, db, payload
):
    user_id = payload.get("user_id")
    stmt = (
        select(Order)
        .where(
            Order.id == order_id, Order.store_id == store_id, Order.user_id == user_id
        )
        .with_for_update()
    )
    order = (await db.execute(stmt)).scalar_one_or_none()
    if not order:
        logger.error("No order created")
        raise HTTPException(status_code=404, detail="no order created")
    stmt = (
        select(Cart)
        .options(selectinload(Cart.cartitems).selectinload(CartItem.product))
        .where(
            Cart.id == cart_id,
            ~Cart.check_out,
            Cart.user_id == user_id,
            Cart.store_id == store_id,
        )
    )
    result = await db.execute(stmt)
    carts = result.scalar_one_or_none()
    logger.info(f"Fetched cart items for cart_id: {cart_id}")
    if not carts:
        raise HTTPException(status_code=404, detail="no cart found")
    if not carts.cartitems:
        raise HTTPException(status_code=404, detail="no cart items found")
    items = [
        i
        for i in carts.cartitems
        if i.product.is_deleted or i.product.product_availability != "available"
    ]
    if items:
        return {
            "message": "there is an update on your cart, please update cart before check out"
        }
    new_orders = [
        OrderItem(
            order_id=order_id,
            product_id=cartitem.product_id,
            quantity=cartitem.quantity,
            price=cartitem.product.product_price * cartitem.quantity,
        )
        for cartitem in carts.cartitems
    ]
    total_quantity = sum(new_order.quantity for new_order in new_orders)
    total_amount = sum(new_order.price for new_order in new_orders)
    try:
        order.total_quantity = total_quantity
        order.total_amount = total_amount
        db.add_all(new_orders)
        update_result = await db.execute(
            update(Cart)
            .where(
                Cart.id == cart_id,
                ~Cart.check_out,
                Cart.user_id == user_id,
            )
            .values(check_out=True)
        )
        if update_result.rowcount == 0:
            raise HTTPException(status_code=409, detail="cart already checked out")
        background_tasks.add_task(
            product_availability, [item.product_id for item in new_orders]
        )
        await db.commit()
        await asyncio.gather(order_invalidation(user_id), cart_invalidation(user_id))
    except IntegrityError:
        logger.error("Database integrity error while creating order items")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        logger.exception("error while creating order items")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"Order items created successfully for order_id: {order_id}")
    return {"status": "success", "message": "order item successfully created"}


async def delivery_address(
    store_id, order_id, delivery_address, background_task, db, payload
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.error("Unauthorized attempt to add delivery address")
        raise HTTPException(status_code=401, detail="not authorized")
    stmt = (
        select(Order)
        .where(
            Order.id == order_id, Order.store_id == store_id, Order.user_id == user_id
        )
        .with_for_update()
    )
    order = (await db.execute(stmt)).scalar_one_or_none()
    if not order:
        logger.error(
            f"Order with order_id: {order_id} not found for adding delivery address"
        )
        raise HTTPException(status_code=404, detail="no order created")
    new_address = Address(
        street=delivery_address.street,
        city=delivery_address.city,
        state=delivery_address.state,
        country=delivery_address.country,
    )
    order.delivery_address = [
        delivery_address.street,
        delivery_address.city,
        delivery_address.state,
        delivery_address.country,
    ]
    try:
        db.add(new_address)
        await db.flush()
        order.delivery_address_id = new_address.id
        await db.commit()
        background_task.add_task(order_invalidation, user_id)
        background_task.add_task(order_address_invalidation, user_id)
    except IntegrityError:
        await db.rollback()
        logger.error("Database integrity error while adding delivery address")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while adding delivery address")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"Delivery address added successfully for order_id: {order_id}")
    return {"status": "success", "message": "delivery address added successfully"}


async def view_delivery_address(store_id, page, limit, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.error("Unauthorized attempt to view delivery address")
        raise HTTPException(status_code=401, detail="not authorized")
    offset = (page - 1) * limit
    cache_key = f"delivery_address:{user_id}:{store_id}:{page}:{limit}"
    cached_data = await cache(cache_key)
    if cached_data:
        logger.info(
            f"Delivery address cache hit for user_id: {user_id}, store_id: {store_id}"
        )
        return StandardResponse(**cached_data)
    stmt = (
        select(Address)
        .join(Order, Address.id == Order.delivery_address_id)
        .where(
            Order.store_id == store_id, Order.user_id == user_id, ~Address.is_deleted
        )
        .offset(offset)
        .limit(limit)
    )
    address = (await db.execute(stmt)).scalars().all()
    if not address:
        logger.info(f"no address stored for user_id: {user_id} in store_id: {store_id}")
        return StandardResponse(
            status="success", message="no address stored", data=None
        )
    total = (
        await db.execute(
            select(func.count(Address.id))
            .join(Order, Address.id == Order.delivery_address_id)
            .where(
                Order.store_id == store_id,
                Order.user_id == user_id,
                ~Address.is_deleted,
            )
        )
    ).scalar() or 0
    data = PaginatedMetadata[AddressResponse](
        items=[AddressResponse.model_validate(ad) for ad in address],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    full_response = StandardResponse(
        status="success", message="delivery addresses", data=data
    )
    await cached(cache_key, full_response, ttl=18000)
    logger.info(f"Delivery address retrieved successfully for store_id: {store_id}")
    return full_response


async def choose_order_address(store_id, order_id, address_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.error("Unauthorized attempt to choose delivery address")
        raise HTTPException(status_code=401, detail="not authorized")
    order = await db.get(Order, order_id, with_for_update=True)
    if not order:
        logger.error(
            f"Order with order_id: {order_id} not found for choosing delivery address"
        )
        raise HTTPException(status_code=404, detail="no order created")
    stmt = select(Address).where(
        Address.id == address_id,
        ~Address.is_deleted,
        Address.orders.any(Order.store_id == store_id),
        Address.orders.any(Order.user_id == user_id),
    )
    address = (await db.execute(stmt)).scalar_one_or_none()
    if not address:
        logger.error(
            f"Address with address_id: {address_id} not found for user_id: {user_id}"
        )
        raise HTTPException(
            status_code=404,
            detail="address not found, please input your address to complete the order",
        )
    order.delivery_address = [
        address.street,
        address.city,
        address.state,
        address.country,
    ]
    order.delivery_address_id = address.id
    try:
        await db.commit()
        await order_invalidation(user_id=user_id)
    except IntegrityError:
        await db.rollback()
        logger.error("Database integrity error while choosing delivery address")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while choosing delivery address")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"Delivery address chosen successfully for order_id: {order_id}")
    return {"status": "success", "message": "delivery address chosen successfully"}


async def delete_delivery_address(store_id, address_id, background_task, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.error("Unauthorized attempt to delete delivery address")
        raise HTTPException(status_code=401, detail="not authorized")
    stmt = (
        select(Address)
        .options(selectinload(Address, Order.delivery_address_id == Address.id))
        .where(
            Address.id == address_id,
            ~Address.is_deleted,
            Address.orders.any(Order.store_id == store_id),
            Address.orders.any(Order.user_id == user_id),
        )
    )
    address = (await db.execute(stmt)).scalar_one_or_none()
    if not address:
        logger.error(
            f"Address with address_id: {address_id} not found for user_id: {user_id}"
        )
        raise HTTPException(status_code=404, detail="address not found")
    if address.orders.status not in ["cancelled", "delivered", "shipped"]:
        logger.warning(
            f"User_id: {user_id} attempted to delete delivery address for active order_id: {order_id}"
        )
        raise HTTPException(
            status_code=400,
            detail="Cannot delete address for an active order. Please cancel the order first.",
        )
    address.is_deleted = True
    try:
        await db.commit()
        background_task.add_task(order_invalidation, user_id)
        background_task.add_task(order_address_invalidation, user_id)
    except IntegrityError:
        await db.rollback()
        logger.error("Database integrity error while deleting delivery address")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while deleting delivery address")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"Delivery address deleted successfully for order_id: {order_id}")
    return {"status": "success", "message": "delivery address deleted successfully"}


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
            .selectinload(OrderItem.cartitems)
            .selectinload(CartItem.product)
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
            select(func.count())
            .select_from(Order)
            .where(
                Order.user_id == user_id,
                Order.store_id == store_id,
                ~Order.order_delete,
            )
        )
    ).scalar() or 0
    logger.info(f"Total orders found: {total} for user_id: {user_id}")
    order = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    if not order:
        return StandardResponse(status="success", message="no orders found", data=None)
    logger.info(f"Preparing paginated response for orders of user_id: {user_id}")
    data = PaginatedMetadata[OrderResponse](
        items=[OrderResponse.model_validate(od) for od in order],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    logger.info(f"Orders retrieved successfully for user_id: {user_id}")
    await cached(order_key, data, ttl=18000)
    return StandardResponse(status="success", message="orders", data=data)


async def view_order(store_id, order_id, page, limit, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.error("Unauthorized attempt to view order")
        raise HTTPException(status_code=401, detail="not a registered buyer")
    offset = (page - 1) * limit
    if page < 1 or limit < 1:
        raise HTTPException(
            status_code=400, detail="page number and limit must be greater than 0"
        )
    version = await cache_version("order_key")
    order_key = f"orders:v{version}:{user_id}:{store_id}:{order_id}:{page}:{limit}"
    cache_key = await cache(order_key)
    if cache_key:
        return StandardResponse(**cache_key)
    stmt = (
        select(Order)
        .options(
            selectinload(Order.orderitems)
            .selectinload(OrderItem.cartitems)
            .selectinload(CartItem.product)
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
        logger.error(f"Order with order_id: {order_id} not found")
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
    response = {"Order": order_data, "Ordered_items": data}
    await cached(order_key, response, ttl=7200)
    logger.info(f"Order details retrieved successfully for order_id: {order_id}")
    return StandardResponse(status="success", message="order_flow", data=response)


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
        .join(Payment, Order.id == Payment.order_id, isouter=True)
        .options(selectinload(Order.payment))
        .where(
            Order.user_id == user_id,
            Order.store_id == store_id,
            Order.id == order_id,
        )
        .with_for_update()
    )
    logger.info(f"Fetching order to cancel for order_id: {order_id}")
    result = (await db.execute(stmt)).scalar_one_or_none()
    if not result:
        logger.error(f"Order with order_id: {order_id} not found for cancellation")
        raise HTTPException(status_code=404, detail="order item not found")
    payment_status = result.payment.status if result.payment else "pending"
    if payment_status == "pending":
        result.status = "Cancelled"
        logger.info(f"Order with order_id: {order_id} cancelled successfully")
    else:
        logger.error(
            f"Order with order_id: {order_id} cannot be cancelled, payment triggered"
        )
        raise HTTPException(
            status_code=400, detail="payment is triggered, cannot cancel order"
        )
    try:
        await db.commit()
        await order_invalidation(user_id=user_id)
    except IntegrityError:
        await db.rollback()
        logger.error("Database integrity error while cancelling order")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while cancelling order")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"Order cancellation process completed for order_id: {order_id}")
    return {"message": "order cancelled"}


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
            Order.user_id == user_id, Order.store_id == store_id, Order.id == order_id
        )
        .with_for_update()
    )
    result = (await db.execute(stmt)).scalar_one_or_none()
    logger.info(f"Fetching order to delete for order_id: {order_id}")
    if not result:
        logger.error(f"Order with order_id: {order_id} not found for deletion")
        raise HTTPException(status_code=404, detail="order item not found")
    if result.status not in ["cancelled", "delivered", "shipped"]:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete an active order. Please cancel it first.",
        )
    result.order_delete = True
    try:
        await db.commit()
        await order_invalidation(user_id=user_id)
    except IntegrityError:
        await db.rollback()
        logger.error("Database integrity error while deleting order")
        raise HTTPException(status_code=500, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while deleting order")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"Order deletion process completed for order_id: {order_id}")
    return {"message": "order deleted"}
