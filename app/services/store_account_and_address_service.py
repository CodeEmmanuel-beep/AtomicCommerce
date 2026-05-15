from fastapi import HTTPException
from app.logs.logger import get_logger
from sqlalchemy import select, exists, func
from app.models import Store, StoreAccount, store_owners, Address, AccountVerification
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from app.api.v1.schemas import (
    StoreAccountResponse,
    AddressDetails,
    AddressResponse,
    PaginatedMetadata,
    PaginatedResponse,
    StandardResponse,
)
from app.utils.redis import cache, cached

logger = get_logger("store_account_and_address")


async def add_finance_details(
    store_id,
    account_holder_name,
    bank_name,
    account_type,
    account_number,
    type_of_id,
    identification_number,
    tax_identification_number,
    db,
    payload,
    cipher,
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at add_finance_details endpoint")
        raise HTTPException(
            status_code=401, detail="unauthorized, you must be a registered user"
        )
    result = await db.execute(
        select(
            exists().where(Store.id == store_id),
            exists().where(
                store_owners.c.stores_id == store_id,
                store_owners.c.users_id == user_id,
            ),
            exists().where(Store.id == store_id, ~Store.account.any()),
        )
    )
    store_exists, is_owner, has_no_account = result.fetchone()
    if not store_exists:
        logger.error(f"Store {store_id} not found.")
        raise HTTPException(status_code=404, detail="Store not found")
    if not is_owner:
        logger.error(f"User {user_id} unauthorized for store {store_id}")
        raise HTTPException(status_code=403, detail="Not the store owner")
    if not has_no_account:
        logger.warning(f"Store {store_id} already has finance details.")
        raise HTTPException(
            status_code=400, detail="Finance details already exist for this store"
        )
    acc_num = cipher.encrypt(account_number.encode())
    tax_num = (
        cipher.encrypt(tax_identification_number.encode())
        if tax_identification_number
        else None
    )

    id_num = cipher.encrypt(identification_number.encode())
    account_detail = StoreAccount(
        store_id=store_id,
        bank_name=bank_name,
        account_type=account_type,
        account_holder_name=account_holder_name,
        account_number=acc_num,
        type_of_id=type_of_id,
        identification_number=id_num,
        tax_identification_number=tax_num,
    )
    try:
        db.add(account_detail)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error(
            "database error while adding finance details for store '%s'", store_id
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while adding finance details for store '%s'", store_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("finance details added to store: %s successfully", store_id)
    return {"message": "finance details added"}


async def edit_finance_details(
    store_id,
    account_holder_name,
    bank_name,
    account_type,
    account_number,
    type_of_id,
    identification_number,
    tax_identification_number,
    db,
    payload,
    cipher,
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at add_finance_details endpoint")
        raise HTTPException(
            status_code=401, detail="unauthorized, you must be a registered user"
        )
    result = await db.execute(
        select(StoreAccount)
        .join(store_owners, StoreAccount.store_id == store_owners.c.stores_id)
        .where(StoreAccount.store_id == store_id, store_owners.c.users_id == user_id)
    )
    store_account = result.scalar_one_or_none()
    if not store_account:
        logger.error(f"Store account {store_id} not found.")
        raise HTTPException(status_code=404, detail="Store account not found")
    acc_num = cipher.encrypt(account_number.encode()) if account_number else None
    tax_num = (
        cipher.encrypt(tax_identification_number.encode())
        if tax_identification_number
        else None
    )
    id_num = (
        cipher.encrypt(identification_number.encode())
        if identification_number
        else None
    )
    is_verified = store_account.verification_status == AccountVerification.verified
    adding_missing_tax = (
        not store_account.tax_identification_number and tax_identification_number
    )
    if is_verified and not adding_missing_tax:
        logger.warning("user: %s, attempted to edit verified account details", user_id)
        raise HTTPException(
            status_code=400, detail="Cannot edit verified account details"
        )
    updated_fields = {
        "store_id": store_id,
        "bank_name": bank_name,
        "account_type": account_type,
        "account_holder_name": account_holder_name,
        "account_number": acc_num,
        "type_of_id": type_of_id,
        "identification_number": id_num,
        "tax_identification_number": tax_num,
    }
    for field, value in updated_fields.items():
        if value:
            setattr(store_account, field, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error(
            "database error while updating finance details for store '%s'", store_id
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            "error while updating finance details for store '%s'", store_id
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("finance details updated for store: %s successfully", store_id)
    return {"message": "finance details updated"}


async def view_financial_details(store_id, db, payload, cipher):
    user_id = payload.get("user_id")
    role = payload.get("role")
    if not user_id:
        logger.warning("unauthorized attempt at view_financial_details endpoint")
        raise HTTPException(
            status_code=401, detail="unauthorized, you must be a registered user"
        )
    allowed_roles = ["Owner", "Admin"]
    store_account = (
        await db.execute(
            select(StoreAccount)
            .options(selectinload(StoreAccount.store).selectinload(Store.user_owners))
            .where(StoreAccount.store_id == store_id)
        )
    ).scalar_one_or_none()
    if not store_account:
        logger.warning(
            "user: %s, tried to view a non-existent finance details of store: %s",
            user_id,
            store_id,
        )
        raise HTTPException(status_code=404, detail="store account not found")
    owner_id = [owner.id for owner in store_account.store.user_owners]
    if user_id not in owner_id and role not in allowed_roles:
        logger.warning(
            "user: %s, attempted to bypass a restricted access in view financial details endpoint for store: %s",
            user_id,
            store_id,
        )
        raise HTTPException(status_code=403, detail="restricted access")
    data = StoreAccountResponse.model_validate(
        store_account, context={"cipher": cipher}
    )
    logger.info(
        "store: %s, successfully returned data, sensitive fields decrypted for user: %s",
        store_id,
        user_id,
    )
    return data


async def add_address(store_id, address_details, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at add_address endpoint")
        raise HTTPException(
            status_code=401, detail="unauthorized, you must be a registered user"
        )
    store_check = (
        await db.execute(
            select(Store)
            .join(store_owners, Store.id == store_owners.c.store_id)
            .where(Store.id == store_id, store_owners.c.user_id == user_id)
        )
    ).scalar_one_or_none()
    if not store_check:
        logger.warning(
            "user: %s, tried to add address details to a store not assigned, store: %s",
            user_id,
            store_id,
        )
        raise HTTPException(status_code=404, detail="store not assigned")
    address_detail = Address(
        store_id=store_check.id,
        street=address_details.street,
        city=address_details.city,
        state=address_details.state,
        country=address_details.country,
    )
    try:
        db.add(address_detail)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error(
            "database error while adding address details for store '%s'", store_id
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while adding address details for store '%s'", store_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("address details added to store: %s successfully", store_id)
    return {"message": "address details added"}


async def view_store_addresses(store_id, page, limit, db):
    offset = (page - 1) * limit
    cache_key = f"store_addresses:{store_id}:{page}:{limit}"
    cached_data = await cache(cache_key)
    if cached_data:
        logger.info(
            "cache hit at view store addresses endpoint for store: %s", store_id
        )
        return StandardResponse(**cached_data)
    stmt = await db.execute(
        select(Address, func.count(Address.id).over().label("total_count"))
        .join(Store, Address.store_id == Store.id)
        .where(
            Store.id == store_id, Address.is_deleted, ~Store.is_deleted, Store.approved
        )
        .offset(offset)
        .limit(limit)
    )
    store_address = stmt.all()
    if not store_address:
        logger.info("no addresses found for store: %s", store_id)
        return StandardResponse(
            status="success", message="no addresses found for this store", data=None
        )
    total = store_address[0].total_count
    data = PaginatedMetadata[AddressResponse](
        items=[AddressResponse.model_validate(add.Address) for add in store_address],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    full_response = StandardResponse(
        status="success", message="store addresses retrieved", data=data
    )
    await cached(cache_key, full_response, ttl=300)
    logger.info(
        "data returned at view store addresses endpoint for store: %s", store_id
    )
    return full_response


async def remove_address(store_id, address_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at delete_address endpoint")
        raise HTTPException(
            status_code=401, detail="only registered users can access this endpoint"
        )
    check_stmt = (
        select(Address)
        .join(Store, Address.store_id == Store.id)
        .join(store_owners, Store.id == store_owners.c.stores_id)
        .where(
            Store.id == store_id,
            store_owners.c.users_id == user_id,
            Address.id == address_id,
            ~Address.is_deleted,
        )
        .with_for_update(of=Address)
    )
    address_check = (await db.execute(check_stmt)).scalar_one_or_none()
    if not address_check:
        logger.error(
            "user: %s, hit a permission errror at the delete_address endpoint",
            user_id,
        )
        raise HTTPException(
            status_code=403,
            detail="permission error, verify the store and address before proceeding",
        )
    address_check.is_deleted = True
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error(
            "database error occured at the delete_address endpoint, user afffected: %s",
            user_id,
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            "rollback occured at the delete_address endpoint, user afffected: %s",
            user_id,
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("address '%s', removed from store: %s", address_id, store_id)
    return {"message": "address deleted"}
