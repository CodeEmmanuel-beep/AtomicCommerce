from app.logs.logger import get_logger
from app.api.v1.schemas import (
    StoreReviewResponse,
    PaginatedMetadata,
    StandardResponse,
    PaginatedResponse,
    ReactionsSummary,
)
from app.models import Review, Store, Reply
from app.utils.helper import react_summary
from fastapi import HTTPException, Response, status
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from app.utils.redis import store_review_invalidation, cache, cache_version, cached

logger = get_logger("store_reviews")


async def store_review(review, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at create_review endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Review).where(
        Review.user_id == user_id, Review.store_id == review.store_id
    )
    limit = (await db.execute(stmt)).scalar()
    if limit:
        logger.error(
            "user: %s, tried posting two reviews on a particular store", user_id
        )
        raise HTTPException(
            status_code=400, detail="can not make more that one review per store"
        )
    target = await db.get(Store, review.store_id)
    if not target or target.is_deleted:
        logger.error(
            "user %s, tried making a review for a store that is not on the platform",
            user_id,
        )
        raise HTTPException(status_code=404, detail="store not found")
    if not (1 <= review.ratings <= 5):
        logger.error(
            "user %s, tried inputing an invalid value for review ratings", user_id
        )
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")
    new_review = Review(
        user_id=user_id,
        store_id=review.store_id,
        review_text=review.review_text,
        ratings=review.ratings,
    )
    try:
        db.add(new_review)
        await db.commit()
        await store_review_invalidation()
    except IntegrityError:
        await db.rollback()
        logger.error("database error occured while making review user: %s", user_id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error occured while making review user: %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("review successfully saved in database reviewer: %s", user_id)
    return {"message": "review generated successfully"}


async def view_reviews(store_id, page, limit, db):
    offset = (page - 1) * limit
    version = await cache_version("store_review_key")
    cache_key = f"store_review:v{version}:{store_id}:{page}:{limit}"
    review_cache = await cache(cache_key)
    if review_cache:
        logger.info("cache hit for store_id '%s', page: %s", store_id, page)
        return StandardResponse(**review_cache)
    stmt = (
        select(Review)
        .join(Store)
        .options(
            selectinload(Review.user),
            selectinload(Review.reply).selectinload(Reply.user),
        )
        .where(Review.store_id == store_id, ~Store.is_deleted)
        .order_by(Review.date_of_review.desc())
    )
    total = (
        await db.execute(
            select(func.count(Review.id))
            .join(Store, Store.id == Review.store_id)
            .where(Review.store_id == store_id, ~Store.is_deleted)
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
    all__summaries = await react_summary(
        db, review_ids, Review.id, Review, Review.store_id == store_id
    )
    items = []
    for rev in review:
        rev_response = StoreReviewResponse.model_validate(rev)
        rev_response.reactions = all__summaries.get(rev.id, ReactionsSummary())
        items.append(rev_response)
    data = PaginatedMetadata[StoreReviewResponse](
        items=items,
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    response = StandardResponse(status="success", message="reviews", data=data)
    await cached(cache_key, response, ttl=36000)
    logger.info("search for reviews successfully returned data")
    return response


async def update(review, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at update review endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Review).where(
        Review.user_id == user_id,
        Review.id == review.id,
        Review.store_id == review.store_id,
    )
    db_review = (await db.execute(stmt)).scalar_one_or_none()
    if not db_review:
        logger.error("user %s, tried updating a non existent review", user_id)
        raise HTTPException(status_code=404, detail="review not found")
    has_changed = False
    if review.review_text is not None and db_review.review_text != review.review_text:
        logger.info("user %s, is updating their review text", user_id)
        db_review.review_text = review.review_text
        has_changed = True
    if review.ratings is not None and db_review.ratings != review.ratings:
        logger.info("user %s, is updating their review ratings", user_id)
        db_review.ratings = review.ratings
        has_changed = True
    if not has_changed:
        return Response(status.HTTP_204_NO_CONTENT)
    try:
        db_review.edited = True
        await db.commit()
        await store_review_invalidation()
    except IntegrityError:
        await db.rollback()
        logger.error("database error occured while editing review user: %s", user_id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error occured while editing review user: %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("review successfully saved in database reviewer: %s", user_id)
    return {"message": "review edited successfully"}


async def delete_review(store_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at delete_review endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Review).where(
        Review.user_id == user_id,
        Review.store_id == store_id,
    )
    review = (await db.execute(stmt)).scalar_one_or_none()
    if not review:
        logger.error("user %s, tried deleting a non existent review", user_id)
        raise HTTPException(status_code=404, detail="review not found")
    try:
        await db.delete(review)
        await db.commit()
        await store_review_invalidation()
    except IntegrityError:
        await db.rollback()
        logger.error("database error occured while deleting review user: %s", user_id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error occured while deleting review user: %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("user '%s' review successfully deleted", user_id)
    return {"message": "review deleted"}
