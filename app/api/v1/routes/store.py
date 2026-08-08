from fastapi import UploadFile, File, APIRouter, Depends, Query, Form, Request
from app.services import store_service
from app.api.v1.schemas import (
    StandardResponse,
    PaginatedMetadata,
    StoreResponse,
    PersonnelResponse,
    PersonalStoreResponse,
    AddSwapEnum,
    OwnerStaff,
    StoreFilterEnum,
)
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db
from supabase import AsyncClient
from typing import Annotated
from app.utils.supabase_url import _supabase
from decimal import Decimal

router = APIRouter(prefix="/store", tags=["store"])

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]
SupabaseDep = Annotated[AsyncClient, Depends(_supabase)]


@router.post(
    "/create",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def create_store(
    request: Request,
    db: DatabaseDep,
    get_supabase: SupabaseDep,
    store_photo: UploadFile = File(...),
    store_name: str = Form(...),
    owners: str = Form(...),
    category: str = Form(...),
    sub_category: str = Form(...),
    store_email: str = Form(...),
    store_contact: str | None = Form(None),
):
    return await store_service.store_creation(
        store_photo=store_photo,
        store_name=store_name,
        owners=owners,
        category=category,
        sub_category=sub_category,
        store_email=store_email,
        store_contact=store_contact,
        db=db,
        request=request,
        get_supabase=get_supabase,
    )


@router.put(
    "/update/{store_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def update_store(
    request: Request,
    db: DatabaseDep,
    get_supabase: SupabaseDep,
    store_id: int,
    update_type: AddSwapEnum = Query(AddSwapEnum.add),
    store_photo: UploadFile = File(None),
    business_logo: UploadFile = File(None),
    store_name: str | None = Form(None),
    sub_category: str | None = Form(None),
    motto: str | None = Form(None),
    description: str | None = Form(None),
    store_contact: str | None = Form(None),
    store_email: str | None = Form(None),
    tax_rate: Decimal | None = Form(None),
    shipping_fee: Decimal | None = Form(None),
):
    return await store_service.store_update(
        store_id=store_id,
        update_type=update_type.value,
        business_logo=business_logo,
        store_photo=store_photo,
        store_name=store_name,
        sub_category=sub_category,
        motto=motto,
        description=description,
        store_contact=store_contact,
        store_email=store_email,
        tax_rate=tax_rate,
        shipping_fee=shipping_fee,
        db=db,
        request=request,
        get_supabase=get_supabase,
    )


@router.put(
    "/approve_store",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def store_approval(request: Request, slug: str, db: DatabaseDep):
    return await store_service.approve_stores(slug=slug, db=db, request=request)


@router.put(
    "/onboard_owner_staff",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def onboard_owner_staff(
    request: Request,
    db: DatabaseDep,
    store_id: int,
    owner_id: int | None = None,
    staff_id: int | None = None,
):
    return await store_service.add_owner_staff(
        store_id=store_id, owner_id=owner_id, staff_id=staff_id, db=db, request=request
    )


@router.get(
    "/view_store_personnel/{store_id}",
    response_model=StandardResponse[PaginatedMetadata[PersonnelResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def store_personnel(
    request: Request,
    db: DatabaseDep,
    store_id: int,
    position: OwnerStaff = Query(OwnerStaff.owner),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await store_service.view_store_owners_staffs(
        store_id=store_id,
        view=position.value,
        page=page,
        limit=limit,
        db=db,
        request=request,
    )


@router.get(
    "/view_personal_stores",
    response_model=StandardResponse[list[PersonalStoreResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_stores(
    request: Request,
    db: DatabaseDep,
    position: OwnerStaff = Query(OwnerStaff.owner),
):
    return await store_service.view_store(
        position=position.value, db=db, request=request
    )


@router.get(
    "/search_stores_global",
    response_model=StandardResponse[PaginatedMetadata[StoreResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_stores_global(
    search_value: str,
    db: DatabaseDep,
    search: StoreFilterEnum = Query(StoreFilterEnum.category),
    seed: float = 0.5,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await store_service.search_stores(
        search_value=search_value,
        search=search.value,
        seed=seed,
        page=page,
        limit=limit,
        db=db,
    )


@router.delete(
    "/delete_staff/{store_id}/{staff_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_staff_by_id(
    request: Request, store_id: int, staff_id: int, db: DatabaseDep
):
    return await store_service.remove_staff(
        store_id=store_id, staff_id=staff_id, db=db, request=request
    )


@router.delete(
    "/delete_store/{store_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_store_by_id(
    request: Request,
    store_id: int,
    db: DatabaseDep,
    get_supabase: SupabaseDep,
):
    return await store_service.remove_store(
        store_id=store_id, db=db, request=request, get_supabase=get_supabase
    )
