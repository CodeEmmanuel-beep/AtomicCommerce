from fastapi import HTTPException
from app.models import Address, Order, OrderStatus
from app.logs.logger import get_logger
from sqlalchemy import select, func
from app.utils.redis import (
    order_address_invalidation,
    order_invalidation,
    cache,
    cached,
)
from sqlalchemy.orm import contains_eager, selectinload
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
            Order.id == order_id,
            ~Order.order_delete,
            Order.store_id == store_id,
            Order.user_id == user_id,
        )
        .with_for_update()
    )
    order = (await db.execute(stmt)).scalar_one_or_none()
    if not order:
        logger.error(
            f"Order with order_id: {order_id} not found for adding delivery address"
        )
        raise HTTPException(status_code=404, detail="no order found")
    new_address = Address(
        store_id=store_id,
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
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database integrity error while adding delivery address: {e}")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while adding delivery address")
        raise HTTPException(status_code=500, detail="internal server error")
    background_task.add_task(order_invalidation, user_id)
    background_task.add_task(order_address_invalidation, user_id)
    logger.info(f"Delivery address added successfully for order_id: {order_id}")
    return StandardResponse(
        status="success", message="delivery address added successfully", data=None
    )


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
            Order.store_id == store_id,
            Order.user_id == user_id,
            Address.is_deleted.is_(False),
        )
        .distinct()
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
            select(func.count(func.distinct(Address.id)))
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


async def choose_order_address(
    store_id, order_id, address_id, db, payload, background_task
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.error("Unauthorized attempt to choose delivery address")
        raise HTTPException(status_code=401, detail="not authorized")
    try:
        order = (
            await db.execute(
                select(Order)
                .where(
                    Order.id == order_id,
                    Order.store_id == store_id,
                    Order.user_id == user_id,
                    Order.order_delete.is_(False),
                )
                .with_for_update(of=Order)
            )
        ).scalar_one_or_none()
        if not order:
            logger.warning(
                "Order with order_id: '%s' not found for choosing delivery address",
                order_id,
            )
            raise HTTPException(status_code=404, detail="no order created")
        address = (
            await db.execute(
                select(Address)
                .options(selectinload(Address.orders).selectinload(Order.user))
                .where(
                    Address.id == address_id,
                    Address.is_deleted.is_(False),
                    Address.store_id == store_id,
                )
            )
        ).scalar_one_or_none()
        if not address or not any(order.user_id == user_id for order in address.orders):
            logger.warning(
                "user: %s tried choosing a non existent address: %s for order: %s",
                user_id,
                address_id,
                order_id,
            )
            raise HTTPException(
                status_code=404,
                detail="address not found, please input your address to complete the order",
            )
        if order.status != OrderStatus.pending:
            logger.warning(
                "user '%s' tried changing the address for an order already handled order_id '%s'",
                user_id,
                order_id,
            )
            raise HTTPException(
                status_code=409, detail="can only change the address of pending orders"
            )
        order.delivery_address = [
            address.street,
            address.city,
            address.state,
            address.country,
        ]
        order.delivery_address_id = address.id
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("Database integrity error while choosing delivery address")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while choosing delivery address")
        raise HTTPException(status_code=500, detail="internal server error")
    background_task.add_task(order_invalidation, user_id)
    logger.info(f"Delivery address chosen successfully for order_id: {order_id}")
    return StandardResponse(
        status="success", message="delivery address chosen successfully", data=None
    )


async def remove_delivery_address(store_id, address_id, background_task, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.error("Unauthorized attempt to delete delivery address")
        raise HTTPException(status_code=401, detail="not authorized")
    try:
        stmt = (
            select(Address)
            .join(Order, Address.id == Order.delivery_address_id)
            .options(contains_eager(Address.orders))
            .where(
                Address.id == address_id,
                Address.is_deleted.is_(False),
                Address.store_id == store_id,
                Order.user_id == user_id,
            )
            .with_for_update()
        )
        address = (await db.execute(stmt)).unique().scalar_one_or_none()
        if not address:
            logger.error(
                "Address with address_id: '%s' not found for user_id: '%s'",
                address_id,
                user_id,
            )
            raise HTTPException(status_code=404, detail="address not found")
        for order in address.orders:
            if order.status not in [
                OrderStatus.cancelled,
                OrderStatus.delivered,
            ]:
                logger.warning(
                    "User_id: '%s' attempted to delete delivery address with active orders",
                    user_id,
                )
                raise HTTPException(
                    status_code=400,
                    detail="Cannot delete address for an active order. Please cancel the order first.",
                )
        address.is_deleted = True
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("Database integrity error while deleting delivery address")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while deleting delivery address")
        raise HTTPException(status_code=500, detail="internal server error")
    background_task.add_task(order_invalidation, user_id)
    background_task.add_task(order_address_invalidation, user_id)
    logger.info(f"Delivery address successfully deleted address_id: {address_id}")
    return StandardResponse(
        status="success", message="delivery address deleted successfully", data=None
    )
