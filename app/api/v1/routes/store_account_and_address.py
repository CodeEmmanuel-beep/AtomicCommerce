from fastapi import APIRouter, Form, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.schemas import (
    StandardResponse,
    StoreAccountResponse,
    PaginatedMetadata,
    AddressDetails,
    AddressResponse,
    ChronologyEnum,
    StoreAccountsList,
)
from app.models import AccountType, IdType, AccountVerification
from app.database.get import get_db
from app.services import store_account_and_address_service
from typing import Annotated
from cryptography.fernet import Fernet

router = APIRouter(
    prefix="/store_account_and_address", tags=["Store Account and Address"]
)

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]


def get_cipher(request: Request):
    return request.app.state.cipher


CipherDep = Annotated[Fernet, Depends(get_cipher)]


@router.post(
    "/store_account",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def store_account_details(
    request: Request,
    db: DatabaseDep,
    cipher: CipherDep,
    store_id: int,
    bank_name: str = Form(...),
    account_type: AccountType = Query(AccountType.business),
    account_holder_name: str = Form(...),
    account_number: str = Form(...),
    type_of_id: IdType = Query(IdType.national_id),
    identification_number: str = Form(...),
    tax_identification_number: str | None = Form(None),
):
    return await store_account_and_address_service.add_finance_details(
        store_id=store_id,
        account_holder_name=account_holder_name,
        bank_name=bank_name,
        account_type=account_type.value,
        account_number=account_number,
        type_of_id=type_of_id.value,
        identification_number=identification_number,
        tax_identification_number=tax_identification_number,
        db=db,
        request=request,
        cipher=cipher,
    )


@router.put(
    "/edit_store_account",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def edit_store_account_details(
    request: Request,
    db: DatabaseDep,
    cipher: CipherDep,
    store_id: int,
    bank_name: str | None = Form(None),
    account_type: AccountType = Query(None),
    account_holder_name: str | None = Form(None),
    account_number: str | None = Form(None),
    type_of_id: IdType = Query(None),
    identification_number: str | None = Form(None),
    tax_identification_number: str | None = Form(None),
):
    return await store_account_and_address_service.edit_finance_details(
        store_id=store_id,
        account_holder_name=account_holder_name,
        bank_name=bank_name,
        account_type=account_type.value if account_type else None,
        account_number=account_number,
        type_of_id=type_of_id.value if type_of_id else None,
        identification_number=identification_number,
        tax_identification_number=tax_identification_number,
        db=db,
        request=request,
        cipher=cipher,
    )


@router.put(
    "/store_account_verification",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def verify_account(
    request: Request,
    db: DatabaseDep,
    slug: str,
    reason: str | None = None,
    status: AccountVerification = Query(AccountVerification.verified),
):
    return await store_account_and_address_service.verify_store_account(
        slug=slug, reason=reason, status=status, db=db, request=request
    )


@router.get(
    "/stores_account_list",
    response_model=StandardResponse[PaginatedMetadata[StoreAccountsList]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def stores_accounts(
    request: Request,
    db: DatabaseDep,
    cipher: CipherDep,
    account_status: AccountVerification = Query(AccountVerification.pending),
    chronology: ChronologyEnum = Query(ChronologyEnum.desc),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await store_account_and_address_service.view_stores_account(
        db=db,
        request=request,
        cipher=cipher,
        page=page,
        limit=limit,
        status=account_status,
        chronology=chronology,
    )


@router.get(
    "/store_account/{store_id}",
    response_model=StandardResponse[StoreAccountsList],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def store_account(
    request: Request,
    store_id: int,
    db: DatabaseDep,
    cipher: CipherDep,
):
    return await store_account_and_address_service.store_financial_details(
        store_id=store_id, db=db, request=request, cipher=cipher
    )


@router.get(
    "/view_store_account_details/{store_id}",
    response_model=StandardResponse[StoreAccountResponse],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_store_account(
    request: Request,
    store_id: int,
    db: DatabaseDep,
    cipher: CipherDep,
):
    return await store_account_and_address_service.view_financial_details(
        store_id=store_id, db=db, request=request, cipher=cipher
    )


@router.post(
    "/store_address",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def store_address_details(
    request: Request, store_id: int, address_details: AddressDetails, db: DatabaseDep
):
    return await store_account_and_address_service.add_address(
        store_id=store_id, address_details=address_details, db=db, request=request
    )


@router.get(
    "/view_store_address_details/{store_id}",
    response_model=StandardResponse[PaginatedMetadata[AddressResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_store_address(
    store_id: int,
    db: DatabaseDep,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await store_account_and_address_service.view_store_addresses(
        store_id=store_id, page=page, limit=limit, db=db
    )


@router.delete(
    "/delete_address/{store_id}/{address_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_address_by_id(
    request: Request, store_id: int, address_id: int, db: DatabaseDep
):
    return await store_account_and_address_service.remove_address(
        store_id=store_id, address_id=address_id, db=db, request=request
    )
