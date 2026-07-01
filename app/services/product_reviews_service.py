from app.logs.logger import get_logger
from app.api.v1.schemas import (
    ProductReviewResponse,
    PaginatedMetadata,
    StandardResponse,
    PaginatedResponse,
    ReactionsSummary,
)
from app.models import Review, Product, React, User, OrderItem, OrderStatus, Order
from fastapi import HTTPException, status, Response
from sqlalchemy import select, func, exists, update
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from app.utils.helper import react_summary
from app.utils.redis import (
    cache,
    cache_version,
    cached,
    product_review_invalidation,
    product_invalidation,
)

logger = get_logger("product_reviews")


async def product_review(review, background_task, ratings, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt to access product_review endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    purchase_check_stmt = select(
        exists(
            select(1)
            .select_from(OrderItem)
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                OrderItem.product_id == review.product_id,
                Order.user_id == user_id,
                Order.status.in_((OrderStatus.processing, OrderStatus.delivered)),
            )
        )
    )
    has_purchased = await db.scalar(purchase_check_stmt)
    if not has_purchased:
        logger.warning(
            "User %s tried to review product %s without a valid purchase history",
            user_id,
            review.product_id,
        )
        raise HTTPException(
            status_code=400, detail="you can only make reviews on purchased products"
        )
    try:
        stmt = (
            select(
                Product,
                exists().where(
                    Review.user_id == user_id, Review.product_id == review.product_id
                ),
            )
            .where(Product.id == review.product_id, Product.is_deleted.is_(False))
            .with_for_update(of=Product)
        )
        row = (await db.execute(stmt)).fetchone()
        if not row:
            logger.warning(
                "user %s, tried making a review for a product that is not on the shelf",
                user_id,
            )
            raise HTTPException(status_code=404, detail="product not found")
        target, limit = row
        if limit:
            logger.warning(
                "user '%s' tried posting more than one review for a product", user_id
            )
            raise HTTPException(
                status_code=400, detail="can not make more that one review per product"
            )
        new_review = Review(
            user_id=user_id,
            product_id=review.product_id,
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
    background_task.add_task(product_review_invalidation, review.product_id)
    background_task.add_task(product_invalidation)
    return StandardResponse(
        status="success", message="review generated successfully", data=None
    )


async def view_reviews(product_id, page, limit, db):
    offset = (page - 1) * limit
    version = await cache_version(f"product_review_key:{product_id}")
    cache_key = f"product_review:v{version}:{product_id}:{page}:{limit}"
    review_cache = await cache(cache_key)
    if review_cache:
        logger.info("cache hit for product_id '%s', page: %s", product_id, page)
        return StandardResponse(**review_cache)
    stmt = (
        select(Review)
        .join(User, Review.user_id == User.id)
        .join(Product, Review.product_id == Product.id)
        .options(selectinload(Review.user))
        .where(
            Review.product_id == product_id,
            Product.is_deleted.is_(False),
            User.is_active.is_(True),
        )
        .order_by(Review.time_of_post.desc())
    )
    total = (
        await db.execute(
            select(func.count(Review.id))
            .join(User, Review.user_id == User.id)
            .join(Product, Review.product_id == Product.id)
            .where(
                Review.product_id == product_id,
                Product.is_deleted.is_(False),
                User.is_active.is_(True),
            )
        )
    ).scalar() or 0
    review = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    if not review:
        logger.info("search for review returned an empty list")
        return StandardResponse(
            status="success", message="no reviews available", data=None
        )
    logger.info("total reviews for product %s, is: %s", product_id, total)
    review_ids = [rev.id for rev in review]
    all__summaries = await react_summary(
        db, review_ids, React.review_id, Review, Review.product_id == product_id
    )
    items = []
    for rev in review:
        rev_response = ProductReviewResponse.model_validate(rev)
        rev_response.reactions = all__summaries.get(rev.id, ReactionsSummary())
        items.append(rev_response)
    data = PaginatedMetadata[ProductReviewResponse](
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
        logger.warning("unauthorized attempt to access update_review endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    try:
        stmt = (
            select(Review, Product)
            .join(Product, Review.product_id == Product.id)
            .where(
                Review.user_id == user_id,
                Review.product_id == review.product_id,
                Review.id == review.id,
                Product.is_deleted.is_(False),
            )
            .with_for_update(of=Product)
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
    logger.info("user '%s' successfully updated his review", user_id)
    background_task.add_task(product_review_invalidation, review.product_id)
    background_task.add_task(product_invalidation)
    return StandardResponse(
        status="success", message="review edited successfully", data=None
    )


async def delete_review(product_id, background_task, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt to access delete_review endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    try:
        stmt = (
            select(Review, Product)
            .join(Product, Review.product_id == Product.id)
            .where(
                Review.user_id == user_id,
                Review.product_id == product_id,
            )
            .with_for_update(of=Product)
        )
        row = (await db.execute(stmt)).first()
        if not row:
            logger.error("user %s, tried deleting a non existent review", user_id)
            raise HTTPException(status_code=404, detail="review not found")
        review, product = row
        current_avg = product.avg_rating or 0
        current_count = product.review_count or 0
        await db.delete(review)
        new_total = max(0, (current_count or 0) - 1)
        if new_total > 0:
            new_avg = ((current_avg * current_count) - review.ratings) / new_total
            new_avg = max(0.0, new_avg)
        else:
            new_avg = 0.0
        await db.execute(
            update(Product)
            .where(Product.id == product_id)
            .values(avg_rating=new_avg, review_count=new_total)
        )
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
    logger.info("user %s, successfully deleted his review", user_id)
    background_task.add_task(product_review_invalidation, product_id)
    background_task.add_task(product_invalidation)
    return StandardResponse(status="success", message="review deleted", data=None)
