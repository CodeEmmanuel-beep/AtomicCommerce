from fastapi import APIRouter, Depends, Query
from app.auth.verify_jwt import verify_token
from app.database.get import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.services import store_reviews_service
from app.api.v1.models import (
    ReviewResponse,
    Reviews,
    StandardResponse,
    PaginatedMetadata,
)


router = APIRouter(prefix="/reviews", tags=["Company_Reviews"])


@router.post("/post_review")
async def create_review(
    review: Reviews,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_reviews_service.store_review(
        review=review, db=db, payload=payload
    )


@router.get(
    "/view_reviews",
    response_model=StandardResponse[PaginatedMetadata[ReviewResponse]],
    response_model_exclude_defaults=True,
    response_model_exclude_none=True,
)
async def reviews_list(
    store_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await store_reviews_service.view_reviews(
        store_id=store_id, db=db, page=page, limit=limit
    )


@router.put("/edit_reviews")
async def reviews_update(
    review: Reviews,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_reviews_service.update(review=review, db=db, payload=payload)


@router.delete("/delete_reviews")
async def delete_one(
    store_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_reviews_service.delete_review(
        store_id=store_id, db=db, payload=payload
    )
