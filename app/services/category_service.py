from app.api.v1.schemas import (
    CategoryResponse,
    PaginatedMetadata,
    PaginatedResponse,
    StandardResponse,
)
from app.models import Category, User
from fastapi import HTTPException
from app.logs.logger import get_logger
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError

logger = get_logger("category")


async def category(name, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Unauthorized access attempt: missing user_id in payload")
        raise HTTPException(status_code=401, detail="unauthorized access")
    stmt = select(User).where(or_(User.role == "Admin", User.role == "Owner"))
    admin = (await db.execute(stmt)).scalar_one_or_none()
    if not admin:
        logger.warning("Forbidden access: user_id=%s is not admin/owner", user_id)
        raise HTTPException(status_code=403, detail="you are not admin")
    new_category = Category(name=name)
    try:
        db.add(new_category)
        await db.commit()
        await db.refresh(new_category)
    except IntegrityError:
        logger.error("database error while creating category: name=%s", name)
        await db.rollback()
        raise HTTPException(status_code=500, detail="database error")
    except Exception:
        logger.exception("error while creating category: name=%s", name)
        await db.rollback()
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(
        "Category successfully created: id=%s, name=%s",
        new_category.id,
        new_category.name,
    )
    return {"status": "success", "message": "category created"}


async def retrieve(page, limit, db):
    offset = (page - 1) * limit
    stmt = select(Category)
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar() or 0
    categories = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    if not categories:
        logger.warning(
            "No categories found: page=%s, limit=%s, offset=%s, total=%s",
            page,
            limit,
            offset,
            total,
        )
        raise HTTPException(status_code=404, detail="no category found")
    data = PaginatedMetadata[CategoryResponse](
        items=[CategoryResponse.model_validate(item) for item in categories],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    logger.info(
        f"all categories fetched successfully page={page}, limit={limit}, total={total}"
    )
    return StandardResponse(status="success", message="categories", data=data)


async def delete_one(category_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning(
            "Unauthorized delete attempt: missing user_id, category_id=%s", category_id
        )
        raise HTTPException(status_code=403, detail="Unauthorized access.")
    stmt = select(User).where(or_(User.role == "Admin", User.role == "Owner"))
    admin = (await db.execute(stmt)).scalar_one_or_none()
    if not admin:
        logger.warning(
            f"{user_id}, tried deleting a category without admin powers, product id: {category_id}"
        )
        raise HTTPException(status_code=403, detail="not authorized")
    stmt = select(Category).where(Category.id == category_id)
    data = (await db.execute(stmt)).scalar_one_or_none()
    if not data:
        logger.warning(
            f"{user_id}, tried deleting a nonexistent category, category id: {category_id}"
        )
        raise HTTPException(status_code=404, detail="invalid field")
    try:
        await db.delete(data)
        await db.commit()
    except IntegrityError:
        db.rollback()
        logger.error("database error occured while deleting category; %s", data.id)
        raise HTTPException(status_code=500, detail="database error")
    except Exception:
        db.rollback()
        logger.exception("error occured while deleting category; %s", data.id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("deleted category %s", category_id)
    return {
        "status": "success",
        "message": "deleted product",
        "data": {
            "id": category_id,
            "username": user_id,
            "deleted": "Yes",
        },
    }
