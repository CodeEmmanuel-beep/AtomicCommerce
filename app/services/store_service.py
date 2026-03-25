from fastapi import HTTPException
from app.models_sql import (
    Store,
    Category,
    User,
    store_owners,
    store_staffs,
    StoreAddress,
    Review,
    Order,
)
from datetime import datetime, timezone
from app.logs.logger import get_logger
from sqlalchemy.orm import selectinload
from sqlalchemy import func, select, text, and_, exists
from sqlalchemy.exc import IntegrityError
import asyncio
from app.utils.helper import view_store_helper, upload_photo_helper
from app.utils.supabase_url import cleaned_up
from app.utils.redis import store_invalidation
import re
import regex

logger = get_logger("store")


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
    if not regex.fullmatch(r"^[\p{L}\s]+$", storeobj.store_name):
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
    if not regex.fullmatch(r"^[\p{L}\s]+$", storeupdate.store_name):
        raise HTTPException(status_code=400, detail="store names should be in letters")
    stmt = select(Store).where(
        Store.id == storeupdate.store_id,
        Store.approved,
        Store.user_owners.any(User.id == user_id),
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
    if storeupdate.motto:
        store_map.motto = storeupdate.motto
    if storeupdate.store_description:
        store_map.store_description = storeupdate.store_description
    if storeupdate.store_contact:
        store_map.store_contact = storeupdate.store_contact
    if storeupdate.business_type:
        store_map.business_type = storeupdate.business_type
    if storeupdate.store_email:
        store_map.store_email = storeupdate.store_email
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
        logger.error("database error while creating store for user '%s'", user_id)
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
        logger.exception("error while creating store for user '%s'", user_id)
        raise HTTPException(status_code=500, detail="internal server error")


async def approve_stores(store_id, db, payload):
    user_id = payload.get("user_id")
    owner = payload.get("role")
    if not user_id or owner != "Owner":
        logger.warning("unauthorized attempt at approve_storea endpoint")
        raise HTTPException(status_code=401, detail="restricted")
    approved = (
        await db.execute(
            select(Store).where(
                Store.id == store_id, ~Store.is_deleted, ~Store.approved
            )
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
        logger.error("database error while approving store '%s'", store_id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while approving store '%s'", store_id)
        raise HTTPException(status_code=500, detail="internal server error")


async def view_store_data(store_id, db):
    target_store = select(
        (select(Store).where(Store.id == store_id, Store.approved))
        .scalar_subquery()
        .label("approved_store"),
        (
            select(func.count(Order.id))
            .where(Order.store_id == store_id)
            .scalar_subquery()
            .label("store_orders")
        ),
        select(func.max(Order.created_at))
        .where(Order.store_id == store_id)
        .scalar_subquery()
        .label("last_order"),
        select(func.count(Review.ratings))
        .where(Review.store_id == store_id)
        .scalar_subquery()
        .label("total_ratings"),
        select(func.avg(Review.ratings))
        .where(Review.store_id == store_id)
        .scalar_subquery()
        .label("avg_ratings"),
    )
    result = await db.execute(target_store)
    row = result.first()
    if not row.approved_store:
        logger.error("user tried accessing an unvailable store: %s", store_id)
        raise HTTPException(status_code=404, detail="store not found")
    (
        approved_store,
        store_orders,
        last_order,
        store_total_ratings,
        store_average_ratings,
    ) = row
    return {
        "store_total_orders": store_orders or 0,
        "last_order": last_order,
        "store_total_ratings": store_total_ratings or 0,
        "store_average_ratings": round(float(store_average_ratings or 0), 2),
    }


async def view_store_deetails(store_id, db):
    target_store = (
        await db.execute(select(Store).where(Store.id == store_id, Store.approved))
    ).scalar_one_or_none()
    if not target_store:
        logger.error("user tried accessing an unvailable store: %s", store_id)
        raise HTTPException(status_code=404, detail="store not found")
    data = {
        "business_logo": target_store.business_logo,
        "store_previous_name": target_store.store_previous_name,
        "motto": target_store.motto,
        "store_description": target_store.store_description,
    }
    return {k: v for k, v in data.items() if v is not None}


async def view_stores_by_business_type(seed, business_type, page, limit, db):
    return await view_store_helper(
        seed, business_type, Store.business_type, page, limit, db
    )


async def view_stores_by_product_name(seed, product_name, page, limit, db):
    return await view_store_helper(
        seed, product_name, Store.category.product_name, page, limit, db
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
    return {"message": "personnel added"}


async def delete_staff(store_id, staff_id, db, payload):
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
    return {"message": "personnel deleted"}
