from fastapi import HTTPException
from app.models_sql import (
    Store,
    Category,
    User,
    store_owners,
    store_staffs,
    StoreAddress,
    StoreAccount,
    Review,
    Order,
    Payment,
    Product,
)
from app.api.v1.models import (
    StoreAccountResponse,
    PaginatedMetadata,
    PaginatedResponse,
    StandardResponse,
    StoreAddressDetails,
)
from datetime import datetime, timezone
from app.logs.logger import get_logger
from sqlalchemy.orm import selectinload
from sqlalchemy import func, select, text, and_, exists, cast, Date, Float, update
from sqlalchemy.exc import IntegrityError
from app.utils.helper import view_store_helper, upload_photo_helper
from app.utils.supabase_url import cleaned_up
from app.utils.redis import store_invalidation, cache, cached
import re
from datetime import date
from dateutil.relativedelta import relativedelta
import regex

logger = get_logger("store")

store_name_pattern = regex.compile(r"^[\p{L}\s]+$")


def generate_slug(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s_-]+", "-", name)
    name = re.sub(r"^-+|-+$", "", name)
    return name


async def store_creation(storeobj, store_photo, db, payload, get_supabase):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at store_creation endpoint")
        raise HTTPException(
            status_code=401, detail="only registered users can own a store"
        )
    if not store_name_pattern.fullmatch(storeobj.store_name):
        raise HTTPException(status_code=400, detail="store names should be in letters")
    store_slug = generate_slug(storeobj.store_name)
    stmt = select(Store).where(Store.slug == store_slug)
    existing_slug = (await db.execute(stmt)).scalar_one_or_none()
    if existing_slug:
        logger.warning("Slug collision for name: %s", storeobj.store_name)
        raise HTTPException(
            status_code=400, detail="This store name is too similar to an existing one"
        )
    if user_id not in storeobj.owners:
        logger.error("user: %s, tried being a third party creator")
        raise HTTPException(
            status_code=400, detail="you can not create a store you do not own"
        )
    category_stmt = await db.execute(
        select(Category).where(Category.name == storeobj.business_type)
    )
    count_stmt = await db.execute(
        select(store_owners.c.users_id, func.count(store_owners.c.stores_id))
        .where(store_owners.c.users_id.in_(storeobj.owners))
        .group_by(store_owners.c.users_id)
    )
    user_data = (
        (await db.execute(select(User).where(User.id.in_(storeobj.owners))))
        .scalars()
        .all()
    )
    if len(user_data) != len(storeobj.owners):
        logger.warning(
            "user: %s, tried making a non-existent user a shop owner", user_id
        )
        raise HTTPException(
            status_code=400, detail="all owners must be registered users"
        )
    count = dict(count_stmt.all())
    for owner_id, store_count in count.items():
        if store_count > 10:
            logger.warning("a user tried owning more than 10 stores user: %s", owner_id)
            raise HTTPException(
                status_code=400, detail="a user can not own more than 10 stores"
            )
    category = category_stmt.scalar_one_or_none()
    if not category:
        logger.error("Category '%s' not found in database", storeobj.business_type)
        raise HTTPException(
            status_code=500, detail="Store category configuration error"
        )
    store_photo = await upload_photo_helper(store_photo, db, payload, get_supabase)
    new_store = Store(
        store_photo=store_photo,
        store_name=storeobj.store_name,
        slug=store_slug,
        business_type=storeobj.business_type,
        category_id=category.id,
        store_email=storeobj.store_email,
        store_contact=storeobj.store_contact,
        user_owners=user_data,
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


async def approve_stores(slug, db, payload):
    user_id = payload.get("user_id")
    owner = payload.get("role")
    if not user_id or owner != "Owner":
        logger.warning("unauthorized attempt at approve_storea endpoint")
        raise HTTPException(status_code=401, detail="restricted")
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
    address_detail = StoreAddress(
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


async def view_store_data(store_id, db):
    cache_key = f"store_data:{store_id}"
    cached_data = await cache(cache_key)
    if cached_data:
        logger.info("cache hit at view store data endpoint for store %s", store_id)
        return cached_data
    store_exists = (
        await db.execute(select(Store).where(Store.id == store_id, Store.approved))
    ).scalar_one_or_none()
    if not store_exists:
        logger.error("user tried accessing an unvailable store: %s", store_id)
        raise HTTPException(status_code=404, detail="store not found")
    target_store = select(
        func.count(Order.id)
        .where(Order.store_id == store_id)
        .scalar_subquery()
        .label("store_orders"),
        select(func.max(Order.created_at))
        .where(Order.store_id == store_id)
        .scalar_subquery()
        .label("last_order"),
        select(func.count(Review.ratings))
        .where(Review.store_id == store_id)
        .scalar_subquery()
        .label("total_ratings"),
        select(func.avg(cast(Review.ratings, Float)))
        .where(Review.store_id == store_id)
        .scalar_subquery()
        .label("avg_ratings"),
    )
    result = await db.execute(target_store)
    row = result.first()
    (
        store_orders,
        last_order,
        store_total_ratings,
        store_average_ratings,
    ) = row
    data = {
        "store_total_orders": store_orders or 0,
        "last_order": last_order,
        "store_total_ratings": store_total_ratings or 0,
        "store_average_ratings": round(float(store_average_ratings or 0), 2),
    }
    await cached(cache_key, data, ttl=300)
    logger.info("data returned at view store data endpoint for store: %s", store_id)
    return data


async def view_store_details(slug, db):
    cache_key = f"store_details:{slug}"
    cached_data = await cache(cache_key)
    if cached_data:
        logger.info("cache hit at view store details endpoint for store: %s", slug)
        return cached_data
    target_store = (
        await db.execute(select(Store).where(Store.slug == slug, Store.approved))
    ).scalar_one_or_none()
    if not target_store:
        logger.error("user tried accessing an unvailable store: %s", slug)
        raise HTTPException(status_code=404, detail="store not found")
    data = {
        "store_previous_name": target_store.store_previous_name,
        "motto": target_store.motto,
        "store_description": target_store.store_description,
        "founded": target_store.founded,
    }
    data = {k: v for k, v in data.items() if v is not None}
    await cached(cache_key, data, ttl=300)
    logger.info(
        "data returned at view store details endpoint for store: %s", target_store.id
    )
    return data


async def view_overall_performance(slug, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at the view overall performance endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    cache_key = f"overall_performance:{slug}"
    cached_data = await cache(cache_key)
    if cached_data:
        logger.info(
            "cache hit at the view overall performance endpoint for store: %s", slug
        )
        return cached_data
    target_store = (
        await db.execute(
            select(Store).where(
                Store.slug == slug,
                Store.user_owners.any(User.id == user_id),
                Store.approved,
            )
        )
    ).scalar_one_or_none()
    if not target_store:
        logger.warning("user: %s, tried experienced permission err: %s", user_id, slug)
        raise HTTPException(status_code=403, detail="restricted access")
    today = date.today()
    if today < target_store.founded + relativedelta(months=1):
        return {
            "message": "performance statistics are revealed one month after onboarding"
        }
    total_gross_sales = (
        await db.execute(
            select(func.sum(Payment.amount_paid))
            .join(Order, Order.id == Payment.order_id)
            .where(
                Order.store_id == target_store.id, Payment.payment_status == "approved"
            )
        ).scalar()
        or 0
    )
    daily_sales = (
        select(
            cast(Payment.payment_date, Date).label("day"),
            func.sum(Payment.amount_paid).label("daily_sale"),
        )
        .join(Order, Payment.order_id == Order.id)
        .where(Order.store_id == target_store.id, Payment.payment_status == "approved")
        .group_by(cast(Payment.payment_date, Date))
        .cte("daily_turnover")
    )
    avg_daily = select(func.avg(daily_sales.c.daily_sale))
    average_sales = (await db.execute(avg_daily)).scalar() or 0
    average_sales_per_day = round(float(average_sales or 0), 2)
    extreme_sale_row = (
        select(Payment.payment_date, Payment.amount_paid)
        .join(Order, Order.id == Payment.order_id)
        .where(Order.store_id == target_store.id, Payment.payment_status == "approved")
    )
    lowest_sale_row = (
        await db.execute(extreme_sale_row.order_by(Payment.amount_paid.asc()).limit(1))
    ).first()
    lowest_sale = (
        {"date": lowest_sale_row[0], "sales": float(lowest_sale_row[1])}
        if lowest_sale_row
        else None
    )
    highest_sale_row = (
        await db.execute(extreme_sale_row.order_by(Payment.amount_paid.desc()).limit(1))
    ).first()
    highest_sale = (
        {"date": highest_sale_row[0], "sales": float(highest_sale_row[1])}
        if highest_sale_row
        else None
    )
    average_sales_per_week = round(average_sales_per_day * 7, 2)
    average_sales_per_month = round(average_sales_per_day * 30, 2)
    data = {
        "total_gross_sales": round(float(total_gross_sales or 0), 2),
        "highest_sales": highest_sale,
        "lowest_sales": lowest_sale,
        "average_sales_per_day": average_sales_per_day or 0,
        "average_sales_per_week": average_sales_per_week or 0,
        "average_sales_per_month": average_sales_per_month or 0,
    }
    await cached(cache_key, data, ttl=300)
    logger.info(
        "data returned at view overall performance endpoint for store: %s", slug
    )
    return data


async def view_current_performance(slug, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at the view current performance endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    cache_key = f"current_performance:{slug}"
    cached_data = await cache(cache_key)
    if cached_data:
        logger.info(
            "cache hit at the view current performance endpoint for store: %s", slug
        )
        return cached_data
    target_store = (
        await db.execute(
            select(Store).where(
                Store.slug == slug,
                Store.user_owners.any(User.id == user_id),
                Store.approved,
            )
        )
    ).scalar_one_or_none()
    if not target_store:
        logger.warning("user: %s, tried experienced permission err: %s", user_id, slug)
        raise HTTPException(status_code=403, detail="restricted access")
    today = date.today()
    gross_sales_this_month = (
        await db.execute(
            select(func.sum(Payment.amount_paid))
            .join(Order, Payment.order_id == Order.id)
            .where(
                Order.store_id == target_store.id,
                Payment.payment_status == "approved",
                Payment.payment_date >= today.replace(day=1),
            )
        ).scalar()
        or 0
    )
    extreme_sale_row = (
        select(Payment.payment_date, Payment.amount_paid)
        .join(Order, Order.id == Payment.order_id)
        .where(
            Order.store_id == target_store.id,
            Payment.payment_status == "approved",
            Payment.payment_date >= today.replace(day=1),
        )
    )
    turnover = (
        select(
            cast(Payment.payment_date, Date),
            func.sum(Payment.amount_paid).label("daily_sum"),
        )
        .join(Order, Payment.order_id == Order.id)
        .where(
            Order.store_id == target_store.id,
            Payment.payment_status == "approved",
            Payment.payment_date >= today.replace(day=1),
        )
        .group_by(cast(Payment.payment_date, Date))
        .cte("monthly_average")
    )
    result = select(func.avg(cast(turnover.c.daily_sum, Float)))
    daily_avg = (await db.execute(result)).scalar() or 0
    lowest_sale_row = (
        await db.execute(extreme_sale_row.order_by(Payment.amount_paid.asc()).limit(1))
    ).first()
    lowest_sale = (
        {"date": lowest_sale_row[0], "sales": float(lowest_sale_row[1])}
        if lowest_sale_row
        else None
    )
    highest_sale_row = (
        await db.execute(extreme_sale_row.order_by(Payment.amount_paid.desc()).limit(1))
    ).first()
    highest_sale = (
        {"date": highest_sale_row[0], "sales": float(highest_sale_row[1])}
        if highest_sale_row
        else None
    )
    today = date.today()
    ratings_orders__check = select(
        (
            select(func.count(Order.id))
            .where(
                Order.store_id == target_store.id,
                Order.created_at >= today.replace(day=1),
            )
            .scalar_subquery()
        ),
        select(func.max(Order.created_at))
        .where(
            Order.store_id == target_store.id, Order.created_at >= today.replace(day=1)
        )
        .scalar_subquery(),
        select(func.count(Review.ratings))
        .where(
            Review.store_id == target_store.id,
            Review.date_of_review >= today.replace(day=1),
        )
        .scalar_subquery(),
        select(func.avg(cast(Review.ratings, Float)))
        .where(
            Review.store_id == target_store.id,
            Review.date_of_review >= today.replace(day=1),
        )
        .scalar_subquery(),
    )
    result_check = await db.execute(ratings_orders__check)
    row = result_check.first()
    orders, last_order, ratings, avg_ratings = row
    data = {
        "orders_this_month": orders,
        "day_of_last_order": last_order,
        "total_ratings_this_month": ratings or 0,
        "average_ratings_this_month": round(float(avg_ratings or 0), 2),
        "gross_sales_this_month": round(float(gross_sales_this_month or 0), 2),
        "highest_sales": highest_sale,
        "lowest_sales": lowest_sale,
        "daily_average": round(float(daily_avg or 0), 2),
    }
    await cached(cache_key, data, ttl=300)
    logger.info(
        "data returned at view current performance endpoint for store: %s", slug
    )
    return data


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
        select(StoreAddress, func.count(StoreAddress.id).over().label("total_count"))
        .join(Store, StoreAddress.store_id == Store.id)
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
    data = PaginatedMetadata[StoreAddressDetails](
        items=[
            StoreAddressDetails.model_validate(add.StoreAddress)
            for add in store_address
        ],
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


async def view_stores_by_category(seed, category_name, page, limit, db):
    return await view_store_helper(
        seed, category_name, Store.category.name, page, limit, db
    )


async def view_stores_by_business_type(seed, business_type, page, limit, db):
    return await view_store_helper(
        seed, business_type, Store.business_type, page, limit, db
    )


async def view_stores_by_product_name(seed, product_name, page, limit, db):
    return await view_store_helper(
        seed, product_name, Store.products.product_name, page, limit, db
    )


async def view_stores_by_store_name(seed, store_name, page, limit, db):
    return await view_store_helper(seed, store_name, Store.store_name, page, limit, db)


async def add_owner_staff(store_id, owner_id, staff_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at add_owners_staffs endpoint")
        raise HTTPException(
            status_code=401, detail="only registered users can access this endpoint"
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
    if owner_id and result["already_owner"]:
        logger.warning(
            "user: %s, tried making owner '%s', when they are already an owner in the same store",
            user_id,
            owner_id,
        )
        raise HTTPException(
            status_code=400, detail="the user is already an owner of this store"
        )
    if staff_id and result["owner_already"]:
        logger.warning(
            "user: %s, tried making staff '%s', when they are already an owner in the same store",
            user_id,
            staff_id,
        )
        raise HTTPException(
            status_code=400, detail="this user is already an owner of this store"
        )
    if staff_id and result["already_staff"]:
        logger.warning(
            "user: %s, tried making staff '%s', when they are already a staff in the same store",
            user_id,
            staff_id,
        )
        raise HTTPException(
            status_code=400, detail="the user is already a staff of this store"
        )
    if owner_id and result["already_staff"]:
        logger.warning(
            "user: %s, tried making owner '%s', when they are already a staff in the same store",
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


async def remove_store(store_id, db, payload):
    user_id = payload.get("user_id")
    role = payload.get("role")
    if not user_id:
        logger.warning("unauthorized attempt at delete_store endpoint")
        raise HTTPException(
            status_code=401, detail="only registered users can access this endpoint"
        )
    allowed_roles = ["Owner", "Admin"]
    (await db.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": store_id}))
    store_check = (
        await db.execute(
            select(Store)
            .options(selectinload(Store.user_owners), selectinload(Store.products))
            .where(
                Store.id == store_id,
                ~Store.is_deleted,
            )
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
            update(Product).where(Product.store_id == store_id).values(is_deleted=False)
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
