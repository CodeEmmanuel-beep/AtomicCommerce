from fastapi import HTTPException
from app.models_sql import Store, Category, User, store_owners
from app.api.v1.models import StandardResponse
from app.logs.logger import get_logger
from app.api.v1.models import StoreResponse
from sqlalchemy import func, select
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
