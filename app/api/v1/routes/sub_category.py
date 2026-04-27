from fastapi import Depends, APIRouter, Query
from app.auth.verify_jwt import verify_token
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db
from app.services import sub_category_service
from app.api.v1.schemas import StandardResponse, PaginatedMetadata, SubCategoryResponse


router = APIRouter(prefix="/sub_category", tags=["Sub Category"])


@router.post("create_sub_category")
async def create_a_sub_category(
    category_id: int,
    name: str,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await sub_category_service.sub_category(
        category_id=category_id, name=name, db=db, payload=payload
    )


@router.get(
    "/get_sub_category",
    response_model=StandardResponse[PaginatedMetadata[SubCategoryResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def sub_category_list(
    category_id: int | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await sub_category_service.retrieve(
        category_id=category_id, db=db, page=page, limit=limit
    )


@router.delete("/delete")
async def delete_one_sub_category(
    sub_category_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await sub_category_service.delete_sub_category(
        sub_category_id=sub_category_id, db=db, payload=payload
    )
