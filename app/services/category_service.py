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
        raise HTTPException(status_code=401, detail="unauthorized access")
    stmt = select(User).where(or_(User.role == "Admin", User.role == "Owner"))
    admin = (await db.execute(stmt)).scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=403, detail="you are not admin")
    new_category = Category(name=name)
    try:
        db.add(new_category)
        await db.commit()
        await db.refresh(new_category)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=500, detail="internal server error")
    return {"status": "success", "message": "category created"}


async def retrieve(page, limit, db):
    offset = (page - 1) * limit
    stmt = select(Category)
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar() or 0
    categories = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    if not categories:
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
    username = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=403, detail="Unauthorized access.")
    stmt = select(User).where(or_(User.role == "Admin", User.role == "Owner"))
    admin = (await db.execute(stmt)).scalar_one_or_none()
    if not admin:
        logger.warning(
            f"{username}, tried deleting a category without admin powers, product id: {category_id}"
        )
        raise HTTPException(status_code=403, detail="not authorized")
    stmt = select(Category).where(Category.id == category_id)
    data = (await db.execute(stmt)).scalar_one_or_none()
    if not data:
        logger.warning(
            f"{username}, tried deleting a nonexistent product, product id: {category_id}"
        )
        raise HTTPException(status_code=404, detail="invalid field")
    logger.info("deleted tasks %s", category_id)
    try:
        await db.delete(data)
        await db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=500, detail="internal server error")
    return {
        "status": "success",
        "message": "deleted product",
        "data": {
            "id": data.id,
            "username": username,
            "deleted": "Yes",
        },
    }
