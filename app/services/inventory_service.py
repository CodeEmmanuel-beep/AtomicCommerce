from app.models import Inventory, Product, store_owners, store_staffs
from sqlalchemy.exc import IntegrityError
from app.api.v1.schemas import (
    StandardResponse,
    PaginatedMetadata,
    PaginatedResponse,
    InventoryResponse,
)
from fastapi import HTTPException, Response, status
from sqlalchemy.orm import selectinload
from app.utils.helper import store_exist, store_inventory
from app.logs.logger import get_logger
from sqlalchemy import select, exists, func
from app.utils.redis import cache, cached

logger = get_logger("inventory")


async def create(store_id: int, product_id: int, stock_quantity: int, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at the create endpoint")
        raise HTTPException(status_code=401, detail="not authenticated")
    stmt = select(
        exists().where(
            store_owners.c.stores_id == store_id,
            store_owners.c.users_id == user_id,
        ),
        exists().where(
            store_staffs.c.stores_id == store_id,
            store_staffs.c.users_id == user_id,
        ),
        exists().where(
            Product.id == product_id, Product.store_id == store_id, ~Product.is_deleted
        ),
    )
    result = (await db.execute(stmt)).fetchone() or (False, False, False)
    owner, staff, product_verified = result
    if not owner and not staff:
        logger.warning(
            "user: %s, made an ineligible attempt in create inventory endpoint", user_id
        )
        raise HTTPException(status_code=403, detail="ineligible credentials")
    if not product_verified:
        logger.warning(
            "user: %s tried creating inventory for invalid or cross-tenant product_id: %s",
            user_id,
            product_id,
        )
        raise HTTPException(status_code=404, detail="product not found in this store")
    stock = Inventory(
        store_id=store_id, product_id=product_id, stock_quantity=stock_quantity
    )
    try:
        db.add(stock)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error(
            "database error occurred while creating inventory for store: %s, user affected '%s'",
            store_id,
            user_id,
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            "error occurred while creating inventory for store: %s, user affected '%s'",
            store_id,
            user_id,
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("inventory created successfully for product: %s", product_id)
    return {"message": "inventory created"}


async def read(store_id, inventory_id, db, payload):
    user_id = await store_exist(store_id, db, payload)
    stmt = store_inventory(store_id, inventory_id)
    result = (await db.execute(stmt)).scalar_one_or_none()
    if not result:
        logger.warning("user: %s, tried fetching a non existent inventory", user_id)
        raise HTTPException(status_code=404, detail="inventory not found")
    logger.info("read function returned data for user %s", user_id)
    return {
        "stock_quantity": result.stock_quantity,
        "time_of_stock": result.last_updated,
    }


async def read_all(store_id, page, limit, db, payload):
    user_id = await store_exist(store_id, db, payload)
    offset = (page - 1) * limit
    cache_key = f"inventory:{user_id}:{store_id}:{page}:{limit}"
    inventory_cache = await cache(cache_key)
    if inventory_cache:
        logger.info(
            "inventory cache hit for user_id: %s, store_id: %s", user_id, store_id
        )
        return StandardResponse(**inventory_cache)
    stmt = store_inventory(store_id, None)
    results = (
        (
            await db.execute(
                stmt.order_by(Inventory.last_updated.desc()).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not results:
        logger.warning("user: %s, tried fetching a non existent inventory", user_id)
        raise HTTPException(status_code=404, detail="inventory not found")
    total = (
        await db.execute(
            select(func.count(Inventory.id)).where(
                Inventory.store_id == store_id, ~Inventory.is_deleted
            )
        )
    ).scalar() or 0
    logger.info("total inventories for store: %s, is: %s", store_id, total)
    data = PaginatedMetadata[InventoryResponse](
        items=[InventoryResponse.model_validate(r) for r in results],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    full_response = StandardResponse(
        status="success", message="store inventory", data=data
    )
    await cached(cache_key, full_response, ttl=600)
    logger.info("read_all function returned data for user %s", user_id)
    return full_response


async def update(store_id: int, inventory_id: int, stock_quantity: int, db, payload):
    user_id = await store_exist(store_id, db, payload)
    stmt = store_inventory(store_id, inventory_id)
    stmt = stmt.with_for_update()
    inventory = (await db.execute(stmt)).scalar_one_or_none()
    if not inventory:
        logger.warning("user: %s, tried updating a non existent inventory", user_id)
        raise HTTPException(status_code=404, detail="inventory not found")
    if inventory.stock_quantity == stock_quantity:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    inventory.stock_quantity = stock_quantity
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error(
            "database error occurred while updating inventory for store: %s, user affected '%s'",
            store_id,
            user_id,
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            "error occurred while updating inventory for store: %s, user affected '%s'",
            store_id,
            user_id,
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("inventory: %s, updated successfully", inventory_id)
    return {"message": "inventory updated"}


async def delete(store_id: int, inventory_id: int, db, payload):
    user_id = await store_exist(store_id, db, payload)
    stmt = store_inventory(store_id, inventory_id)
    stmt = stmt.with_for_update()
    inventory = (await db.execute(stmt)).scalar_one_or_none()
    if not inventory:
        logger.warning(
            "user: %s, tried deleting a non existent inventory",
            user_id,
        )
        raise HTTPException(status_code=404, detail="inventory not found")
    inventory.is_deleted = True
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error(
            "database error occurred while deleting inventory for store: %s, user affected '%s'",
            store_id,
            user_id,
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            "error occurred while deleting inventory for store: %s, user affected '%s'",
            store_id,
            user_id,
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("inventory: %s, successfully deleted", inventory_id)
    return {"message": "inventory deleted"}
