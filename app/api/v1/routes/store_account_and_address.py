from fastapi import APIRouter, Depends, Form, Query, Request
from app.auth.verify_jwt import verify_token
from app.database.get import get_db
from app.services import store_account_and_address_service
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.schemas import (
    StandardResponse,
    StoreAccountResponse,
    PaginatedMetadata,
    AddressDetails,
    AddressResponse,
)

router = APIRouter(
    prefix="/store_account_and_address", tags=["Store Account and Address"]
)


def get_cipher(request: Request):
    return request.app.state.cipher


@router.post("/store_account")
async def store_account_details(
    store_id: int,
    bank_name: str = Form(...),
    account_type: str = Query("business", enum=["savings", "current", "business"]),
    account_holder_name: str = Form(...),
    account_number: str = Form(...),
    type_of_id: str = Query(
        "national_id", enum=["voter_id", "national_id", "driver_license", "other_id"]
    ),
    identification_number: str = Form(...),
    tax_identification_number: str = Form(None),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
    cipher=Depends(get_cipher),
):
    return await store_account_and_address_service.add_finance_details(
        store_id=store_id,
        account_holder_name=account_holder_name,
        bank_name=bank_name,
        account_type=account_type,
        account_number=account_number,
        type_of_id=type_of_id,
        identification_number=identification_number,
        tax_identification_number=tax_identification_number,
        db=db,
        payload=payload,
        cipher=cipher,
    )


@router.put("/edit_store_account")
async def edit_store_account_details(
    store_id: int,
    bank_name: str = Form(None),
    account_type: str = Query("business", enum=["savings", "current", "business"]),
    account_holder_name: str = Form(None),
    account_number: str = Form(None),
    type_of_id: str = Query(
        "national_id", enum=["voter_id", "national_id", "driver_license", "other_id"]
    ),
    identification_number: str = Form(None),
    tax_identification_number: str = Form(None),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
    cipher=Depends(get_cipher),
):
    return await store_account_and_address_service.edit_finance_details(
        store_id=store_id,
        account_holder_name=account_holder_name,
        bank_name=bank_name,
        account_type=account_type,
        account_number=account_number,
        type_of_id=type_of_id,
        identification_number=identification_number,
        tax_identification_number=tax_identification_number,
        db=db,
        payload=payload,
        cipher=cipher,
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
    return await store_account_and_address_service.view_financial_details(
        store_id=store_id, db=db, payload=payload, cipher=cipher
    )


@router.post("/store_address")
async def store_address_details(
    store_id: int,
    address_details: AddressDetails,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_account_and_address_service.add_address(
        store_id=store_id,
        address_details=address_details,
        db=db,
        payload=payload,
    )


@router.get(
    "/view_store_address_details/{store_id}",
    response_model=StandardResponse[PaginatedMetadata[AddressResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_store_address(
    store_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await store_account_and_address_service.view_store_addresses(
        store_id=store_id, page=page, limit=limit, db=db
    )


@router.delete("/delete_address/{store_id}/{address_id}")
async def delete_address_by_id(
    store_id: int,
    address_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_account_and_address_service.remove_address(
        store_id=store_id, address_id=address_id, db=db, payload=payload
    )
