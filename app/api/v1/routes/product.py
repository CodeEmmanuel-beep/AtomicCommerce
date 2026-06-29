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
from decimal import Decimal

router = APIRouter(prefix="/product", tags=["Products"])


@router.post(
    "/add_product", response_model=StandardResponse, response_model_exclude_none=True
)
async def create_product(
    store_id: int = Form(...),
    sub_category_name: str = Form(...),
    primary_image: UploadFile = File(...),
    product_name: str = Form(...),
    product_type: str = Form(...),
    product_size: str = Query(
        "small", enum=["small", "medium", "large", "extra_large"]
    ),
    product_price: Decimal = Form(...),
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


@router.post(
    "/product_images", response_model=StandardResponse, response_model_exclude_none=True
)
async def upload_product_images(
    store_id: int = Form(...),
    product_id: int = Form(...),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
    get_supabase=Depends(_supabase),
):
    return await product_service.add_image(
        image=image,
        store_id=store_id,
        product_id=product_id,
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


@router.put(
    "/edit_product", response_model=StandardResponse, response_model_exclude_none=True
)
async def product_change(
    store_id: int,
    product_id: int,
    primary_image: UploadFile = File(None),
    product_name: str = Form(None),
    product_type: str = Form(None),
    product_size: str = Query(None, enum=["small", "medium", "large", "extra_large"]),
    product_price: Decimal = Form(None),
    product_description: str = Form(None),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
    get_supabse=Depends(_supabase),
):
    return await product_service.product_change(
        store_id=store_id,
        product_id=product_id,
        primary_image=primary_image,
        product_name=product_name,
        product_type=product_type,
        product_size=product_size,
        product_price=product_price,
        product_description=product_description,
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
async def search(
    seed: float = 0.5,
    filters: str = Query(None, enum=["cheap", "quality", "latest"]),
    product_name: str | None = None,
    category: str | None = None,
    sub_category: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await product_service.search_product(
        seed=seed,
        filters=filters,
        sub_category=sub_category,
        product_name=product_name,
        category=category,
        page=page,
        limit=limit,
        db=db,
    )


@router.delete(
    "/delete_product_image/{store_id}/{product_id}/{image_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_image(
    store_id: int,
    product_id: int,
    image_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
    get_supabase=Depends(_supabase),
):
    return await product_service.delete_images(
        store_id=store_id,
        product_id=product_id,
        image_id=image_id,
        db=db,
        payload=payload,
        get_supabase=get_supabase,
    )


@router.delete(
    "/delete/{store_id}/{product_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
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
