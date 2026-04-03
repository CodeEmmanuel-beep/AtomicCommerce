from app.models_sql import Inventory, Store, Product, User
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from app.logs.logger import get_logger
from sqlalchemy import select, or_, exists

logger = get_logger("inventory")


async def create(store_id: int, product_id: int, stock_quantity: int, db, payload):
    user_id = payload.get("user_id")
    stmt = select(
        exists().where(
            Store.id == store_id,
            Product.id == product_id,
            or_(
                Store.user_owners.any(User.id == user_id),
                Store.user_staffs.any(User.id == user_id),
            ),
        )
    ).join(Product, Store.id == Product.store_id)
    result = (await db.execute(stmt)).scalar()
    if not result:
        logger.warning(
            "user: %s, made an ineligible attempt in create inventory endpoint"
        )
        raise HTTPException(status_code=403, detail="ineligible credentials")
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
