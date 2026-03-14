from app.logs.logger import get_logger
from app.api.v1.models import (
    ReplyResponse,
    PaginatedMetadata,
    PaginatedResponse,
    StandardResponse,
)
from fastapi import HTTPException
from app.models_sql import Review, Reply, User
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from app.utils.redis import (
    product_reply_invalidation,
    product_review_invalidation,
    cache,
    cache_version,
    cached,
)
import asyncio

logger = get_logger("product_reply")


async def reply(reply, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at create reply endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Review).where(
        Review.product_id == reply.product_id, Review.id == reply.review_id
    )
    rep = (await db.execute(stmt)).scalar_one_or_none()
    if not rep:
        logger.error("user %s, tried replying to a non-existent review", user_id)
        raise HTTPException(status_code=404, detail="review not found")
    new_reply = Reply(
        user_id=user_id,
        product_id=reply.product_id,
        review_id=reply.review_id,
        reply_text=reply.reply_text,
    )
    try:
        rep.reply_count = (rep.reply_count or 0) + 1
        db.add(new_reply)
        await db.commit()
        await asyncio.gather(
            product_reply_invalidation(), product_review_invalidation()
        )
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error occured while making reply user: %s", user_id)
        raise HTTPException(status_code=400, detail="databaase error")
    except Exception:
        await db.rollback()
        logger.exception("error occured while making reply user: %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("reply successfully saved in database reviewer: %s", user_id)
    return {"messsage": "reply successfully posted"}


async def view_replies(product_id, review_id, page, limit, db):
    offset = (page - 1) * limit
    version = await cache_version("product_reply_key")
    cache_key = f"product_reply:v{version}:{product_id}:{review_id}:{page}:{limit}"
    reply_cache = await cache(cache_key)
    if reply_cache:
        logger.info("cache hit for product_id '%s', page: %s", product_id, page)
        return StandardResponse(**reply_cache)
    stmt = (
        select(Reply)
        .join(Reply.user)
        .options(selectinload(Reply.user))
        .where(Reply.product_id == product_id, Reply.review_id == review_id)
        .order_by(
            or_(
                User.role == "Admin", User.role == "Owner", User.role == "customer_care"
            ).desc(),
            Reply.time_of_post.desc(),
        )
    )
    total_gather, reply_gather = await asyncio.gather(
        db.execute(
            select(func.count(Reply.id)).where(
                Reply.product_id == product_id, Reply.review_id == review_id
            )
        ),
        db.execute(stmt.offset(offset).limit(limit)),
    )
    total = total_gather.scalar() or 0
    logger.info("total reply found for review_id '%s' is %s", review_id, total)
    reply = reply_gather.scalars().all()
    if not reply:
        logger.info("review_id '%s' has no replies", review_id)
        return StandardResponse(
            status="success", message="no replies available", data=None
        )
    data = PaginatedMetadata[ReplyResponse](
        items=[ReplyResponse.model_validate(rep) for rep in reply],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    response = StandardResponse(status="success", message="reviews", data=data)
    await cached(cache_key, response, ttl=36000)
    logger.info("search for replies successfully returned data")
    return response


async def update(reply, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at edit reply endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Reply).where(
        Reply.user_id == user_id,
        Reply.product_id == reply.product_id,
        Reply.id == reply.id,
    )
    db_reply = (await db.execute(stmt)).scalar_one_or_none()
    if not db_reply:
        logger.error("user: %s, tried editing a non-existent reply", user_id)
        raise HTTPException(status_code=404, detail="reply not found")
    db_reply.reply_text = reply.reply_text
    try:
        db_reply.edited = True
        await db.commit()
        await asyncio.gather(
            product_reply_invalidation(), product_review_invalidation()
        )
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error occured while editing reply user: %s", user_id)
        raise HTTPException(status_code=400, detail="databaase error")
    except Exception:
        await db.rollback()
        logger.exception("error occured while editing reply user: %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("reply update by user '%s' successfully saved in database", user_id)
    return {"messsage": "reply successfully edited"}


async def delete_reply(reply, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at delete_reply endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = (
        select(Reply)
        .options(selectinload(Reply.review))
        .where(
            Reply.user_id == user_id,
            Reply.product_id == reply.product_id,
            Reply.id == reply.id,
        )
    )
    db_reply = (await db.execute(stmt)).scalar_one_or_none()
    if not db_reply:
        logger.error("user: %s, tried deleting a non-existent reply", user_id)
        raise HTTPException(status_code=404, detail="reply not found")
    try:
        await db.delete(db_reply)
        db_reply.review.reply_count = max(0, (db_reply.review.reply_count or 1) - 1)
        await db.commit()
        await asyncio.gather(
            product_reply_invalidation(), product_review_invalidation()
        )
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error occured while deleting reply user: %s", user_id)
        raise HTTPException(status_code=400, detail="databaase error")
    except Exception:
        await db.rollback()
        logger.exception("error occured while deleting reply user: %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("user '%s' successfully deleted their reply", user_id)
    return {"message": "deleted reply"}
