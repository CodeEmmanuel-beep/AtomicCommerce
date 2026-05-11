from fastapi import UploadFile, File, APIRouter, Depends, Request, Query, Form
from app.services import store_service
from app.api.v1.schemas import (
    StoreAccountDetails,
    StandardResponse,
    StoreAccountResponse,
    PaginatedMetadata,
    AddressDetails,
    StoreResponse,
)
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.verify_jwt import verify_token
from app.database.get import get_db
from app.utils.supabase_url import _supabase
from typing import List
from decimal import Decimal

router = APIRouter(prefix="/store", tags=["store"])


def get_cipher(request: Request):
    return request.app.state.cipher


@router.post("/create")
async def create_store(
    store_photo: UploadFile = File(...),
    store_name: str = Form(...),
    owners: str = Form(...),
    category: str = Form(...),
    sub_category: str = Form(...),
    store_email: str = Form(None),
    store_contact: str = Form(None),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
    get_supabase=Depends(_supabase),
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
        payload=payload,
        get_supabase=get_supabase,
    )


@router.put("/update/{store_id}")
async def update_store(
    store_id: int,
    update_type: str = Query("add", enum=["add", "replace"]),
    store_photo: UploadFile = File(None),
    business_logo: UploadFile = File(None),
    store_name: str = Form(None),
    sub_category: str = Form(None),
    motto: str = Form(None),
    description: str = Form(None),
    store_contact: str = Form(None),
    store_email: str = Form(None),
    shipping_fee: Decimal = Form(None),
    get_supabase=Depends(_supabase),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_service.store_update(
        store_id=store_id,
        update_type=update_type,
        business_logo=business_logo,
        store_photo=store_photo,
        store_name=store_name,
        sub_category=sub_category,
        motto=motto,
        description=description,
        store_contact=store_contact,
        store_email=store_email,
        shipping_fee=shipping_fee,
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
    "/view_personal_stores",
    response_model=StandardResponse[List[StoreResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_stores(
    position: str = Query("owner", enum=["staff", "owner"]),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_service.view_store(position=position, db=db, payload=payload)


@router.get(
    "/search_stores_global",
    response_model=StandardResponse[PaginatedMetadata[StoreResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_stores_global(
    search_value: str,
    search: str = Query(
        "category", enum=["category", "sub_category", "store_name", "product_name"]
    ),
    seed: float = 0.5,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await store_service.search_stores(
        search_value=search_value,
        search=search,
        seed=seed,
        page=page,
        limit=limit,
        db=db,
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
