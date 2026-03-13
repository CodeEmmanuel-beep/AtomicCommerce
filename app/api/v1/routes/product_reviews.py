from fastapi import APIRouter, Depends, Query
from app.auth.verify_jwt import verify_token
from app.database.get import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.services import product_reviews_service
from app.api.v1.models import (
    ReviewResponse,
    Review,
    StandardResponse,
    PaginatedMetadata,
)


router = APIRouter(prefix="/reviews", tags=["Product_Reviews"])


@router.post("/post_review")
async def create_review(
    review: Review,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await product_reviews_service.product_review(
        review=review, db=db, payload=payload
    )


@router.get(
    "/view_reviews/{product_id}",
    response_model=StandardResponse[PaginatedMetadata[ReviewResponse]],
    response_model_exclude_defaults=True,
    response_model_exclude_none=True,
)
async def review_list(
    product_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await product_reviews_service.view_reviews(
        product_id=product_id, db=db, payload=payload, page=page, limit=limit
    )


@router.put("/edit_reviews")
async def reviews_update(
    review: Review,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await product_reviews_service.update(review=review, db=db, payload=payload)


@router.delete("/delete_reviews/{product_id}")
async def delete_one(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await product_reviews_service.delete_review(
        product_id=product_id, db=db, payload=payload
    )
