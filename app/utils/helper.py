from sqlalchemy import func, select, text, or_, exists, and_
from app.utils.redis import cache, cache_version, cached
from app.api.v1.schemas import (
    StandardResponse,
    PaginatedMetadata,
    StoreResponse,
    PaginatedResponse,
    MembershipRes,
)
from fastapi import HTTPException
import uuid
from werkzeug.utils import secure_filename
from sqlalchemy.orm import selectinload
from app.logs.logger import get_logger
from app.models import Store, Category, Membership, store_owners, store_staffs, Product
from enum import Enum
from app.utils.supabase_url import cleaned_up
from app.database.config import settings
from io import BytesIO
from app.models import React
from app.api.v1.schemas import ReactionsSummary
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("helper")


async def react_summary(
    db: AsyncSession, r_id: list[int], db_schema, join_model, column_filter
) -> dict[int, ReactionsSummary]:
    if isinstance(r_id, int):
        r_id = [r_id]
    counts = (
        await db.execute(
            select(db_schema, React.type, func.count(React.id))
            .join(join_model, db_schema == join_model.id)
            .where(db_schema.in_(r_id), column_filter)
            .group_by(db_schema, React.type)
        )
    ).all()
    summary_map: dict[int, dict[str, int]] = {}
    for r_id_row, rtype, count in counts:
        key = rtype.name if hasattr(rtype, "name") else rtype
        summary_map.setdefault(r_id_row, {})[key] = count
    result: dict[int, ReactionsSummary] = {}
    for rid in r_id:
        summary = summary_map.get(rid, {})
        result[rid] = ReactionsSummary(
            like=summary.get("like", 0),
            love=summary.get("love", 0),
            laugh=summary.get("laugh", 0),
            angry=summary.get("angry", 0),
            wow=summary.get("wow", 0),
            sad=summary.get("sad", 0),
        )
    return result


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
    async with db as conn:
        (await conn.execute(text("SELECT setseed(:s)"), {"s": seed}))
        if not isinstance(search_value, Enum):
            stmt = (
                select(Store, func.random())
                .join(Category, Store.category_id == Category.id)
                .join(Product, Store.id == Product.store_id)
                .options(selectinload(Store.category), selectinload(Store.products))
                .where(filter_column.ilike(f"%{search_value}%"), Store.approved)
                .order_by(func.random())
                .distinct(Store)
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


async def upload_photo_helper(photo, db, payload, get_supabase):
    user_id = payload.get("user_id")
    filename = None
    max_size = 5 * 1024 * 1024
    allowed_types = ["image/jpeg", "image/webp", "image/png"]
    total_size = 0
    file_byte = b""
    with BytesIO() as buffer:
        try:
            if photo.content_type not in allowed_types:
                logger.warning(
                    "user '%s', tried uploading an invalid file type: %s",
                    user_id,
                    photo.content_type,
                )
                raise HTTPException(
                    status_code=400,
                    detail="Invalid file type. Only JPG, PNG, WEBP allowed.",
                )
            filename = f"{uuid.uuid4()}_{secure_filename(photo.filename)}"
            while chunk := await photo.read(1024 * 1024):
                total_size += len(chunk)
                if total_size > max_size:
                    logger.warning(
                        "user: %s, tried uploading a file larger than file limit, file size '%s'",
                        user_id,
                        total_size,
                    )
                    raise HTTPException(
                        status_code=400, detail="File too large. Max 5MB."
                    )
                buffer.write(chunk)
            file_byte = buffer.getvalue()
            upload_photo = await get_supabase.storage.from_(settings.BUCKET).upload(
                filename, file_byte, {"content-type": photo.content_type}
            )
            if hasattr(upload_photo, "error"):
                logger.error("error uploading store photo %s", upload_photo)
                raise HTTPException(
                    status_code=500, detail="error uploading store photo"
                )
            return filename
        except HTTPException:
            await db.rollback()
            raise
        except Exception:
            await db.rollback()
            if filename:
                await cleaned_up(
                    get_supabase,
                    filename,
                    context_1="error removing orphaned store photo",
                    context_2="successfully removed orphaned store photo",
                )
                logger.exception("error saving store photo")
                raise HTTPException(status_code=500, detail="error saving store photo")


async def file_generator(file, user_id):
    total_size = 0
    max_image_size = 5 * 1024 * 1024
    while chunk := await file.read(1024 * 1024):
        total_size += len(chunk)
        if total_size > max_image_size:
            logger.warning(
                "user: %s, tried uploading an image larger than the max size approved, image size attempted: %s",
                user_id,
                total_size,
            )
            raise HTTPException(
                status_code=400, detail="image should not be more than 5mb"
            )
        yield chunk


async def view_selected_members(
    store_id, filter_1, filter_2, context, page, limit, db, payload
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt to access view_active_members endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    offset = (page - 1) * limit
    if page < 1 or limit < 1:
        raise HTTPException(
            status_code=400, detail="page number and limit must be greater than 0"
        )
    store_cte = (
        select(Store)
        .where(Store.id == store_id)
        .where(
            or_(
                and_(
                    exists().where(
                        store_owners.c.users_id == user_id,
                        store_owners.c.stores_id == store_id,
                    )
                ),
                and_(
                    exists().where(
                        store_staffs.c.users_id == user_id,
                        store_staffs.c.stores_id == store_id,
                    )
                ),
            )
        )
    ).cte("portal_access")
    membership_stmt = (
        (
            select(Membership)
            .join(store_cte, Membership.store_id == store_cte.c.id)
            .where(filter_1, filter_2)
        )
        .offset(offset)
        .limit(limit)
    )
    version = await cache_version("member_key")
    cache_key = f"membership:v{version}:{context}:{store_id}:{page}:{limit}"
    cached_member = await cache(cache_key)
    if cached_member:
        logger.info("cached hit at view_active_members endpoint user %s", user_id)
        return StandardResponse(**cached_member)
    total = (
        await db.execute(
            select(func.count(Membership.id)).where(
                filter_1,
                filter_2,
                Membership.store_id == store_id,
            )
        )
    ).scalar() or 0
    logger.info(f"total number of {context} members: %s", total)
    if total == 0:
        logger.info(f"{context} members search returned an empty list")
        return StandardResponse(
            status="success", message=f"no {context} member found", data=None
        )
    logger.info(f"total number of {context} members %s", total)
    result = (await db.execute(membership_stmt)).scalars().all()
    if not result:
        logger.warning(
            f"user: '{user_id}' tried accessing view_active_members endpoint without authorization"
        )
        raise HTTPException(status_code=403, detail="restricted access")
    data = PaginatedMetadata[MembershipRes](
        items=[MembershipRes.model_validate(mem) for mem in result],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    response = StandardResponse(
        status="success", message="membership information", data=data
    )
    await cached(cache_key, response, ttl=3600)
    logger.info(f"{context} members data cached successfully for admin: %s", user_id)
    return response
