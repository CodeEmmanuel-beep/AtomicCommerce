from fastapi import APIRouter, Depends, Query, BackgroundTasks
from app.auth.verify_jwt import verify_token
from app.database.get import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.services import store_reviews_service
from app.api.v1.schemas import (
    StoreReviewResponse,
    Review,
    StandardResponse,
    PaginatedMetadata,
)

router = APIRouter(prefix="/store_reviews", tags=["Store_Reviews"])


@router.post(
    "/post_store_review",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def create_store_review(
    review: Review,
    background_task: BackgroundTasks,
    ratings: int = Query(0, le=5),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_reviews_service.store_review(
        review=review,
        background_task=background_task,
        ratings=ratings,
        db=db,
        payload=payload,
    )


@router.get(
    "/view_store_reviews",
    response_model=StandardResponse[PaginatedMetadata[StoreReviewResponse]],
    response_model_exclude_defaults=True,
    response_model_exclude_none=True,
)
async def store_review_list(
    store_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await store_reviews_service.view_reviews(
        store_id=store_id, db=db, page=page, limit=limit
    )


@router.put(
    "/edit_store_review",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def store_reviews_update(
    review: Review,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_reviews_service.update_review(
        review=review, db=db, payload=payload
    )


@router.delete(
    "/store_review_delete",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_store_review(
    store_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_reviews_service.delete_review(
        store_id=store_id, db=db, payload=payload
    )
