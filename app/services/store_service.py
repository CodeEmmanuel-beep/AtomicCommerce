from fastapi import HTTPException
from app.models import (
    Store,
    Category,
    User,
    store_owners,
    store_staffs,
    Address,
    StoreAccount,
    Product,
    Inventory,
    SubCategory,
)
from app.api.v1.schemas import (
    StoreAccountResponse,
    StoreResponse,
    PaginatedMetadata,
    PaginatedResponse,
    StandardResponse,
    ProductRes,
    AddressDetails,
)
from datetime import datetime, timezone
from app.logs.logger import get_logger
from sqlalchemy.orm import selectinload, aliased
from sqlalchemy import func, select, text, and_, exists, update, cast, String
from sqlalchemy.exc import IntegrityError
from app.utils.helper import upload_photo_helper
from app.utils.supabase_url import cleaned_up, get_public_url
from app.utils.redis import store_invalidation, cache, cached, cache_version
import re
import regex

logger = get_logger("store")

store_name_pattern = regex.compile(r"^[\p{L}\s]+$")


def generate_slug(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s_-]+", "-", name)
    name = re.sub(r"^-+|-+$", "", name)
    return name


async def store_creation(
    store_name,
    owners,
    category,
    sub_category,
    store_email,
    store_contact,
    store_photo,
    db,
    payload,
    get_supabase,
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at store_creation endpoint")
        raise HTTPException(
            status_code=401, detail="only registered users can own a store"
        )
    if not store_name_pattern.fullmatch(store_name):
        raise HTTPException(status_code=400, detail="store names should be in letters")
    store_slug = generate_slug(store_name)
    try:
        if isinstance(owners, str):
            owners = [int(i.strip()) for i in owners.split(",")]
        elif isinstance(owners, list):
            owners = [int(i.strip()) for i in owners[0].split(",")]
    except ValueError:
        raise HTTPException(
            status_code=400, detail="owners must be a comma-separated list of numbers"
        )
    try:
        if isinstance(sub_category, str):
            sub_category = [str(i.strip()) for i in sub_category.split(",")]
        elif isinstance(sub_category, list):
            sub_category = [str(i.strip()) for i in sub_category[0].split(",")]
    except ValueError:
        raise HTTPException(status_code=400, detail="error inputing sub_category field")
    owners_input = list(set(owners))
    if user_id not in owners_input:
        logger.warning("user: %s, tried being a third party creator", user_id)
        raise HTTPException(
            status_code=400, detail="you can not create a store you do not own"
        )
    subq = select(
        select(exists().where(Store.slug == store_slug)).scalar_subquery(),
        select(Category.id).where(Category.name == category).scalar_subquery(),
    )
    result = (await db.execute(subq)).first() or (False, None)
    existing_slug, category_id = result
    if existing_slug:
        logger.warning("Slug collision for name: %s", store_name)
        raise HTTPException(
            status_code=400, detail="This store name is too similar to an existing one"
        )
    if category_id is None:
        logger.warning("Category '%s' not found in database", category)
        raise HTTPException(
            status_code=500, detail="Store category configuration error"
        )
    sub_count = (
        await db.execute(
            select(func.count(SubCategory.id)).where(
                SubCategory.name.in_(sub_category),
                SubCategory.category_id == category_id,
            )
        )
    ).scalar() or 0
    if sub_count != len(set(sub_category)):
        logger.warning(
            "user %s, tried inputing a sub_category not found in the database", user_id
        )
        raise HTTPException(
            status_code=400, detail="sub_category do not match the values available"
        )
    count_stmt = await db.execute(
        select(User, func.count(store_owners.c.stores_id))
        .outerjoin(store_owners, User.id == store_owners.c.users_id)
        .where(User.id.in_(owners_input))
        .group_by(User.id)
    )
    count = count_stmt.all()
    owner = []
    for _user, store_count in count:
        if store_count >= 10:
            logger.warning("a user tried owning more than 10 stores user: %s", _user.id)
            raise HTTPException(
                status_code=400, detail="a user can not own more than 10 stores"
            )
        owner.append(_user)
    if len(count) != len(owners_input):
        logger.warning(
            "user: %s, tried making a non-existent user a shop owner", user_id
        )
        raise HTTPException(
            status_code=400, detail="all owners must be registered users"
        )
    store_photo = await upload_photo_helper(store_photo, db, payload, get_supabase)
    new_store = Store(
        store_photo=store_photo,
        store_name=store_name,
        slug=store_slug,
        category_name=category,
        sub_category=sub_category,
        category_id=category_id,
        store_email=store_email,
        store_contact=store_contact,
        user_owners=owner,
    )
    try:
        db.add(new_store)
        await db.commit()
        await store_invalidation()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        await cleaned_up(
            get_supabase,
            store_photo,
            context_1="error removing orphaned store photo",
            context_2="successfully removed orphaned store photo",
        )
        logger.error("database error while creating store for user '%s'", user_id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        await cleaned_up(
            get_supabase,
            store_photo,
            context_1="error removing orphaned store photo",
            context_2="successfully removed orphaned store photo",
        )
        logger.exception("error while creating store for user '%s'", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("store: %s, created successfully", new_store.id)
    return {"message": "store created"}


async def store_update(
    storeupdate, business_logo, store_photo, db, payload, get_supabase
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at store_creation endpoint")
        raise HTTPException(
            status_code=401, detail="only registered users can own a store"
        )
    if not store_name_pattern.fullmatch(storeupdate.store_name):
        raise HTTPException(status_code=400, detail="store names should be in letters")
    stmt = (
        select(Store)
        .where(
            Store.id == storeupdate.store_id,
            Store.approved,
            Store.user_owners.any(User.id == user_id),
        )
        .with_for_update()
    )
    store_map = (await db.execute(stmt)).scalar_one_or_none()
    if not store_map:
        logger.warning(
            "user: %s, tried to edit store with store_id: %s, when they are",
            user_id,
            storeupdate.store_id,
        )
        raise HTTPException(status_code=403, detail="restricted access")
    if store_map.edited_name and storeupdate.store_name:
        logger.warning(
            "user: %s, tried to edit store with store_id: %s, name more than once",
            user_id,
            storeupdate.store_id,
        )
        raise HTTPException(
            status_code=400, detail="Store name cannot be changed morethan once"
        )
    old_photo = []
    filename_link = []
    if store_photo:
        old_photo.append(store_map.store_photo) if store_map.store_photo else None
        filename = await upload_photo_helper(store_photo, db, payload, get_supabase)
        store_map.store_photo = filename
        filename_link.append(filename)
    if business_logo:
        old_photo.append(store_map.business_logo) if store_map.business_logo else None
        filename = await upload_photo_helper(business_logo, db, payload, get_supabase)
        store_map.business_logo = filename
        filename_link.append(filename)
    if storeupdate.store_name:
        store_map.store_previous_name = store_map.store_name
        store_map.store_name = storeupdate.store_name
        store_map.edited_name = True
    update_fields = [
        "motto",
        "store_description",
        "store_contact",
        "business_type",
        "store_email",
    ]
    for field in update_fields:
        value = getattr(storeupdate, field, None)
        if value is not None:
            setattr(store_map, field, value)
    try:
        await db.commit()
        if old_photo:
            await cleaned_up(
                get_supabase,
                old_photo,
                context_1="error removing orphaned store photo",
                context_2="successfully removed orphaned store photo",
            )
        await store_invalidation()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        if filename_link:
            await cleaned_up(
                get_supabase,
                filename_link,
                context_1="error removing orphaned store photo",
                context_2="successfully removed orphaned store photo",
            )
        logger.error("database error while updating store for user '%s'", user_id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        if filename_link:
            await cleaned_up(
                get_supabase,
                filename_link,
                context_1="error removing orphaned store photo",
                context_2="successfully removed orphaned store photo",
            )
        logger.exception("error while updating store for user '%s'", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("store: %s, updated successfully", store_map.id)
    return {"message": "store updated"}


async def approve_stores(slug, db, payload):
    user_id = payload.get("user_id")
    owner = payload.get("role")
    if not user_id or owner != "Owner":
        logger.warning("unauthorized attempt at approve_storea endpoint")
        raise HTTPException(status_code=401, detail="restricted access")
    approved = (
        await db.execute(
            select(Store).where(Store.slug == slug, ~Store.is_deleted, ~Store.approved)
        )
    ).scalar_one_or_none()
    if not approved:
        logger.error("owner tried approving a store that is not eligible for approval")
        raise HTTPException(status_code=400, detail="eligible store not found")
    approved.approved = True
    approved.founded = datetime.now(timezone.utc)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error("database error while approving store '%s'", slug)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while approving store '%s'", slug)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("store: %s, approved successfully", slug)
    return {"message": "store approved"}


async def add_finance_details(store_id, finance_details, db, payload, cipher):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at add_finance_details endpoint")
        raise HTTPException(
            status_code=401, detail="unauthorized, you must be a registered user"
        )
    store_check = (
        await db.execute(
            select(Store)
            .options(selectinload(Store.accounts))
            .where(Store.id == store_id, Store.user_owners.any(User.id == user_id))
        )
    ).scalar_one_or_none()
    if not store_check:
        logger.error(
            "user: %s, tried to add finance details to a store not assigned, store: %s",
            user_id,
            store_id,
        )
        raise HTTPException(status_code=404, detail="store not assigned")
    if store_check.account.id:
        logger.warning(
            "user: %s, tried to add finance details more than once to store: %s",
            user_id,
            store_id,
        )
        raise HTTPException(
            status_code=400, detail="finance details can only be added once"
        )
    acc_num = cipher.encrypt(finance_details.account_number.encode())
    tax_num = cipher.encrypt(finance_details.tax_identification_number.encode())
    id_num = cipher.encrypt(finance_details.identification_number.encode())
    account_detail = StoreAccount(
        store_id=store_check.id,
        account_name=finance_details.account_name,
        account_number=acc_num,
        tax_identification_number=tax_num,
        identification_number=id_num,
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
            select(Store).where(
                Store.id == store_id, Store.user_owners.any(User.id == user_id)
            )
        )
    ).scalar_one_or_none()
    if not store_check:
        logger.error(
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
        .where(Store.id == store_id, Store.approved)
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
    data = PaginatedMetadata[AddressDetails](
        items=[AddressDetails.model_validate(add.Address) for add in store_address],
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


async def view_store(position, db, payload):
    user_id = payload.get("user_id")
    cache_key = f"store_view:{position}:{user_id}"
    store_cache = await cache(cache_key)
    if store_cache:
        logger.info(f"cache hit for user '{user_id}' at view store endpoint")
        return StandardResponse(**store_cache)
    if position not in ["owner", "staff"]:
        logger.warning(
            "user: %s, tried accessing a restricted endpoint 'view_store endpoint' with position: %s",
            user_id,
            position,
        )
        raise HTTPException(status_code=403, detail="restricted access")
    query = (
        store_owners.c.users_id == user_id
        if position == "owner"
        else store_staffs.c.users_id == user_id
    )
    stmt = (
        select(Store)
        .outerjoin(store_owners, Store.id == store_owners.c.stores_id)
        .outerjoin(store_staffs, Store.id == store_staffs.c.stores_id)
        .where(query, ~Store.is_deleted)
    )
    store_type = (await db.execute(stmt)).scalars().all()
    if not store_type:
        msg = (
            "you do not own any store yet"
            if position == "owner"
            else "you do not work in any store yet"
        )
        logger.info("search for stores returned an empty list")
        return StandardResponse(
            status="success",
            message=msg,
            data=None,
        )
    items = []
    datas = [StoreResponse.model_validate(s_t) for s_t in store_type]
    for data, s_type in zip(datas, store_type):
        data.business_logo = (
            get_public_url(s_type.business_logo) if s_type.business_logo else None
        )
        data.store_photo = get_public_url(s_type.store_photo)  # type: ignore
        items.append(data)
    message = "stores you own" if position == "owner" else "stores you work in"
    response = StandardResponse(status="success", message=message, data=items)
    await cached(cache_key, response, ttl=180)
    logger.info("search for stores returned data")
    return response


async def search_stores(search, search_value, seed, page, limit, db):
    if search not in ["category", "sub_category", "store_name", "product_name"]:
        logger.warning(
            "invalid field in search attempted at the search stores endpoint"
        )
        raise HTTPException(
            status_code=400,
            detail="invalid search, only 'category','sub_category','store_name' and 'product_name' are allowed",
        )
    offset = (page - 1) * limit
    version = await cache_version("store_key")
    cache_key = f"store_view:v{version}:{seed}:{search}:{search_value}:{page}:{limit}"
    store_cache = await cache(cache_key)
    if store_cache:
        logger.info(f"cache hit for {search_value} at search stores endpoint")
        return StandardResponse(**store_cache)
    total = None
    async with db as conn:
        inner_stmt = (
            select(Product)
            .where(
                Product.store_id == Store.id,
                Product.product_name.ilike(f"%{search_value}%"),
                ~Product.is_deleted,
            )
            .order_by(Product.id.desc())
            .limit(1)
            .correlate(Store)
            .lateral("product")
        )
        product_aliase = aliased(Product, inner_stmt, name="product_aliase")
        filter_column = {
            "category": Store.category_name.ilike(f"%{search_value}%"),
            "sub_category": cast(Store.sub_category, String).ilike(f"%{search_value}%"),
            "store_name": Store.store_name.ilike(f"%{search_value}%"),
            "product_name": product_aliase.product_name.ilike(f"%{search_value}%"),
        }[search]
        stmt = (
            select(Store, product_aliase)
            .outerjoin(product_aliase, Store.id == product_aliase.store_id)
            .where(
                filter_column,
                Store.approved,
                ~Store.is_deleted,
            )
            .order_by(func.md5(func.concat(cast(Store.id, String), str(seed))))
        )
        rows = (await conn.execute(stmt.offset(offset).limit(limit))).all()
        if not rows:
            logger.info(
                "search for '%s' stores returned an empty list",
                search_value,
            )
            return StandardResponse(
                status="success",
                message="no store available under this search",
                data=None,
            )
        count_stmt = select(func.count(Store.id))
        if search == "product_name":
            count_stmt = count_stmt.outerjoin(
                product_aliase, Store.id == product_aliase.store_id
            )
        total = (
            await conn.execute(
                count_stmt.where(
                    filter_column,
                    Store.approved,
                    ~Store.is_deleted,
                )
            )
        ).scalar() or 0
        logger.info("total stores found is '%s'", total)
    items = []
    for s_type, prod in rows:
        data = StoreResponse.model_validate(s_type)
        data.business_logo = (
            get_public_url(s_type.business_logo) if s_type.business_logo else None
        )
        data.store_photo = get_public_url(s_type.store_photo)  # type: ignore
        if prod:
            prod_data = ProductRes.model_validate(prod)
            prod_data.primary_image = get_public_url(prod.primary_image)  # type: ignore
            data.featured_product = [prod_data]
        items.append(data)
    data_obj = PaginatedMetadata[StoreResponse](
        items=items,
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    response = StandardResponse(
        status="success",
        message=f"available '{search_value}' stores",
        data=data_obj,
    )
    await cached(cache_key, response, ttl=36000)
    logger.info("search for stores returned data")
    return response


async def add_owner_staff(store_id, owner_id, staff_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at add_owners_staffs endpoint")
        raise HTTPException(
            status_code=401, detail="only registered users can access this endpoint"
        )
    if not owner_id and not staff_id:
        logger.warning("user: %s, tried executing a null field", user_id)
        raise HTTPException(
            status_code=400, detail="you must add either a new staff or a new owner"
        )
    if owner_id and staff_id:
        logger.warning(
            "user: %s, tried adding a staff and owner at the same time", user_id
        )
        raise HTTPException(
            status_code=400,
            detail="you must add either a new staff or a new owner not both at once",
        )
    (await db.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": store_id}))
    store_check = (
        await db.execute(
            select(Store)
            .options(selectinload(Store.user_owners), selectinload(Store.user_staffs))
            .where(Store.id == store_id)
        )
    ).scalar_one_or_none()
    check_stmt = select(
        select(store_owners.c.users_id)
        .where(
            store_owners.c.users_id == user_id,
            store_owners.c.stores_id == store_id,
        )
        .scalar_subquery()
        .label("store_owner"),
        select(store_owners.c.users_id)
        .where(
            store_owners.c.users_id == owner_id,
            store_owners.c.stores_id == store_id,
        )
        .scalar_subquery()
        .label("already_owner"),
        select(store_owners.c.users_id)
        .where(
            store_owners.c.users_id == staff_id,
            store_owners.c.stores_id == store_id,
        )
        .scalar_subquery()
        .label("owner_already"),
        select(store_staffs.c.users_id)
        .where(
            store_staffs.c.users_id == staff_id,
            store_staffs.c.stores_id == store_id,
        )
        .scalar_subquery()
        .label("already_staff"),
        select(store_staffs.c.users_id)
        .where(
            store_staffs.c.users_id == owner_id,
            store_staffs.c.stores_id == store_id,
        )
        .scalar_subquery()
        .label("staff_already"),
        select(func.count())
        .where(store_owners.c.users_id == owner_id)
        .scalar_subquery()
        .label("owner_count"),
        select(func.count())
        .where(store_staffs.c.users_id == staff_id)
        .scalar_subquery()
        .label("staff_count"),
    )
    result = (await db.execute(check_stmt)).mappings().first()
    if not store_check:
        logger.error(
            "user: %s, tried accessing a non existent store at the add_owners_staffs endpoint",
            user_id,
        )
        raise HTTPException(status_code=404, detail="store not found")
    if not result["store_owner"]:
        logger.warning(
            "user: %s, tried accessing a restricted endpoint 'add_owners_staffs endpoint'",
            user_id,
        )
        raise HTTPException(status_code=403, detail="restricted access")
    if result["already_owner"]:
        logger.warning(
            "user: %s, tried making user '%s', an owner, when they are already an owner in the same store",
            user_id,
            owner_id,
        )
        raise HTTPException(
            status_code=400, detail="the user is already an owner of this store"
        )
    if result["owner_already"]:
        logger.warning(
            "user: %s, tried making user '%s', a staff, when they are already an owner in the same store",
            user_id,
            staff_id,
        )
        raise HTTPException(
            status_code=400, detail="this user is already an owner of this store"
        )
    if result["already_staff"]:
        logger.warning(
            "user: %s, tried making user '%s', a staff, when they are already a staff in the same store",
            user_id,
            staff_id,
        )
        raise HTTPException(
            status_code=400, detail="the user is already a staff of this store"
        )
    if result["staff_already"]:
        logger.warning(
            "user: %s, tried making user '%s', an owner, when they are already a staff in the same store",
            user_id,
            owner_id,
        )
        raise HTTPException(
            status_code=400, detail="this user is already a staff of this store"
        )
    if owner_id and result["owner_count"] > 10:
        logger.warning("owner: %s, already owns 10 stores")
        raise HTTPException(status_code=400, detail="owner already owns 10 store")
    if staff_id and result["staff_count"] > 2:
        logger.warning("staff: %s, already works in 2 stores")
        raise HTTPException(status_code=400, detail="staff already works in 2 store")
    intended_id = owner_id if owner_id else staff_id
    user_obj = await db.get(User, intended_id)
    if not user_obj:
        logger.error(
            "user: %s, inputed an invalid user_id in add_owners_staffs endpoint invalid_id: %s",
            user_id,
            intended_id,
        )
        raise HTTPException(status_code=404, detail="user not found")
    if owner_id is not None:
        store_check.user_owners.append(user_obj)
    if staff_id is not None:
        store_check.user_staffs.append(user_obj)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error(
            "database error occured at the add_owners_staffs endpoint, user afffected: %s",
            user_id,
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            "rollback occured at the add_owners_staffs endpoint, user afffected: %s",
            user_id,
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("personnel added to store: %s", store_id)
    return {"message": "personnel added"}


async def remove_staff(store_id, staff_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at delete_staff endpoint")
        raise HTTPException(
            status_code=401, detail="only registered users can access this endpoint"
        )
    (await db.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": store_id}))
    check_stmt = (
        select(Store).where(
            and_(Store.id == store_id, Store.approved),
            exists().where(
                and_(
                    store_owners.c.users_id == user_id,
                    store_owners.c.stores_id == store_id,
                )
            ),
            exists().where(
                and_(
                    store_staffs.c.users_id == staff_id,
                    store_staffs.c.stores_id == store_id,
                )
            ),
        )
    ).cte("check_stmt")
    result = await db.execute(
        select(Store)
        .options(selectinload(Store.user_staffs))
        .where(Store.id == store_id, Store.approved)
        .join(check_stmt, Store.id == check_stmt.c.id)
    )
    store_check = result.scalar_one_or_none()
    if not store_check:
        logger.error(
            "user: %s, hit a permission errror at the delete_staff endpoint",
            user_id,
        )
        raise HTTPException(
            status_code=403,
            detail="permission error, verify the store and staff before proceeding",
        )
    staff_obj = next((s for s in store_check.user_staffs if s.id == staff_id), None)
    if not staff_obj:
        logger.error(
            "an alien user id bypassed cte check,s alien_user_id: %s", staff_id
        )
        raise HTTPException(status_code=404, detail="Staff member not found in store")
    store_check.user_staffs.remove(staff_obj)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error(
            "database error occured at the delete_staff endpoint, user afffected: %s",
            user_id,
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            "rollback occured at the delete_staff endpoint, user afffected: %s",
            user_id,
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("staff '%s', removed from store: %s", staff_id, store_id)
    return {"message": "personnel deleted"}


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
        .where(
            Store.id == store_id,
            Store.user_owners.any(User.id == user_id),
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


async def remove_store(store_id, db, payload):
    user_id = payload.get("user_id")
    role = payload.get("role")
    if not user_id:
        logger.warning("unauthorized attempt at delete_store endpoint")
        raise HTTPException(
            status_code=401, detail="only registered users can access this endpoint"
        )
    allowed_roles = ["Owner", "Admin"]
    store_check = (
        await db.execute(
            select(Store)
            .options(selectinload(Store.user_owners))
            .where(
                Store.id == store_id,
                ~Store.is_deleted,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not store_check:
        logger.error(
            "user: %s, tried accessing a non existent store at the delete_store endpoint",
            user_id,
        )
        raise HTTPException(status_code=404, detail="store not found")
    owner_id = [owner.id for owner in store_check.user_owners]
    if user_id not in owner_id and role not in allowed_roles:
        logger.warning(
            "user: %s attempted a restricted endpoint (deleted store)", user_id
        )
        raise HTTPException(status_code=403, detail="restricted access")
    store_check.is_deleted = True
    store_check.approved = False
    (
        await db.execute(
            update(Address).where(Address.store_id == store_id).values(is_deleted=True)
        )
    )
    (
        await db.execute(
            update(Product).where(Product.store_id == store_id).values(is_deleted=True)
        )
    )
    (
        await db.execute(
            update(Inventory)
            .where(Inventory.store_id == store_id)
            .values(is_deleted=True)
        )
    )
    try:
        await db.commit()
        await store_invalidation()
    except IntegrityError:
        await db.rollback()
        logger.error(
            "database error occured at the delete_store endpoint, user afffected: %s",
            user_id,
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            "rollback occured at the delete_store endpoint, user afffected: %s",
            user_id,
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("store '%s', deleted", store_id)
    return {"message": "store deleted"}
