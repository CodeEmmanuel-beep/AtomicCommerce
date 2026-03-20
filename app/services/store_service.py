from fastapi import HTTPException
from app.models_sql import Store, Category, User, store_owners, store_staffs
from app.api.v1.models import StandardResponse
from app.logs.logger import get_logger
from app.api.v1.models import StoreResponse
from sqlalchemy.orm import selectinload
from sqlalchemy import func, select, text, or_
from sqlalchemy.exc import IntegrityError
import asyncio
import uuid
from app.utils.supabase_url import cleaned_up
from werkzeug.utils import secure_filename
from app.database.config import settings


logger = get_logger("store")


async def store_creation(storeobj, store_photo, db, payload, get_supabase):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at store_creation endpoint")
        raise HTTPException(
            status_code=401, detail="only registered users can own a store"
        )
    stmt = select(Store).where(Store.store_name == storeobj.store_name)
    store = (await db.execute(stmt)).scalar_one_or_none()
    if store:
        logger.error(
            "user: %s, tried duplicating store name '%s'", user_id, storeobj.store_name
        )
        raise HTTPException(status_code=400, detail="store name already taken")
    filename = None
    try:
        filename = f"{uuid.uuid4()}_{secure_filename(store_photo.filename)}"
        file_byte = await store_photo.read()
        upload_photo = await get_supabase.storage.from_(settings.BUCKET).upload(
            filename, file_byte, {"content-type": store_photo.content_type}
        )
        if hasattr(upload_photo, "error"):
            logger.error("error uploading store photo %s", upload_photo)
            raise HTTPException(status_code=500, detail="error uploading store photo")
    except Exception:
        await db.rollback()
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned store photo",
                context_2="successfully removed orphaned store photo",
            )
            logger.exception("error saving store photo")
            raise HTTPException(status_code=500, detail="error saving store photo")
    store_photo = filename
    if user_id not in storeobj.owners:
        logger.error("user: %s, tried being a third party creator")
        raise HTTPException(
            status_code=400, detail="you can not create a store you do not own"
        )
    category_gather, count_gather, user_gather = await asyncio.gather(
        db.execute(select(Category).where(Category.name == storeobj.business_type)),
        db.execute(
            select(store_owners.c.users_id, func.count(store_owners.c.stores_id))
            .where(store_owners.c.users_id.in_(storeobj.owners))
            .group_by(store_owners.c.users_id)
        ),
        db.execute(select(User).where(User.id.in_(storeobj.owners))),
    )
    user_data = user_gather.scalars().all()
    if len(user_data) != len(storeobj.owners):
        logger.warning(
            "user: %s, tried making a non-existent user a shop owner", user_id
        )
        raise HTTPException(
            status_code=400, detail="all owners must be registered users"
        )
    count = dict(count_gather.all())
    for owner_id, store_count in count.items():
        if store_count > 10:
            logger.warning("a user tried owning more than 10 stores user: %s", owner_id)
            raise HTTPException(
                status_code=400, detail="a user can not own more than 10 stores"
            )
    category = category_gather.scalar_one_or_none()
    if not category:
        logger.error("Category '%s' not found in database", storeobj.business_type)
        raise HTTPException(
            status_code=500, detail="Store category configuration error"
        )
    new_store = Store(
        store_photo=store_photo,
        store_name=storeobj.store_name,
        business_type=storeobj.business_type,
        category_id=category.id,
        store_email=storeobj.store_email,
        store_contact=storeobj.store_contact,
        user_owners=user_data,
    )
    try:
        db.add(new_store)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned store photo",
                context_2="successfully removed orphaned store photo",
            )
        logger.error("database error while creating store for user '%s'", user_id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned store photo",
                context_2="successfully removed orphaned store photo",
            )
        logger.exception("error while creating store for user '%s'", user_id)
        raise HTTPException(status_code=500, detail="internal server error")


async def add_owner_staff(store_id, owner_id, staff_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at add_owner_staff endpoint")
        raise HTTPException(
            status_code=401, detail="only registered users can access this endpoint"
        )
    (await db.execute(text("SELECT pg_advisory_xact_lock(:id)", {"id": store_id})))
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
            status_code=400, detail="the user is already an owner of this store"
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
            status_code=400, detail="the user is already a staff of this store"
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
            "user: %s, inputed an invalid user_id in add_owner_staff endpoint invalid_id: %s",
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
            "database error occured at the add_owners_staffs_endpoint, user afffected: %s",
            user_id,
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            "rollback occured at the add_owners_staffs_endpoint, user afffected: %s",
            user_id,
        )
        raise HTTPException(status_code=500, detail="internal server error")
    return {"message": "personnel added"}
