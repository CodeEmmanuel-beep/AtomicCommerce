from fastapi import (
    APIRouter,
    Depends,
    Query,
    UploadFile,
    File,
    BackgroundTasks,
    Form,
    Request,
    Depends,
)
from app.database.get import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.schemas import (
    PaginatedMetadata,
    ProductResponse,
    StandardResponse,
    ProductFilterEnum,
    ProductSearch,
)
from app.services import product_service
from app.utils.supabase_url import _supabase
from decimal import Decimal
from typing import Annotated
from supabase import AsyncClient

router = APIRouter(prefix="/product", tags=["Products"])

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]

SupabaseDep = Annotated[AsyncClient, Depends(_supabase)]


@router.post(
    "/add_product", response_model=StandardResponse, response_model_exclude_none=True
)
async def create_product(
    request: Request,
    db: DatabaseDep,
    get_supabase: SupabaseDep,
    background_task: BackgroundTasks,
    store_id: int = Form(...),
    sub_category_name: str = Form(...),
    primary_image: UploadFile = File(...),
    product_name: str = Form(...),
    product_description: str = Form(...),
):
    return await product_service.create(
        primary_image=primary_image,
        store_id=store_id,
        sub_category_name=sub_category_name,
        product_name=product_name,
        product_description=product_description,
        db=db,
        request=request,
        background_tasks=background_task,
        get_supabase=get_supabase,
    )


@router.post(
    "/product_images", response_model=StandardResponse, response_model_exclude_none=True
)
async def upload_product_images(
    request: Request,
    db: DatabaseDep,
    get_supabase: SupabaseDep,
    store_id: int = Form(...),
    product_id: int = Form(...),
    image: UploadFile = File(...),
):
    return await product_service.add_image(
        image=image,
        store_id=store_id,
        product_id=product_id,
        db=db,
        request=request,
        get_supabase=get_supabase,
    )


@router.get(
    "/view_product_images/{store_id}/{product_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def product_images_list(store_id: int, product_id: int, db: DatabaseDep):
    return await product_service.view_product_pics(
        store_id=store_id, product_id=product_id, db=db
    )


@router.put(
    "/edit_product", response_model=StandardResponse, response_model_exclude_none=True
)
async def product_change(
    request: Request,
    db: DatabaseDep,
    get_supabase: SupabaseDep,
    store_id: int,
    product_id: int,
    background_task: BackgroundTasks,
    primary_image: UploadFile = File(None),
    product_name: str | None = Form(None),
    product_description: str | None = Form(None),
):
    return await product_service.product_change(
        store_id=store_id,
        product_id=product_id,
        primary_image=primary_image,
        product_name=product_name,
        product_description=product_description,
        db=db,
        request=request,
        get_supabase=get_supabase,
        background_tasks=background_task,
    )


@router.get(
    "/store_product/{store_id}/{product_id}",
    response_model=StandardResponse[ProductResponse],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def get_store_product(db: DatabaseDep, store_id: int, product_id: int):
    return await product_service.store_product(
        store_id=store_id, db=db, product_id=product_id
    )


@router.get(
    "/store_products_list",
    response_model=StandardResponse,
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def store_products(
    db: DatabaseDep,
    store_id: int,
    seed: float = 0.5,
    cursor_id: int | None = Query(None, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await product_service.list_store_products(
        seed=seed, store_id=store_id, db=db, cursor_id=cursor_id, limit=limit
    )


@router.get(
    "/search_products",
    response_model=StandardResponse[PaginatedMetadata[ProductResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def search(
    db: DatabaseDep,
    search_value: str,
    seed: float = 0.5,
    filters: ProductFilterEnum = Query(None),
    search: ProductSearch = Query(ProductSearch.product_name),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await product_service.search_product(
        seed=seed,
        filters=filters.value if filters else None,
        search_value=search_value,
        search=search.value,
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
    request: Request,
    store_id: int,
    product_id: int,
    image_id: int,
    db: DatabaseDep,
    get_supabase: SupabaseDep,
):
    return await product_service.delete_images(
        store_id=store_id,
        product_id=product_id,
        image_id=image_id,
        db=db,
        request=request,
        get_supabase=get_supabase,
    )


@router.delete(
    "/delete/{store_id}/{product_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_product(
    request: Request,
    store_id: int,
    product_id: int,
    background_task: BackgroundTasks,
    db: DatabaseDep,
    get_supabase: SupabaseDep,
):
    return await product_service.delete_one(
        store_id=store_id,
        product_id=product_id,
        background_task=background_task,
        db=db,
        request=request,
        get_supabase=get_supabase,
    )
