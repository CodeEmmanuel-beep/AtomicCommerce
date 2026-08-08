from app.api.v1.schemas import (
    CategoryResponse,
    PaginatedMetadata,
    StandardResponse,
)
from typing import Annotated
from fastapi import APIRouter, Query, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db
from app.services import category_service

router = APIRouter(prefix="/category", tags=["Category"])

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/create_category",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def create_a_category(name: str, request: Request, db: DatabaseDep):
    return await category_service.category(name=name, request=request, db=db)


@router.get(
    "/get_category",
    response_model=StandardResponse[PaginatedMetadata[CategoryResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def category_list(
    db: DatabaseDep,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await category_service.retrieve(db=db, page=page, limit=limit)


@router.delete("/delete")
async def delete_one_category(category_id: int, request: Request, db: DatabaseDep):
    return await category_service.delete_category(
        category_id=category_id, request=request, db=db
    )
