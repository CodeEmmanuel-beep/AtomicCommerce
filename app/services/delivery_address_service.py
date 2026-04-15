from fastapi import HTTPException
from app.models import Address, Order
from app.logs.logger import get_logger
from sqlalchemy import select, func
from app.utils.redis import (
    order_address_invalidation,
    order_invalidation,
    cache,
    cached,
)
from sqlalchemy.orm import selectinload
from app.api.v1.schemas import (
    StandardResponse,
    PaginatedMetadata,
    PaginatedResponse,
    AddressResponse,
)
from sqlalchemy.exc import IntegrityError

logger = get_logger("delivery_address")


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
        .options(selectinload(Address.orders))
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
    for order in address.orders:
        if order.status not in ["cancelled", "delivered", "shipped"]:
            logger.warning(
                f"User_id: {user_id} attempted to delete delivery address with active orders"
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
    logger.info(f"Delivery address successfully deleted address_id: {address_id}")
    return {"status": "success", "message": "delivery address deleted successfully"}
