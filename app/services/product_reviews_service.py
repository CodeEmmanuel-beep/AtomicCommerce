from app.logs.logger import get_logger
from app.api.v1.models import (
    ReviewResponse,
    PaginatedMetadata,
    StandardResponse,
    PaginatedResponse,
)
from app.models_sql import Review, Product, Reply
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
import asyncio
from app.utils.redis import cache, cache_version, cached, product_review_invalidation

logger = get_logger("product_reviews")


async def product_review(review, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt to access product_review endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Review).where(
        Review.user_id == user_id, Review.product_id == review.product_id
    )
    limit = (await db.execute(stmt)).scalar()
    if limit:
        logger.warning(
            "user %s, tried posting more than one review for a product", user_id
        )
        raise HTTPException(
            status_code=400, detail="can not make more that one review per product"
        )
    target = await db.get(Product, review.product_id)
    if not target:
        logger.error(
            "user %s, tried making a review for a product taht is not on the shelf",
            user_id,
        )
        raise HTTPException(status_code=404, detail="product not found")
    if not (1 <= review.ratings <= 5):
        logger.error("user %s, tried inputing an invalid value for review ratings")
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")
    new_review = Review(
        user_id=user_id,
        product_id=review.product_id,
        review_text=review.review_text,
        ratings=review.ratings,
    )
    try:
        db.add(new_review)
        await db.commit()
        await product_review_invalidation("product_review_key")
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error occured while making review user: %s", user_id)
        raise HTTPException(status_code=400, detail="databaase error")
    except Exception:
        await db.rollback()
        logger.exception("error occured while making review user: %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("review successfully saved in database reviewer: %s", user_id)
    return {"message": "review generated successfully"}


async def view_reviews(product_id, page, limit, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt to access view_reviews endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    offset = (page - 1) * limit
    version = await cache_version("product_review_key")
    cache_key = f"product_review:v{version}:{product_id}:{page}:{limit}"
    review_cache = await cache(cache_key)
    if review_cache:
        logger.info("cache hit for product_id '%s', page: %s", product_id, page)
        return StandardResponse(**review_cache)
    stmt = (
        select(Review)
        .options(
            selectinload(Review.user),
            selectinload(Review.reply).selectinload(Reply.user),
        )
        .where(Review.product_id == product_id)
        .order_by(Review.date_of_review.desc())
    )
    total_review_gather, review_gather = await asyncio.gather(
        db.execute(
            select(func.count(Review.id)).where(Review.product_id == product_id)
        ),
        db.execute(stmt.offset(offset).limit(limit)),
    )
    total_review = total_review_gather.scalar() or 0
    review = review_gather.scalars().all()
    if not review:
        logger.info("search for review returned an empty list")
        return StandardResponse(
            status="success", message="no reviews available", data=None
        )
    logger.info("total reviews for product %s, is: %s", product_id, total_review)
    data = PaginatedMetadata[ReviewResponse](
        items=[ReviewResponse.model_validate(rev) for rev in review],
        pagination=PaginatedResponse(page=page, limit=limit, total=total_review),
    )
    response = StandardResponse(status="success", message="reviews", data=data)
    await cached(cache_key, response, ttl=36000)
    logger.info("search for reviews successfully returned data")
    return response


async def update(review, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt to access update_review endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Review).where(
        Review.user_id == user_id,
        Review.product_id == review.product_id,
        Review.id == review.id,
    )
    reviews = (await db.execute(stmt)).scalar_one_or_none()
    if not reviews:
        logger.error("user %s, tried updating a non existent review", user_id)
        raise HTTPException(status_code=404, detail="review not found")
    if review.review_text is not None:
        logger.info("user %s, us updating his review text", user_id)
        reviews.review_text = review.review_text
    if review.ratings is not None:
        logger.info("user %s, us updating his review ratings", user_id)
        reviews.ratings = review.ratings
    try:
        reviews.edited = True
        await db.commit()
        await product_review_invalidation("product_review_key")
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error occured while editing review user: %s", user_id)
        raise HTTPException(status_code=400, detail="databaase error")
    except Exception:
        await db.rollback()
        logger.exception("error occured while editing review user: %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("user %s, successfully updated his review", user_id)
    return {"message": "review edited successfully"}


async def delete_review(product_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt to access delete_review endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Review).where(
        Review.user_id == user_id,
        Review.product_id == product_id,
    )
    review = (await db.execute(stmt)).scalar_one_or_none()
    if not review:
        logger.error("user %s, tried deleting a non existent review", user_id)
        raise HTTPException(status_code=404, detail="review not found")
    try:
        await db.delete(review)
        await db.commit()
        await product_review_invalidation("product_review_key")
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error occured while deleting review user: %s", user_id)
        raise HTTPException(status_code=400, detail="databaase error")
    except Exception:
        await db.rollback()
        logger.exception("error occured while deleting review user: %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("user %s, successfully deleted his review", user_id)
    return {"message": "review deleted"}
