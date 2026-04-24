from app.api.v1.schemas import (
    CategoryResponse,
    PaginatedMetadata,
    StandardResponse,
)
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.verify_jwt import verify_token
from app.database.get import get_db
from app.services import category_service

router = APIRouter(prefix="/group", tags=["Category"])


@router.post("/create_category")
async def category(
    name: str, db: AsyncSession = Depends(get_db), payload: dict = Depends(verify_token)
):
    return await category_service.category(name=name, db=db, payload=payload)


@router.get(
    "/get_cart",
    response_model=StandardResponse[PaginatedMetadata[CategoryResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def retrieve(
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await category_service.retrieve(db=db, page=page, limit=limit)


@router.delete("/delete", response_model=StandardResponse)
async def delete_one(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await category_service.delete_one(
        category_id=category_id, db=db, payload=payload
    )
