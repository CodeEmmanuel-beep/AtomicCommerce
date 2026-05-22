from app.models import Inventory, Store, Product, User, store_owners, store_staffs
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from app.logs.logger import get_logger
from sqlalchemy import select, or_, exists

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
    logger.info("inventory: %s, created successfully", stock.id)
    return {"message": "inventory created"}


async def read(store_id, inventory_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at the read endpoint")
        raise HTTPException(status_code=401, detail="not authenticated")
    auth_stmt = select(
        exists().where(
            store_owners.c.stores_id == store_id, store_owners.c.users_id == user_id
        ),
        exists().where(
            store_staffs.c.stores_id == store_id, store_staffs.c.users_id == user_id
        ),
    )
    auth_result = (await db.execute(auth_stmt)).fetchone()
    owner_exist, staff_exist = auth_result if auth_result else (False, False)

    if not owner_exist and not staff_exist:
        logger.warning(
            "user: %s, made an ineligible attempt in read inventory endpoint for store: %s",
            user_id,
            store_id,
        )
        raise HTTPException(status_code=403, detail="ineligible credentials")
    stmt = (
        select(Inventory).where(
            Inventory.id == inventory_id,
            Inventory.store_id == store_id,
            ~Inventory.is_deleted,
        ),
    )
    result = (await db.execute(stmt)).scalar_one_or_none()
    if not result:
        logger.warning(
            "user: %s, made an ineligible attempt in read inventory endpoint"
        )
        raise HTTPException(status_code=403, detail="ineligible credentials")
    logger.info("read inventory endpoint returned data for user %s", user_id)
    return {
        "stock_quantity": result.stock_quantity,
        "time_of_stock": result.last_updated,
    }


async def update(store_id: int, inventory_id: int, stock_quantity: int, db, payload):
    user_id = payload.get("user_id")
    stmt = (
        select(Inventory)
        .join(Store, Store.id == Inventory.store_id)
        .where(
            Inventory.id == inventory_id,
            Store.id == store_id,
            or_(
                Store.user_owners.any(User.id == user_id),
                Store.user_staffs.any(User.id == user_id),
            ),
        )
    )
    inventory = (await db.execute(stmt)).scalar_one_or_none()
    if not inventory:
        logger.warning(
            "user: %s, made an ineligible attempt in updating inventory endpoint"
        )
        raise HTTPException(status_code=403, detail="ineligible credentials")
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
    user_id = payload.get("user_id")
    stmt = (
        select(Inventory)
        .join(Store, Store.id == Inventory.store_id)
        .where(
            Inventory.id == inventory_id,
            Store.id == store_id,
            or_(
                Store.user_owners.any(User.id == user_id),
                Store.user_staffs.any(User.id == user_id),
            ),
        )
    )
    inventory = (await db.execute(stmt)).scalar_one_or_none()
    if not inventory:
        logger.warning(
            "user: %s, made an ineligible attempt in deleting inventory endpoint"
        )
        raise HTTPException(status_code=403, detail="ineligible credentials")
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
