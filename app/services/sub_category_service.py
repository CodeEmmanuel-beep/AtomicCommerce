from app.models import SubCategory, Category
from app.logs.logger import get_logger
from fastapi import HTTPException
from sqlalchemy import select, func, and_
from app.api.v1.schemas import (
    StandardResponse,
    PaginatedMetadata,
    PaginatedResponse,
    SubCategoryResponse,
)
from app.utils.redis import cache, cached
from app.utils.helper import user_role, unique_id
from sqlalchemy.exc import IntegrityError

logger = get_logger("sub_categories")


async def sub_category(category_id, name, db, request):
    user_id = unique_id(request)
    role = user_role(request)
    if not user_id:
        logger.warning("Unauthorized access attempt: missing user_id in payload")
        raise HTTPException(status_code=401, detail="unauthorized access")
    if role not in ("Admin", "Owner"):
        logger.warning("Forbidden access: user_id=%s is not admin/owner", user_id)
        raise HTTPException(status_code=403, detail="restricted access")
    normalized_name = "".join(name.split())
    category_exists = (
        await db.execute(
            select(Category).where(Category.id == category_id, ~Category.is_deleted)
        )
    ).scalar_one_or_none()
    if not category_exists:
        logger.warning(
            "user: %s, tried adding a sub_category to a non-existent category"
        )
        raise HTTPException(status_code=404, detail="category not found")
    sub_category_exists = (
        await db.execute(
            select(SubCategory).where(
                func.lower(func.regexp_replace(SubCategory.name, r"\s+", "", "g"))
                == normalized_name.lower()
            )
        )
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
    return StandardResponse(status="success", message="sub_category created", data=None)


async def retrieve(category_id, page, limit, db):
    offset = (page - 1) * limit
    cache_key = f"sub_categories:category_id={category_id}:page={page}:limit={limit}"
    cached_data = await cache(cache_key)
    if cached_data:
        logger.info(
            "Cache hit for sub_categories: category_id=%s, page=%s, limit=%s",
            category_id,
            page,
            limit,
        )
        return StandardResponse(**cached_data)
    check = (
        and_(SubCategory.category_id == category_id, SubCategory.is_deleted.is_(False))
        if category_id
        else SubCategory.is_deleted.is_(False)
    )
    stmt = select(SubCategory).where(check)
    sub_categories = (
        (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    )
    if not sub_categories:
        logger.warning(
            "No sub_categories found: page=%s",
            page,
        )
        raise HTTPException(status_code=404, detail="no sub category found")
    total = (
        await db.execute(select(func.count(SubCategory.id)).where(check))
    ).scalar() or 0
    data = PaginatedMetadata[SubCategoryResponse](
        items=[SubCategoryResponse.model_validate(item) for item in sub_categories],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    full_response = StandardResponse(
        status="success", message="sub_categories", data=data
    )
    await cached(cache_key, full_response, ttl=86400)
    logger.info(
        f"all categories fetched successfully page={page}, limit={limit}, total={total}"
    )
    return full_response


async def delete_sub_category(sub_category_id, db, request):
    user_id = unique_id(request)
    role = user_role(request)
    if not user_id:
        logger.warning(
            "Unauthorized delete attempt: missing user_id, sub_category_id=%s",
            sub_category_id,
        )
        raise HTTPException(status_code=403, detail="Unauthorized access.")
    if role not in ("Admin", "Owner"):
        logger.warning(
            f"{user_id}, tried deleting a sub_category without admin powers, sub_category id: {sub_category_id}"
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
        await db.rollback()
        logger.error("database error occured while deleting sub_category: %s", data.id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error occured while deleting sub_category: %s", data.id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("deleted sub_category %s", sub_category_id)
    return StandardResponse(
        status="success",
        message="deleted sub_category",
        data={
            "id": sub_category_id,
            "user_id": user_id,
            "deleted": True,
        },
    )
