from fastapi import (
    APIRouter,
    Depends,
    Query,
    UploadFile,
    File,
    BackgroundTasks,
    Request,
)
from app.database.get import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.schemas import (
    PaginatedMetadata,
    ProductVariantResponse,
    StandardResponse,
    ProductVariantRequest,
    AddSwapEnum,
)
from app.services import product_variant_service
from app.utils.supabase_url import _supabase
from typing import Annotated
from supabase import AsyncClient

router = APIRouter(prefix="/product_variant", tags=["Product Variants"])

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]

SupabaseDep = Annotated[AsyncClient, Depends(_supabase)]


@router.post(
    "/add_product_variant",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def create_product_variant(
    request: Request,
    db: DatabaseDep,
    background_task: BackgroundTasks,
    variant: ProductVariantRequest,
):
    return await product_variant_service.create_v(
        variant=variant,
        db=db,
        request=request,
        background_tasks=background_task,
    )


@router.post(
    "/product_variant_images",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def upload_variant_images(
    request: Request,
    db: DatabaseDep,
    get_supabase: SupabaseDep,
    store_id: int,
    variant_id: int,
    image: UploadFile = File(...),
):
    return await product_variant_service.add_vimage(
        image=image,
        store_id=store_id,
        variant_id=variant_id,
        db=db,
        request=request,
        get_supabase=get_supabase,
    )


@router.get(
    "/view_product_variant_images/{variant_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def product_variant_images_list(variant_id: int, db: DatabaseDep):
    return await product_variant_service.view_variant_photos(
        variant_id=variant_id, db=db
    )


@router.put(
    "/edit_product_variant",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def product_variant_change(
    request: Request,
    db: DatabaseDep,
    variant: ProductVariantRequest,
    background_task: BackgroundTasks,
    edit_mode: AddSwapEnum = Query(AddSwapEnum.add),
):
    return await product_variant_service.variant_change(
        edit_mode=edit_mode,
        variant=variant,
        db=db,
        request=request,
        background_tasks=background_task,
    )


@router.get(
    "/get_variant/{variant_id}",
    response_model=StandardResponse[ProductVariantResponse],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def get_product_variant(db: DatabaseDep, variant_id: int):
    return await product_variant_service.product_variant(db=db, variant_id=variant_id)


@router.get(
    "/product_variants_list/{product_id}",
    response_model=StandardResponse[PaginatedMetadata[ProductVariantResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def get_product_variants(
    db: DatabaseDep,
    product_id: int,
    cursor_id: int | None = Query(None, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await product_variant_service.list_product_variants(
        product_id=product_id, db=db, cursor_id=cursor_id, limit=limit
    )


@router.delete(
    "/delete_product_image/{store_id}/{variant_id}/{image_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_image(
    request: Request,
    store_id: int,
    variant_id: int,
    image_id: int,
    db: DatabaseDep,
    get_supabase: SupabaseDep,
):
    return await product_variant_service.delete_image(
        store_id=store_id,
        variant_id=variant_id,
        image_id=image_id,
        db=db,
        request=request,
        get_supabase=get_supabase,
    )


@router.delete(
    "/delete_variant/{store_id}/{variant_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_product_variant(
    request: Request,
    store_id: int,
    variant_id: int,
    background_task: BackgroundTasks,
    db: DatabaseDep,
    get_supabase: SupabaseDep,
):
    return await product_variant_service.delete_one_variant(
        store_id=store_id,
        variant_id=variant_id,
        background_task=background_task,
        db=db,
        request=request,
        get_supabase=get_supabase,
    )
