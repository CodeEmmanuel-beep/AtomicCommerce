from fastapi import APIRouter, Depends, Query, UploadFile, File, BackgroundTasks, Form
from app.database.get import get_db
from app.auth.verify_jwt import verify_token
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.schemas import (
    PaginatedMetadata,
    ProductResponse,
    StandardResponse,
)
from app.services import product_service
from app.utils.supabase_url import _supabase
from typing import List, Optional

router = APIRouter(prefix="/product", tags=["Products"])


@router.post("/add_product")
async def create_product(
    store_id: int = Form(...),
    sub_category_name: str = Form(...),
    primary_image: UploadFile = File(...),
    product_name: str = Form(...),
    product_type: str = Form(...),
    product_size: str = Query(
        "small", enum=["small", "medium", "large", "extra_large"]
    ),
    product_price: float = Form(...),
    product_description: str = Form(...),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
    get_supabase=Depends(_supabase),
):
    return await product_service.create(
        primary_image=primary_image,
        store_id=store_id,
        sub_category_name=sub_category_name,
        product_name=product_name,
        product_type=product_type,
        product_size=product_size,
        product_price=product_price,
        product_description=product_description,
        db=db,
        payload=payload,
        get_supabase=get_supabase,
    )


@router.post("/product_images")
async def upload_product_images(
    store_id: int = Form(...),
    product_id: int = Form(...),
    image_1: UploadFile = File(...),
    image_2: UploadFile = File(None),
    image_3: UploadFile = File(None),
    image_4: UploadFile = File(None),
    image_5: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
    get_supabase=Depends(_supabase),
):
    return await product_service.add_image(
        image_1=image_1,
        store_id=store_id,
        product_id=product_id,
        image_2=image_2,
        image_3=image_3,
        image_4=image_4,
        image_5=image_5,
        db=db,
        payload=payload,
        get_supabase=get_supabase,
    )


@router.get(
    "/view_product_images/{store_id}/{product_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def product_images_list(
    store_id: int,
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await product_service.view_product_pics(
        store_id=store_id, product_id=product_id, db=db
    )


@router.put("/edit_product")
async def product_change(
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
    product_name: str | None = None,
    category: str | None = None,
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
