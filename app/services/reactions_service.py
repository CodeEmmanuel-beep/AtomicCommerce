from app.models import React, Review, Reply, ReactionType
from app.logs.logger import get_logger
from fastapi import HTTPException, status
from app.api.v1.schemas import StandardResponse
from datetime import timezone, datetime
from sqlalchemy import select
from app.utils.redis import (
    store_reply_invalidation,
    store_review_invalidation,
    product_reply_invalidation,
    product_review_invalidation,
)
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    try:
        reaction_enum = ReactionType(reaction_type)
    except ValueError:
        logger.warning(f"Invalid reaction type '{reaction_type}' by user {user_id}")
        raise HTTPException(status_code=400, detail="invalid reaction type")
    if (reply_id is None and review_id is None) or (
        reply_id is not None and review_id is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="must reaction to either review or reply",
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
            if existing.type == reaction_enum:
                await db.delete(existing)
                await db.flush()
                delete_message = "Reaction deleted"
                value = getattr(target, field_name) or 0
                setattr(target, field_name, max(value - 1, 0))
            else:
                existing.type = reaction_enum
                existing.time_of_reaction = datetime.now(timezone.utc)
        else:
            new_react = React(
                user_id=user_id,
                type=reaction_enum,
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
