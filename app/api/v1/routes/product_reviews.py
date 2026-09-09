from fastapi import APIRouter, Request, Query, BackgroundTasks, Depends
from app.database.get import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.services import product_reviews_service
from app.api.v1.schemas import (
    ProductReviewResponse,
    Review,
    StandardResponse,
    PaginatedMetadata,
)
from typing import Annotated

router = APIRouter(prefix="/product_reviews", tags=["Product_Reviews"])

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/post_product_review",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def create_product_review(
    request: Request,
    review: Review,
    db: DatabaseDep,
    background_task: BackgroundTasks,
    ratings: int = Query(0, ge=1, le=5),
):
    return await product_reviews_service.product_review(
        review=review,
        background_task=background_task,
        ratings=ratings,
        db=db,
        request=request,
    )


@router.get(
    "/view_product_reviews/{product_id}",
    response_model=StandardResponse[PaginatedMetadata[ProductReviewResponse]],
    response_model_exclude_defaults=True,
    response_model_exclude_none=True,
)
async def product_review_list(
    product_id: int,
    db: DatabaseDep,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await product_reviews_service.view_reviews(
        product_id=product_id, db=db, page=page, limit=limit
    )


@router.put(
    "/edit_product_review",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def product_review_update(
    request: Request,
    review: Review,
    background_task: BackgroundTasks,
    db: DatabaseDep,
    ratings: int = Query(0, ge=1, le=5),
):
    return await product_reviews_service.update_review(
        review=review,
        ratings=ratings,
        background_task=background_task,
        db=db,
        request=request,
    )


@router.delete(
    "/product_review_delete/{store_id}/{product_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_product_review(
    request: Request,
    store_id: int,
    product_id: int,
    background_task: BackgroundTasks,
    db: DatabaseDep,
):
    return await product_reviews_service.delete_review(
        store_id=store_id,
        product_id=product_id,
        background_task=background_task,
        db=db,
        request=request,
    )
