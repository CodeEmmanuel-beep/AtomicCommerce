from fastapi import APIRouter, Depends, Query
from app.auth.verify_jwt import verify_token
from app.database.get import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.services import product_reviews_service
from app.api.v1.schemas import (
    ProductReviewResponse,
    Review,
    StandardResponse,
    PaginatedMetadata,
)

router = APIRouter(prefix="/product_reviews", tags=["Product_Reviews"])


@router.post("/post_product_review")
async def create_product_review(
    review: Review,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await product_reviews_service.product_review(
        review=review, db=db, payload=payload
    )


@router.get(
    "/view_product_reviews/{product_id}",
    response_model=StandardResponse[PaginatedMetadata[ProductReviewResponse]],
    response_model_exclude_defaults=True,
    response_model_exclude_none=True,
)
async def product_review_list(
    product_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await product_reviews_service.view_reviews(
        product_id=product_id, db=db, page=page, limit=limit
    )


@router.put("/edit_product_review")
async def product_review_update(
    review: Review,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await product_reviews_service.update_review(
        review=review, db=db, payload=payload
    )


@router.delete("/product_review_delete/{product_id}")
async def delete_product_review(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await product_reviews_service.delete_review(
        product_id=product_id, db=db, payload=payload
    )
