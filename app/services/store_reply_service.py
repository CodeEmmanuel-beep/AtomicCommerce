from app.logs.logger import get_logger
from app.api.v1.schemas import (
    ReplyResponse,
    PaginatedMetadata,
    PaginatedResponse,
    StandardResponse,
    ReactionsSummary,
)
from fastapi import HTTPException, status, Response
from app.models import Review, Reply, User, Store, React
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from app.utils.helper import react_summary
from app.utils.redis import (
    store_reply_invalidation,
    cache,
    cache_version,
    cached,
)

logger = get_logger("store_reply")


async def reply(reply, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at create reply endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = (
        select(Review)
        .options(
            selectinload(Review.store).selectinload(Store.user_owners),
            selectinload(Review.store).selectinload(Store.user_staffs),
        )
        .where(Review.store_id == reply.store_id, Review.id == reply.review_id)
    )
    rep = (await db.execute(stmt)).scalar_one_or_none()
    if not rep:
        logger.error("user %s, tried replying to a non-existent review", user_id)
        raise HTTPException(status_code=404, detail="review not found")
    auth_check = any(owner.id == user_id for owner in rep.store.user_owners) or any(
        staff.id == user_id for staff in rep.store.user_staffs
    )
    if not auth_check:
        logger.warning(
            "unauthorized attempt at create reply endpoint by user: %s", user_id
        )
        raise HTTPException(status_code=403, detail="restricted access")
    new_reply = Reply(
        user_id=user_id,
        store_id=reply.store_id,
        review_id=reply.review_id,
        reply_text=reply.reply_text,
    )
    try:
        rep.store_reply_count = Review.store_reply_count + 1
        db.add(new_reply)
        await db.commit()
        await store_reply_invalidation(reply.store_id)
    except IntegrityError:
        await db.rollback()
        logger.error("database error occurred while making reply user: %s", user_id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error occurred while making reply user: %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("reply successfully saved in database responder: %s", user_id)
    return {"message": "reply successfully posted"}


async def view_replies(store_id, review_id, page, limit, db):
    offset = (page - 1) * limit
    version = await cache_version(f"store_reply_key:{store_id}")
    cache_key = f"store_reply:v{version}:{store_id}:{review_id}:{page}:{limit}"
    reply_cache = await cache(cache_key)
    if reply_cache:
        logger.info("cache hit for store_id '%s', page: %s", store_id, page)
        return StandardResponse(**reply_cache)
    stmt = (
        select(Reply)
        .join(User, Reply.user_id == User.id)
        .join(Store, Reply.store_id == Store.id)
        .options(selectinload(Reply.user))
        .where(
            Reply.store_id == store_id,
            ~Store.is_deleted,
            Reply.review_id == review_id,
            User.is_active,
        )
        .order_by(Reply.time_of_post.desc())
    )
    total = (
        await db.execute(
            select(func.count(Reply.id))
            .join(User, Reply.user_id == User.id)
            .join(Store, Reply.store_id == Store.id)
            .where(
                Reply.store_id == store_id,
                ~Store.is_deleted,
                Reply.review_id == review_id,
                User.is_active,
            )
        )
    ).scalar() or 0
    logger.info("total reply found for review_id '%s' is %s", review_id, total)
    reply = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    if not reply:
        logger.info("review_id '%s' has no replies", review_id)
        return StandardResponse(
            status="success", message="no replies available", data=None
        )
    reply_ids = [rep.id for rep in reply]
    all_summaries = await react_summary(
        db, reply_ids, React.reply_id, Reply, Reply.store_id == store_id
    )
    items = []
    for rep in reply:
        rep_response = ReplyResponse.model_validate(rep)
        rep_response.reactions = all_summaries.get(rep.id, ReactionsSummary())
        items.append(rep_response)
    data = PaginatedMetadata[ReplyResponse](
        items=items,
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    response = {"data": data}
    full_response = StandardResponse(status="success", message="replies", data=response)
    await cached(cache_key, full_response, ttl=36000)
    logger.info("search for replies successfully returned data")
    return full_response


async def update(reply, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at edit reply endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Reply).where(
        Reply.user_id == user_id,
        Reply.store_id == reply.store_id,
        Reply.id == reply.id,
    )
    db_reply = (await db.execute(stmt)).scalar_one_or_none()
    if not db_reply:
        logger.error("user: %s, tried editing a non-existent reply", user_id)
        raise HTTPException(status_code=404, detail="reply not found")
    if db_reply.reply_text == reply.reply_text:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    db_reply.reply_text = reply.reply_text
    try:
        db_reply.edited = True
        await db.commit()
        await store_reply_invalidation(reply.store_id)
    except IntegrityError:
        await db.rollback()
        logger.error("database error occurred while editing reply user: %s", user_id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error occurred while editing reply user: %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("reply update by user '%s' successfully saved in database", user_id)
    return {"message": "reply successfully edited"}


async def delete_reply(reply, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at delete_reply endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = (
        select(Reply)
        .options(
            selectinload(Reply.review),
            selectinload(Reply.store).selectinload(Store.user_owners),
        )
        .where(
            Reply.store_id == reply.store_id,
            Reply.id == reply.id,
        )
    )
    db_reply = (await db.execute(stmt)).scalar_one_or_none()
    if not db_reply:
        logger.error("user: %s, tried deleting a non-existent reply", user_id)
        raise HTTPException(status_code=404, detail="reply not found")
    is_owner = any(owner.id == user_id for owner in db_reply.store.user_owners)
    if db_reply.user_id != user_id and not is_owner:
        logger.warning("Unauthorized delete attempt by user: %s", user_id)
        raise HTTPException(status_code=403, detail="restricted access")
    try:
        db_reply.review.store_reply_count = max(
            0, (db_reply.review.store_reply_count or 0) - 1
        )
        await db.delete(db_reply)
        await db.commit()
        await store_reply_invalidation(reply.store_id)
    except IntegrityError:
        await db.rollback()
        logger.error("database error occurred while deleting reply user: %s", user_id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error occurred while deleting reply user: %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("user '%s' successfully deleted their reply", user_id)
    return {"message": "deleted reply"}
