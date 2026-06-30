from app.logs.logger import get_logger
from app.api.v1.schemas import (
    ReplyResponse,
    PaginatedMetadata,
    PaginatedResponse,
    StandardResponse,
    ReactionsSummary,
)
from fastapi import HTTPException, Response, status
from app.models import (
    Review,
    Reply,
    Product,
    React,
    User,
    Store,
    Order,
    OrderItem,
    OrderStatus,
)
from sqlalchemy import select, func, exists, case
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from app.utils.redis import (
    product_reply_invalidation,
    product_review_invalidation,
    cache,
    cache_version,
    cached,
)
from app.utils.helper import react_summary

logger = get_logger("product_reply")


async def reply(reply, background_task, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at create reply endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    purchase_check_stmt = select(
        exists(
            select(1)
            .select_from(OrderItem)
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                OrderItem.product_id == reply.product_id,
                Order.user_id == user_id,
                Order.status.in_((OrderStatus.processing, OrderStatus.delivered)),
            )
        )
    )
    has_purchased = await db.scalar(purchase_check_stmt)
    if not has_purchased:
        logger.warning(
            "User %s tried to reply to a review for product %s without a valid purchase history",
            user_id,
            reply.product_id,
        )
        raise HTTPException(
            status_code=400,
            detail="you can only reply to reviews on purchased products",
        )
    try:
        stmt = (
            select(
                Review,
                exists().where(
                    Reply.user_id == user_id, Reply.review_id == reply.review_id
                ),
            )
            .join(Product, Review.product_id == Product.id)
            .where(
                Review.id == reply.review_id,
                Review.product_id == reply.product_id,
                Product.is_deleted.is_(False),
            )
            .with_for_update()
        )
        row = (await db.execute(stmt)).fetchone()
        if not row:
            logger.warning("user %s, tried replying to a non-existent review", user_id)
            raise HTTPException(status_code=404, detail="review not found")
        review_obj, reply_exist = row
        if reply_exist:
            logger.warning(
                "user: %s, tried replying to a review more than once, review: %s",
                user_id,
                reply.review_id,
            )
            raise HTTPException(status_code=400, detail="only one reply per review")
        new_reply = Reply(
            user_id=user_id,
            product_id=reply.product_id,
            review_id=reply.review_id,
            reply_text=reply.reply_text,
        )
        review_obj.product_reply_count += 1
        db.add(new_reply)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error occurred while making reply user: %s", user_id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error occurred while making reply user: %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    background_task.add_task(product_reply_invalidation, reply.product_id)
    background_task.add_task(product_review_invalidation, reply.product_id)
    logger.info("reply successfully saved in database responder: %s", user_id)
    return StandardResponse(
        status="success", message="reply successfully posted", data=None
    )


async def view_replies(product_id, review_id, page, limit, db):
    offset = (page - 1) * limit
    version = await cache_version(f"product_reply_key:{product_id}")
    cache_key = f"product_reply:v{version}:{product_id}:{review_id}:{page}:{limit}"
    reply_cache = await cache(cache_key)
    if reply_cache:
        logger.info("cache hit for product_id '%s', page: %s", product_id, page)
        return StandardResponse(**reply_cache)
    priority_case = case(
        (Store.user_owners.any(User.id == Reply.user_id), 2),
        (Store.user_staffs.any(User.id == Reply.user_id), 1),
        else_=0,
    ).desc()
    stmt = (
        select(Reply)
        .join(Product, Reply.product_id == Product.id)
        .join(User, Reply.user_id == User.id)
        .options(selectinload(Reply.user))
        .where(
            Reply.product_id == product_id,
            Product.is_deleted.is_(False),
            Reply.review_id == review_id,
            User.is_active.is_(True),
        )
        .order_by(
            priority_case,
            Reply.time_of_post.desc(),
        )
    )
    total = (
        await db.execute(
            select(func.count(func.distinct(Reply.id)))
            .join(Product, Reply.product_id == Product.id)
            .join(User, Reply.user_id == User.id)
            .where(
                Reply.product_id == product_id,
                Product.is_deleted.is_(False),
                Reply.review_id == review_id,
                User.is_active.is_(True),
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
        db, reply_ids, React.reply_id, Reply, Reply.product_id == product_id
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
    response = StandardResponse(status="success", message="replies", data=data)
    await cached(cache_key, response, ttl=30)
    logger.info("search for replies successfully returned data")
    return response


async def update(reply, background_task, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at edit reply endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    try:
        stmt = (
            select(Reply)
            .join(Product, Reply.product_id == Product.id)
            .where(
                Reply.user_id == user_id,
                Reply.product_id == reply.product_id,
                Reply.id == reply.id,
                Product.is_deleted.is_(False),
            )
            .with_for_update()
        )
        db_reply = (await db.execute(stmt)).scalar_one_or_none()
        if not db_reply:
            logger.error("user: %s, tried editing a non-existent reply", user_id)
            raise HTTPException(status_code=404, detail="reply not found")
        has_changed = False
        if reply.reply_text is not None and db_reply.reply_text != reply.reply_text:
            logger.info("user %s, is updating their reply text", user_id)
            db_reply.reply_text = reply.reply_text
            has_changed = True
        if not has_changed:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        db_reply.edited = True
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error occurred while editing reply user: %s", user_id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error occurred while editing reply user: %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    background_task.add_task(product_reply_invalidation, reply.product_id)
    background_task.add_task(product_review_invalidation, reply.product_id)
    logger.info("reply update by user '%s' successfully saved in database", user_id)
    return StandardResponse(
        status="success", message="reply successfully edited", data=None
    )


async def delete_reply(reply_id, review_id, background_task, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at delete_reply endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    product_id = None
    try:
        stmt = (
            select(Reply)
            .options(selectinload(Reply.review))
            .where(
                Reply.user_id == user_id,
                Reply.review_id == review_id,
                Reply.id == reply_id,
            )
            .with_for_update()
        )
        db_reply = (await db.execute(stmt)).scalar_one_or_none()
        if not db_reply:
            logger.error("user: %s, tried deleting a non-existent reply", user_id)
            raise HTTPException(status_code=404, detail="reply not found")
        product_id = db_reply.product_id
        db_reply.review.product_reply_count = max(
            0, (db_reply.review.product_reply_count or 0) - 1
        )
        await db.delete(db_reply)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error occurred while deleting reply user: %s", user_id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error occurred while deleting reply user: %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    background_task.add_task(product_reply_invalidation, product_id)
    background_task.add_task(product_review_invalidation, product_id)
    logger.info("user '%s' successfully deleted their reply", user_id)
    return StandardResponse(status="success", message="deleted reply", data=None)
