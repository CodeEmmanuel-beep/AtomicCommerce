from sqlalchemy import func, select, text
from app.utils.redis import cache, cache_version, cached
from app.api.v1.models import (
    StandardResponse,
    PaginatedMetadata,
    StoreResponse,
    PaginatedResponse,
)
from sqlalchemy.orm import selectinload
from app.logs.logger import get_logger
from app.models_sql import Store, Category
from enum import Enum

logger = get_logger("helper")


async def view_store_helper(seed, search_value, filter_column, page, limit, db):
    offset = (page - 1) * limit
    version = await cache_version("store_key")
    cache_key = f"store_view:v{version}:{seed}:{search_value}:{page}:{limit}"
    store_cache = await cache(cache_key)
    if store_cache:
        logger.info(f"cache hit for {search_value} at view store endpoint")
        return StandardResponse(**store_cache)
    total = None
    store_type = None
    async with db.connection() as conn:
        (await conn.execute(text("SELECT setseed(:s)"), {"s": seed}))
        if not isinstance(search_value, Enum):
            stmt = (
                select(Store)
                .join(Category.products)
                .options(selectinload(Store.category).selectinload(Category.products))
                .where(filter_column.ilike(f"%{search_value}%"), Store.approved)
                .order_by(func.random())
                .distinct()
            )
        else:
            stmt = (
                select(Store)
                .where(filter_column == search_value, Store.approved)
                .order_by(func.random())
            )
        store_type = (
            (await conn.execute(stmt.offset(offset).limit(limit))).scalars().all()
        )
        total = (
            await conn.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar() or 0
    logger.info("total stores found is '%s'", total)
    if not store_type:
        logger.info(
            "search for stores returned an empty list",
            search_value,
        )
        return StandardResponse(
            status="success",
            message="no store available under this search",
            data=None,
        )
    data = PaginatedMetadata[StoreResponse](
        items=[StoreResponse.model_validate(s_t) for s_t in store_type],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    response = StandardResponse(
        status="success", message=f"available {search_value} stores", data=data
    )
    await cached(cache_key, response, ttl=36000)
    logger.info("search for stores returned data")
    return response
