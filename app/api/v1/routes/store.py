from fastapi import UploadFile, File, APIRouter, Depends, Request, Query
from app.services import store_service
from app.api.v1.models import (
    StoreAccountDetails,
    StandardResponse,
    StoreAccountResponse,
    BusinessType,
    PaginatedMetadata,
    AddressDetails,
    StoreObj,
    StoreResponse,
    StoreUpdate,
)
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.verify_jwt import verify_token
from app.database.get import get_db
from app.utils.supabase_url import _supabase

router = APIRouter(prefix="/store", tags=["store"])


def get_cipher(request: Request):
    return request.app.state.cipher


@router.post("/create")
async def create_store(
    storeobj: StoreObj,
    get_supabase=Depends(_supabase),
    store_photo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_service.store_creation(
        store_photo=store_photo,
        storeobj=storeobj,
        db=db,
        payload=payload,
        get_supabase=get_supabase,
    )


@router.put("/update")
async def update_store(
    storeupdate: StoreUpdate,
    get_supabase=Depends(_supabase),
    store_photo: UploadFile = File(...),
    business_logo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_service.store_update(
        business_logo=business_logo,
        store_photo=store_photo,
        storeupdate=storeupdate,
        db=db,
        payload=payload,
        get_supabase=get_supabase,
    )


@router.put("/approve_store")
async def store_approval(
    slug: str, db: AsyncSession = Depends(get_db), payload: dict = Depends(verify_token)
):
    return await store_service.approve_stores(slug=slug, db=db, payload=payload)


@router.post("/store_account")
async def store_account_details(
    store_id: int,
    financial_details: StoreAccountDetails,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
    cipher=Depends(get_cipher),
):
    return await store_service.add_finance_details(
        store_id=store_id,
        finance_details=financial_details,
        db=db,
        payload=payload,
        cipher=cipher,
    )


@router.post("/store_address")
async def store_address_details(
    store_id: int,
    address_details: AddressDetails,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_service.add_address(
        store_id=store_id,
        address_details=address_details,
        db=db,
        payload=payload,
    )


@router.put("/onboard_owner_staff")
async def onboard_owner_staff(
    store_id: int,
    owner_id: int,
    staff_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_service.add_owner_staff(
        store_id=store_id, owner_id=owner_id, staff_id=staff_id, db=db, payload=payload
    )


@router.get(
    "/view_store_account_details/{store_id}",
    response_model=StoreAccountResponse,
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_store_account(
    store_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
    cipher=Depends(get_cipher),
):
    return await store_service.view_financial_details(
        store_id=store_id, db=db, payload=payload, cipher=cipher
    )


@router.get(
    "/view_store_address_details/{store_id}",
    response_model=StandardResponse[PaginatedMetadata[AddressDetails]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_store_address(
    store_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await store_service.view_store_addresses(
        store_id=store_id, page=page, limit=limit, db=db
    )


@router.get(
    "/view_store_by_category",
    response_model=StandardResponse[PaginatedMetadata[StoreResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_store_through_category(
    category_name: str,
    seed: float = 0.5,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await store_service.view_stores_by_category(
        category_name=category_name, seed=seed, page=page, limit=limit, db=db
    )


@router.get(
    "/view_store_by_name",
    response_model=StandardResponse[PaginatedMetadata[StoreResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_store_through_name(
    store_name: str,
    seed: float = 0.5,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await store_service.view_stores_by_store_name(
        store_name=store_name, seed=seed, page=page, limit=limit, db=db
    )


@router.get(
    "/view_store_by_business_type",
    response_model=StandardResponse[PaginatedMetadata[StoreResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_store_through_business_type(
    business_type: BusinessType,
    seed: float = 0.5,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await store_service.view_stores_by_business_type(
        business_type=business_type, seed=seed, page=page, limit=limit, db=db
    )


@router.get(
    "/view_store_by_product/{store_id}",
    response_model=StandardResponse[PaginatedMetadata[StoreResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_store_through_product(
    product_name: str,
    seed: float = 0.5,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await store_service.view_stores_by_product_name(
        product_name=product_name, seed=seed, page=page, limit=limit, db=db
    )


@router.delete("/delete_staff/{store_id}/{staff_id}")
async def delete_staff_by_id(
    store_id: int,
    staff_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_service.remove_staff(
        store_id=store_id, staff_id=staff_id, db=db, payload=payload
    )


@router.delete("/delete_address/{store_id}/{address_id}")
async def delete_address_by_id(
    store_id: int,
    address_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_service.remove_address(
        store_id=store_id, address_id=address_id, db=db, payload=payload
    )


@router.delete("/delete_store/{store_id}")
async def delete_store_by_id(
    store_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_service.remove_store(store_id=store_id, db=db, payload=payload)
