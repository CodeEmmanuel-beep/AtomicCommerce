from fastapi import APIRouter, Depends, Query, UploadFile, File, BackgroundTasks
from app.database.get import get_db
from app.auth.verify_jwt import verify_token
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.models import (
    PaginatedMetadata,
    ProductResponse,
    StandardResponse,
    ProductObj,
)
from app.services import product_service
from app.utils.supabase_url import _supabase


router = APIRouter(prefix="/product", tags=["Products"])


@router.post("add_product")
async def create_product(
    prod: ProductObj,
    primary_image: UploadFile = File(...),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
    get_supabase=Depends(_supabase),
):
    return await product_service.create(
        prod=prod,
        primary_image=primary_image,
        image=image,
        db=db,
        payload=payload,
        get_supabase=get_supabase,
    )


@router.put("/edit_product")
async def product_change(
    prod: ProductObj,
    primary_image: UploadFile = File(...),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
    get_supabse=Depends(_supabase),
):
    return await product_service.product_change(
        prod=prod,
        primary_image=primary_image,
        image=image,
        db=db,
        payload=payload,
        get_supabase=get_supabse,
    )


@router.get(
    "/list",
    response_model=StandardResponse[PaginatedMetadata[ProductResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def list_products(
    seed: float = 0.5,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
):
    return await product_service.list_products(seed=seed, db=db, page=page, limit=limit)


@router.get(
    "/search_products",
    response_model=StandardResponse[PaginatedMetadata[ProductResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def list_one(
    product_name: str,
    category: str,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await product_service.search_product(
        product_name=product_name, category=category, page=page, limit=limit, db=db
    )


@router.delete("/delete/{store_id}/{product_id}", response_model=StandardResponse)
async def delete_product(
    store_id: int,
    product_id: int,
    background_task: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
    get_supabase=Depends(_supabase),
):
    return await product_service.delete_one(
        store_id=store_id,
        product_id=product_id,
        background_task=background_task,
        db=db,
        payload=payload,
        get_supabase=get_supabase,
    )
