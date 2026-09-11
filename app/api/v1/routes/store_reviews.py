from fastapi import APIRouter, Request, Query, BackgroundTasks, Depends
from app.database.get import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.services import store_reviews_service
from app.api.v1.schemas import (
    StoreReviewResponse,
    Review,
    StandardResponse,
    PaginatedMetadata,
)
from typing import Annotated

router = APIRouter(prefix="/store_reviews", tags=["Store_Reviews"])

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/post_store_review",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def create_store_review(
    request: Request,
    review: Review,
    db: DatabaseDep,
    background_task: BackgroundTasks,
    ratings: int = Query(1, ge=1, le=5),
):
    return await store_reviews_service.store_review(
        review=review,
        background_task=background_task,
        ratings=ratings,
        db=db,
        request=request,
    )


@router.get(
    "/view_store_reviews",
    response_model=StandardResponse[PaginatedMetadata[StoreReviewResponse]],
    response_model_exclude_defaults=True,
    response_model_exclude_none=True,
)
async def store_review_list(
    store_id: int,
    db: DatabaseDep,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
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
    request: Request,
    review: Review,
    background_task: BackgroundTasks,
    db: DatabaseDep,
    ratings: int = Query(None, ge=1, le=5),
):
    return await store_reviews_service.update_review(
        review=review,
        background_task=background_task,
        ratings=ratings,
        db=db,
        request=request,
    )


@router.delete(
    "/store_review_delete",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_store_review(
    request: Request, store_id: int, background_task: BackgroundTasks, db: DatabaseDep
):
    return await store_reviews_service.delete_review(
        store_id=store_id, background_task=background_task, db=db, request=request
    )
