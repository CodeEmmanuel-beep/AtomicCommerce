from app.models import React, Review, Reply, ReactionType
from app.logs.logger import get_logger
from fastapi import HTTPException, status
from app.api.v1.schemas import (
    StandardResponse,
    PaginatedMetadata,
    PaginatedResponse,
    ReactResponse,
)
from datetime import timezone, datetime
from sqlalchemy import select, or_, func
from app.utils.redis import (
    store_reply_invalidation,
    store_review_invalidation,
    product_reply_invalidation,
    product_review_invalidation,
)
from app.utils.redis import cache, cached
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

logger = get_logger("react")


async def react_type(
    reaction_type,
    reply_id,
    review_id,
    background_task,
    db,
    payload,
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Unauthorized reaction attempt")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        reaction_enum = ReactionType(reaction_type)
    except ValueError:
        logger.warning(f"Invalid reaction type '{reaction_type}' by user {user_id}")
        raise HTTPException(status_code=400, detail="invalid reaction type")
    if (reply_id is None and review_id is None) or (
        reply_id is not None and review_id is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="must react to either review or reply",
        )
    delete_message = None
    try:
        if review_id:
            target = (
                await db.execute(
                    select(Review)
                    .options(selectinload(Review.product))
                    .where(Review.id == review_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if not target:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="must react on an existing review",
                )
            base_filter = React.review_id == review_id
        if reply_id:
            target = (
                await db.execute(
                    select(Reply)
                    .options(selectinload(Reply.product))
                    .where(Reply.id == reply_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if not target:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="must react on an existing reply",
                )
            base_filter = React.reply_id == reply_id
        prefix = "product" if target.product else "store"
        suffix = (
            "review_reaction_count"
            if isinstance(target, Review)
            else "reply_reaction_count"
        )
        field_name = f"{prefix}_{suffix}"
        stmt = (
            select(React).where(React.user_id == user_id, base_filter).with_for_update()
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        product_id = target.product_id
        store_id = target.store_id
        if existing:
            if existing.reaction_type == reaction_enum:
                await db.delete(existing)
                await db.flush()
                delete_message = "Reaction deleted"
                value = getattr(target, field_name) or 0
                setattr(target, field_name, max(value - 1, 0))
            else:
                existing.reaction_type = reaction_enum
                existing.time_of_reaction = datetime.now(timezone.utc)
        else:
            new_react = React(
                user_id=user_id,
                reaction_type=reaction_enum,
                reply_id=reply_id,
                review_id=review_id,
                time_of_reaction=datetime.now(timezone.utc),
            )
            db.add(new_react)
            value = getattr(target, field_name) or 0
            setattr(target, field_name, value + 1)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error(f"User {user_id} failed to add new reaction")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(f"User {user_id} failed to add new reaction")
        raise HTTPException(status_code=500, detail="internal server error")
    if review_id:
        if field_name == "product_review_reaction_count":
            background_task.add_task(product_review_invalidation, product_id)
        elif field_name == "store_review_reaction_count":
            background_task.add_task(store_review_invalidation, store_id)
    if reply_id:
        if field_name == "product_reply_reaction_count":
            background_task.add_task(product_reply_invalidation, product_id)
        elif field_name == "store_reply_reaction_count":
            background_task.add_task(store_reply_invalidation, store_id)
    logger.info("User '%s' added new reaction", user_id)
    if delete_message:
        message = delete_message
    else:
        message = "Reaction added"
    return StandardResponse(status="success", message=message, data=reaction_enum)


async def view_reactions(review_id, reply_id, page, limit, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Unauthorized view reaction attempt")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if (review_id and reply_id) or (review_id is None and reply_id is None):
        raise HTTPException(
            status_code=409, detail="choose either review_id or reply_id"
        )
    offset = (page - 1) * limit
    cache_key = f"reactions_list:{user_id}:{review_id}:{reply_id}:{page}:{limit}"
    r_cache = await cache(cache_key)
    if r_cache:
        logger.info("cache hit at view_reactions endpoint for user '%s'", user_id)
        return StandardResponse(**r_cache)
    filters = []
    if review_id is not None:
        filters.append(React.review_id == review_id)
    if reply_id is not None:
        filters.append(React.reply_id == reply_id)
    stmt = (
        select(React)
        .options(selectinload(React.user))
        .where(*filters)
        .order_by(React.time_of_reaction.desc())
    )
    react_list = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    log_message = (
        "search for reaction of review" if review_id else "search for reaction of reply"
    )
    search_id = review_id if review_id else reply_id
    if not react_list:
        logger.warning("%s: %s, returned null", log_message, search_id)
        raise HTTPException(status_code=404, detail="not found")
    total = (
        await db.execute(select(func.count(React.id)).where(or_(*filters)))
    ).scalar() or 0
    total_log = (
        "total reactions for review_id" if review_id else "total reactions for reply_id"
    )
    logger.info("%s, '%s', is: %s", total_log, search_id, total)
    data = PaginatedMetadata[ReactResponse](
        items=[ReactResponse.model_validate(r_list) for r_list in react_list],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    full_response = StandardResponse(status="success", message="reactions", data=data)
    await cached(cache_key, full_response, ttl=30)
    logger.info(
        "view_reactions endpoint successfully returned data for user: %s", user_id
    )
    return full_response
