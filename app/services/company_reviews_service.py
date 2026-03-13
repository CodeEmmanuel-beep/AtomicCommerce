from app.logs.logger import get_logger
from app.api.v1.models import (
    ReviewResponse,
    PaginatedMetadata,
    StandardResponse,
    PaginatedResponse,
    ReplyResponse,
)
from app.models_sql import Review
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError


logger = get_logger("company_reviews")


async def company_review(review, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Review).where(Review.user_id == user_id)
    limit = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar() or 0
    if limit == 1:
        raise HTTPException(
            status_code=400, detail="can not make more that one review per product"
        )
    new_review = Review(
        user_id=user_id,
        review_text=review.review_text,
        ratings=review.ratings,
    )
    try:
        db.add(new_review)
        await db.commit()
        await db.refresh(new_review)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=500, detail="internal server error")
    return {"message": "review generated successfully"}


async def view_reviews(page, limit, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="not a registered user")
    offset = (page - 1) * limit
    stmt = select(Review).options(selectinload(Review.replies))
    subq=stmt.subquery()
    total = (
        await db.execute(select(func.count()).select_from(subq))
    ).scalar() or 0
    review = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    if not review:
        raise HTTPException(status_code=404, detail="no reviews available")
    stmt = select(Review).options(selectinload(Review.replies))
    total = (
        await db.execute(select(func.count()).select_from(subq))
    ).scalar() or 0
    reply = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    items = []
    for rev in review:
        review_data = ReviewResponse.model_validate(rev)
        review_data.reply = [ReplyResponse.model_validate(rep) for rep in reply]
        items.append(review_data)
    data = PaginatedMetadata[ReviewResponse](
        items=items, pagination=PaginatedResponse(page=page, limit=limit, total=total)
    )
    return StandardResponse(status="success", message="reviews", data=data)


async def update(review, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Review).where(Review.user_id == user_id, Review.id == review.id)
    reviews = (await db.execute(stmt)).scalars().all()
    if not reviews:
        raise HTTPException(status_code=404, detail="review not found")
    if review.review_text is not None:
        reviews.review_text = review.review_text
    if review.ratings is not None:
        reviews.ratings = review.ratings
    try:
        review.edited = True
        await db.commit()
        await db.refresh(reviews)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=500, detail="internal server error")
    return {"message": "review edited successfully"}


async def delete_review(review, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Review).where(Review.user_id == user_id, Review.id == review.id)
    review = (await db.execute(stmt)).scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="revie not found")
    try:
        await db.delete(review)
        await db.commit()
        await db.refresh(review)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=500, detail="internal server error")
    return {"message": "deleted review"}
