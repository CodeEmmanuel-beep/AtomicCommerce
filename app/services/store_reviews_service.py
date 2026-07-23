from app.logs.logger import get_logger
from app.api.v1.schemas import (
    StoreReviewResponse,
    PaginatedMetadata,
    StandardResponse,
    PaginatedResponse,
    ReactionsSummary,
)
from app.models import Review, Store, Reply, React, User, Order, OrderStatus
from app.utils.helper import react_summary
from fastapi import HTTPException, Response, status
from sqlalchemy import select, func, exists
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from app.utils.redis import (
    store_review_invalidation,
    cache,
    cache_version,
    cached,
    store_invalidation_global,
)

logger = get_logger("store_reviews")


async def store_review(review, ratings, background_task, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at create_review endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    try:
        stmt = (
            select(
                Store,
                exists().where(
                    Order.user_id == user_id,
                    Order.store_id == review.store_id,
                    Order.status.in_((OrderStatus.processing, OrderStatus.delivered)),
                ),
                exists().where(
                    Review.user_id == user_id,
                    Review.store_id == review.store_id,
                    Review.product_id.is_(None),
                ),
            )
            .where(Store.id == review.store_id, Store.is_deleted.is_(False))
            .with_for_update(of=Store)
        )
        row = (await db.execute(stmt)).fetchone()
        if not row:
            logger.warning(
                "user %s, tried making a review for a store that is not on the shelf",
                user_id,
            )
            raise HTTPException(status_code=404, detail="store not found")
        target, patronage, limit = row
        if not patronage:
            logger.warning(
                "user %s, tried making a review for a store they have not patronized",
                user_id,
            )
            raise HTTPException(
                status_code=403,
                detail="can not make review for a store you have not patronized",
            )
        if limit:
            logger.error(
                "user: %s, tried posting two reviews on a particular store", user_id
            )
            raise HTTPException(
                status_code=400, detail="can not make more that one review per store"
            )
        new_review = Review(
            user_id=user_id,
            store_id=review.store_id,
            review_text=review.review_text,
            ratings=ratings,
        )
        db.add(new_review)
        current_avg = target.avg_rating or 0
        current_count = target.review_count or 0
        target.review_count = current_count + 1
        new_avg = (current_avg * current_count + ratings) / (current_count + 1)
        target.avg_rating = new_avg
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error occurred while making review user: %s", user_id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error occurred while making review user: %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("review successfully saved in database reviewer: %s", user_id)
    background_task.add_task(store_review_invalidation, review.store_id)
    background_task.add_task(store_invalidation_global)
    return StandardResponse(
        status="success", message="review generated successfully", data=None
    )


async def view_reviews(store_id, page, limit, db):
    offset = (page - 1) * limit
    version = await cache_version(f"store_review_key:{store_id}")
    cache_key = f"store_review:v{version}:{store_id}:{page}:{limit}"
    review_cache = await cache(cache_key)
    if review_cache:
        logger.info("cache hit for store_id '%s', page: %s", store_id, page)
        return StandardResponse(**review_cache)
    stmt = (
        select(Review)
        .join(User, Review.user_id == User.id)
        .join(Store, Review.store_id == Store.id)
        .options(
            selectinload(Review.user),
            selectinload(Review.replies).selectinload(Reply.user),
        )
        .where(
            Review.store_id == store_id,
            Review.product_id.is_(None),
            Store.is_deleted.is_(False),
            User.is_active.is_(True),
        )
        .order_by(Review.time_of_post.desc())
    )
    total = (
        await db.execute(
            select(func.count(Review.id))
            .join(User, Review.user_id == User.id)
            .join(Store, Store.id == Review.store_id)
            .where(
                Review.store_id == store_id,
                Review.product_id.is_(None),
                Store.is_deleted.is_(False),
                User.is_active.is_(True),
            )
        )
    ).scalar() or 0
    logger.info("total reviews for store %s, is: %s", store_id, total)
    review = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    if not review:
        logger.info("search for review returned an empty list")
        return StandardResponse(
            status="success", message="no reviews available", data=None
        )
    review_ids = [rev.id for rev in review]
    all_summaries = await react_summary(
        db, review_ids, React.review_id, Review, Review.store_id == store_id
    )
    items = []
    for rev in review:
        rev_response = StoreReviewResponse.model_validate(rev)
        rev_response.reactions = all_summaries.get(rev.id, ReactionsSummary())
        items.append(rev_response)
    data = PaginatedMetadata[StoreReviewResponse](
        items=items,
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    response = StandardResponse(status="success", message="reviews", data=data)
    await cached(cache_key, response, ttl=30)
    logger.info("search for reviews successfully returned data")
    return response


async def update_review(review, ratings, background_task, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at update review endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    try:
        stmt = (
            select(Review, Store)
            .join(Store, Review.store_id == Store.id)
            .where(
                Review.user_id == user_id,
                Store.is_deleted.is_(False),
                Review.product_id.is_(None),
                Review.id == review.id,
                Review.store_id == review.store_id,
            )
            .with_for_update(of=Store)
        )
        row = (await db.execute(stmt)).fetchone()
        if not row:
            logger.error("user %s, tried updating a non existent review", user_id)
            raise HTTPException(status_code=404, detail="review not found")
        db_review, target = row
        has_changed = False
        if (
            review.review_text is not None
            and db_review.review_text != review.review_text
        ):
            logger.info("user %s, is updating their review text", user_id)
            db_review.review_text = review.review_text
            has_changed = True
        if not has_changed and db_review.ratings == ratings:
            await db.rollback()
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        db_review.edited = True
        if db_review.ratings != ratings:
            former_rating = db_review.ratings
            db_review.ratings = ratings
            current_avg = target.avg_rating or 0
            current_count = target.review_count or 0
            if current_count > 0:
                new_avg = (
                    (current_avg * current_count) - former_rating + ratings
                ) / current_count
                target.avg_rating = max(0.0, new_avg)
            else:
                target.avg_rating = ratings or 0.0
                target.review_count = 1
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error occurred while editing review user: %s", user_id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error occurred while editing review user: %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    background_task.add_task(store_review_invalidation, review.store_id)
    background_task.add_task(store_invalidation_global)
    logger.info("review successfully saved in database reviewer: %s", user_id)
    return StandardResponse(
        status="success", message="review edited successfully", data=None
    )


async def delete_review(store_id, background_task, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at delete_review endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    try:
        stmt = (
            select(Review, Store)
            .join(Store, Review.store_id == Store.id)
            .where(
                Review.user_id == user_id,
                Review.store_id == store_id,
                Review.product_id.is_(None),
            )
            .with_for_update(of=Store)
        )
        row = (await db.execute(stmt)).fetchone()
        if not row:
            logger.error("user %s, tried deleting a non existent review", user_id)
            raise HTTPException(status_code=404, detail="review not found")
        review, store = row
        await db.delete(review)
        current_avg = store.avg_rating or 0
        current_count = store.review_count or 0
        new_total = max(0, (current_count or 0) - 1)
        if new_total > 0:
            new_avg = ((current_avg * current_count) - review.ratings) / new_total
            new_avg = max(0.0, new_avg)
            store.avg_rating = new_avg
            store.review_count = new_total
        else:
            store.avg_rating = 0.0
            store.review_count = 0
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error occurred while deleting review user: %s", user_id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error occurred while deleting review user: %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    background_task.add_task(store_review_invalidation, store_id)
    background_task.add_task(store_invalidation_global)
    logger.info("user '%s' review successfully deleted", user_id)
    return StandardResponse(status="success", message="review deleted", data=None)
