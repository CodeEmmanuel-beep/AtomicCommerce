from app.models import SubCategory, User
from app.logs.logger import get_logger
from fastapi import HTTPException
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError

logger = get_logger("sub_categories")


async def sub_category(category_id, name, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Unauthorized access attempt: missing user_id in payload")
        raise HTTPException(status_code=401, detail="unauthorized access")
    stmt = select(User).where(or_(User.role == "Admin", User.role == "Owner"))
    admin = (await db.execute(stmt)).scalar_one_or_none()
    if not admin:
        logger.warning("Forbidden access: user_id=%s is not admin/owner", user_id)
        raise HTTPException(status_code=403, detail="restricted access")
    sub_category_exists = (
        await db.execute(select(SubCategory).where(SubCategory.name == name))
    ).scalar_one_or_none()
    if sub_category_exists:
        logger.warning(
            "user: %s, tried duplicating sub_category name: %s", user_id, name
        )
        raise HTTPException(status_code=400, detail="sub_category name already exists")
    sub_category = SubCategory(category_id=category_id, name=name)
    try:
        db.add(sub_category)
        await db.commit()
    except IntegrityError:
        logger.error("database error while creating sub_category: name=%s", name)
        await db.rollback()
        raise HTTPException(status_code=500, detail="database error")
    except Exception:
        logger.exception("error while creating sub_category: name=%s", name)
        await db.rollback()
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("sub_category: %s, created successfully", name)
    return {"status": "success", "message": "sub_category created"}


async def delete_sub_category(sub_category_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning(
            "Unauthorized delete attempt: missing user_id, sub_category_id=%s",
            sub_category_id,
        )
        raise HTTPException(status_code=403, detail="Unauthorized access.")
    stmt = select(User).where(or_(User.role == "Admin", User.role == "Owner"))
    admin = (await db.execute(stmt)).scalar_one_or_none()
    if not admin:
        logger.warning(
            f"{user_id}, tried deleting a sub_category without admin powers, product id: {sub_category_id}"
        )
        raise HTTPException(status_code=403, detail="not authorized")
    stmt = select(SubCategory).where(
        SubCategory.id == sub_category_id, ~SubCategory.is_deleted
    )
    data = (await db.execute(stmt)).scalar_one_or_none()
    if not data:
        logger.warning(
            f"{user_id}, tried deleting a nonexistent sub_category,sub category id: {sub_category_id}"
        )
        raise HTTPException(status_code=404, detail="sub category not found")
    data.is_deleted = True
    try:
        await db.commit()
    except IntegrityError:
        db.rollback()
        logger.error("database error occured while deleting sub_category; %s", data.id)
        raise HTTPException(status_code=500, detail="database error")
    except Exception:
        db.rollback()
        logger.exception("error occured while deleting sub_category; %s", data.id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("deleted sub_category %s", sub_category_id)
    return {
        "status": "success",
        "message": "deleted sub_category",
        "data": {
            "id": sub_category_id,
            "username": user_id,
            "deleted": "Yes",
        },
    }
