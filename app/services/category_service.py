from app.api.v1.schemas import (
    CategoryResponse,
    PaginatedMetadata,
    PaginatedResponse,
    StandardResponse,
)
from app.models import Category
from fastapi import HTTPException
from sqlalchemy.orm import selectinload
from app.logs.logger import get_logger
from sqlalchemy import select, func
from app.utils.redis import cache, cached
from sqlalchemy.exc import IntegrityError
from app.utils.helper import unique_id, user_role

logger = get_logger("category")


async def category(name, request, db):
    user_id = unique_id(request)
    role = user_role(request)
    if not user_id:
        logger.warning("Unauthorized access attempt: missing user_id in payload")
        raise HTTPException(status_code=401, detail="unauthorized access")
    if role not in ("Admin", "Owner"):
        logger.warning("Forbidden access: user_id=%s is not admin/owner", user_id)
        raise HTTPException(status_code=403, detail="restricted access")
    normalized_name = " ".join(name.split())
    category_exists = (
        await db.execute(
            select(Category).where(
                func.lower(
                    func.trim(func.regexp_replace(Category.name, r"\s+", "", "g"))
                )
                == normalized_name.replace(" ", "").lower()
            )
        )
    ).scalar_one_or_none()
    if category_exists:
        logger.warning("user: %s, tried duplicating category name: %s", user_id, name)
        raise HTTPException(status_code=400, detail="category name already exists")
    new_category = Category(name=name)
    try:
        db.add(new_category)
        await db.commit()
    except IntegrityError:
        logger.error("database error while creating category: name=%s", name)
        await db.rollback()
        raise HTTPException(status_code=500, detail="database error")
    except Exception:
        logger.exception("error while creating category: name=%s", name)
        await db.rollback()
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("category: %s, created successfully", name)
    return StandardResponse(status="success", message="category created", data=None)


async def retrieve(page, limit, db):
    offset = (page - 1) * limit
    cache_key = f"categories:page={page}:limit={limit}"
    cached_data = await cache(cache_key)
    if cached_data:
        logger.info("Cache hit for categories")
        return StandardResponse(**cached_data)
    stmt = select(Category).where(Category.is_deleted.is_(False))
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
    full_response = StandardResponse(status="success", message="categories", data=data)
    await cached(cache_key, full_response, ttl=86400)
    logger.info(
        f"all categories fetched successfully page={page}, limit={limit}, total={total}"
    )
    return full_response


async def delete_category(category_id, request, db):
    user_id = unique_id(request)
    role = user_role(request)
    if not user_id:
        logger.warning(
            "Unauthorized delete attempt: missing user_id, category_id=%s", category_id
        )
        raise HTTPException(status_code=403, detail="Unauthorized access.")
    if role not in ("Admin", "Owner"):
        logger.warning(
            f"{user_id}, tried deleting a category without admin powers, category id: {category_id}"
        )
        raise HTTPException(status_code=403, detail="not authorized")
    try:
        stmt = (
            select(Category)
            .options(selectinload(Category.sub_categories))
            .where(Category.id == category_id, Category.is_deleted.is_(False))
            .with_for_update()
        )
        data = (await db.execute(stmt)).scalar_one_or_none()
        if not data:
            logger.warning(
                f"{user_id}, tried deleting a nonexistent category, category id: {category_id}"
            )
            raise HTTPException(status_code=404, detail="category not found")
        data.is_deleted = True
        for subcategory in data.sub_categories:
            subcategory.is_deleted = True
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error occured while deleting category: %s", category_id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error occured while deleting category: %s", category_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("deleted category %s", category_id)
    return StandardResponse(
        status="success",
        message="deleted category",
        data={
            "id": category_id,
            "user_id": user_id,
            "deleted": True,
        },
    )
