from fastapi import HTTPException
import uuid
from werkzeug.utils import secure_filename
from app.logs.logger import get_logger
from app.api.v1.models import (
    PaginatedMetadata,
    ProductResponse,
    StandardResponse,
    PaginatedResponse,
)
from app.database.config import settings
from app.models_sql import Product, Store, Category, User, Inventory
from sqlalchemy import select, func, text, update, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
import asyncio
import orjson
from app.utils.redis import (
    cart_global_invalidation,
    order_global_invalidation,
    product_invalidation,
    cache_version,
    cached,
    cache,
)
from app.utils.helper import file_generator
from app.utils.supabase_url import cleaned_up

logger = get_logger("products")


async def create(
    prod,
    primary_image,
    image,
    get_supabase,
    db,
    payload,
):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="user not authenticated")
    stmt = select(Store).where(
        Store.id == prod.store_id,
        or_(
            Store.user_owners.any(User.id == user_id),
            Store.user_staffs.any(User.id == user_id),
        ),
    )
    eligible = (await db.execute(stmt)).scalar_one_or_none()
    if not eligible:
        raise HTTPException(status_code=403, detail="not authorized")
    uploaded_file = []
    images = []
    tasks = []
    files_allowed = ["image/jpeg", "image/png", "image/webp"]
    try:
        if primary_image.content_type not in files_allowed:
            logger.warning(
                "user: %s, tried uploading a file with an unsupported format",
                user_id,
            )
            raise HTTPException(status_code=400, detail="file format not supported")
        filename = f"{uuid.uuid4()}_{secure_filename(primary_image.filename)}"
        file_byte = file_generator(primary_image, user_id)
        client = await get_supabase.storage.from_(settings.BUCKET).upload(
            filename, file_byte, {"content-type": primary_image.content_type}
        )
        if hasattr(client, "error"):
            logger.exception("could not upload product primary image %s", client)
            raise HTTPException(
                status_code=500, detail="error uploading product primary image"
            )
        uploaded_file.append(filename)
        logger.info("saved product primary image")
        if image is not None:
            for img in image:
                if img.content_type not in files_allowed:
                    logger.warning(
                        "user: %s, tried uploading  file with an unsupported format",
                        user_id,
                    )
                    raise HTTPException(
                        status_code=400, detail="file format not supported"
                    )
            max_image = 7
            if len(image) > max_image:
                raise HTTPException(
                    status_code=400,
                    detail=f"maximum number of images allowed is {max_image}",
                )
            file_list = [file_generator(img, user_id) for img in image]
            for file, file_byte in zip(image, file_list):
                filenames = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
                tasks.append(
                    get_supabase.storage.from_(settings.BUCKET).upload(
                        filenames, file_byte, {"content-type": file.content_type}
                    )
                )
                images.append(filenames)
            await asyncio.gather(*tasks)
            uploaded_file.extend(images)
        else:
            image = None
    except Exception as e:
        logger.exception("could not save product image")
        await db.rollback()
        if uploaded_file:
            await cleaned_up(
                get_supabase,
                uploaded_file,
                context_1="error removing orphaned product images",
                context_2="successfully removed orphaned product images",
            )
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=500, detail="could not save product primary image"
        )
    logger.info("saved product images, uploaded by user: %s", user_id)
    primary_image = filename
    category = (
        await db.execute(select(Category).where(Category.name == prod.category_name))
    ).scalar_one_or_none()
    new_product = Product(
        store_id=eligible.id,
        product_name=prod.product_name,
        primary_image=filename,
        image=orjson.dumps(images).decode("utf-8"),
        product_price=prod.product_price,
        category_id=category.id,
        product_availability=prod.product_availability,
    )
    try:
        db.add(new_product)
        await db.commit()
        await cart_global_invalidation()
        await order_global_invalidation()
        await product_invalidation()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        if uploaded_file:
            await cleaned_up(
                get_supabase,
                uploaded_file,
                context_1="error removing orphaned product images",
                context_2="successfully removed orphaned product images",
            )
        logger.error("database error while saving product data")
        raise HTTPException(status_code=400, detail="database error")
    except Exception as e:
        await db.rollback()
        if uploaded_file:
            await cleaned_up(
                get_supabase,
                uploaded_file,
                context_1="error removing orphaned product images",
                context_2="successfully removed orphaned product images",
            )
        logger.exception("error while saving product data")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail="internal server error")
    return {"status": "success", "message": "product added to shelve"}


async def product_change(prod, primary_image, image, db, payload, get_supabase):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="user not authenticated")
    stmt = (
        select(Product)
        .join(Store, Product.store_id == Store.id)
        .where(
            or_(
                Store.user_owners.any(User.id == user_id),
                Store.user_staffs.any(User.id == user_id),
            ),
            Store.id == prod.store_id,
            Product.id == prod.product_id,
            ~Product.is_deleted,
        )
        .with_for_update()
    )
    product = (await db.execute(stmt)).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=403, detail="invalid id")
    uploaded_file = []
    images = []
    tasks = []
    filename = None
    old_photo = []
    if image or primary_image is not None:
        try:
            if primary_image is not None:
                if product.primary_image:
                    old_photo.append(product.primary_image)
                allowed_types = ["image/jpeg", "image/png", "image/webp"]
                if primary_image.content_type not in allowed_types:
                    logger.warning(
                        "user: %s, tried uploading an unsupported file in product change endpoint, file_type: %s",
                        user_id,
                        primary_image.content_type,
                    )
                    raise HTTPException(
                        status_code=400, detail="file type not supported"
                    )
                filename = f"{uuid.uuid4()}_{secure_filename(primary_image.filename)}"
                file_byte = file_generator(primary_image, user_id)
                response = await get_supabase.storage.from_(settings.BUCKET).upload(
                    filename,
                    file_byte,
                    {"content-type": primary_image.content_type},
                )
                if hasattr(response, "error"):
                    logger.error("error updating product primary image %s", response)
                    raise HTTPException(status_code=500, detail="internal server error")
                logger.info("updated product primary image")
                uploaded_file.append(filename)
            if image is not None:
                if product.image and len(str(product.image)) > 2:
                    old_photo.extend(orjson.loads(product.image))
                for img in image:
                    if img.content_type not in [
                        "image/jpeg",
                        "image/png",
                        "image/webp",
                    ]:
                        logger.warning(
                            "user: %s, tried uploading an unsupported file in product change endpoint, file_type: %s",
                            user_id,
                            img.content_type,
                        )
                        raise HTTPException(
                            status_code=400, detail="file type not supported"
                        )
                max_image = 7
                if len(image) > max_image:
                    raise HTTPException(
                        status_code=400,
                        detail=f"maximum number of images allowed is {max_image}",
                    )
                file_list = [file_generator(img, user_id) for img in image]
                for file, file_byte in zip(image, file_list):
                    filenames = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
                    tasks.append(
                        get_supabase.storage.from_(settings.BUCKET).upload(
                            filenames,
                            file_byte,
                            {"content-type": file.content_type},
                        )
                    )
                    images.append(filenames)
                await asyncio.gather(*tasks)
                uploaded_file.extend(images)
                logger.info("updated product images, uploaded by user: %s", user_id)
            product.primary_image = filename if filename else product.primary_image
            product.image = (
                orjson.dumps(images).decode("utf-8") if images else product.image
            )
        except Exception as e:
            if uploaded_file:
                await cleaned_up(
                    get_supabase,
                    uploaded_file,
                    context_1="error removing orphaned product images",
                    context_2="successfully removed orphaned product images",
                )
            if isinstance(e, HTTPException):
                raise e
            logger.exception("error updating product images")
            raise HTTPException(status_code=500, detail="error saving product image")
    update_fields = ["product_name", "product_price", "product_availability"]
    for field in update_fields:
        val = getattr(prod, field, None)
        if val is not None:
            setattr(product, field, val)
    try:
        await db.commit()
        await asyncio.gather(
            cart_global_invalidation(),
            order_global_invalidation(),
            product_invalidation(),
        )
        if old_photo:
            await cleaned_up(
                get_supabase,
                old_photo,
                context_1="error removing orphaned product images",
                context_2="successfully removed orphaned product images",
            )
        logger.info("successfully updated product data")
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        if uploaded_file:
            await cleaned_up(
                get_supabase,
                uploaded_file,
                context_1="error removing orphaned product images",
                context_2="successfully removed orphaned product images",
            )
        logger.error("database error occured while updating product data")
        raise HTTPException(status_code=400, detail="database error")
    except Exception as e:
        await db.rollback()
        if uploaded_file:
            await cleaned_up(
                get_supabase,
                uploaded_file,
                context_1="error removing orphaned product images",
                context_2="successfully removed orphaned product images",
            )
        if isinstance(e, HTTPException):
            raise e
        logger.error("error occured while updating product data")
        raise HTTPException(status_code=500, detail="internal server error")
    return {"status": "success", "message": "product updated successfully"}


async def list_products(
    seed,
    db,
    page,
    limit,
):
    offset = (page - 1) * limit
    if page < 1 or limit < 1:
        raise HTTPException(
            status_code=400, detail="page number and limit must be greater than 0"
        )
    version = await cache_version("product_key")
    cache_key = f"product:{version}:{seed}:{page}:{limit}"
    product_cache = await cache(cache_key)
    if product_cache and isinstance(product_cache, dict):
        logger.info("Cache hit for products")
        return StandardResponse(**product_cache)
    total = None
    products = None
    async with db.connection() as conn:
        (await conn.execute(text("SELECT setseed(:s)"), {"s": seed}))
        stmt = (
            select(Product)
            .options(selectinload(Product.inventory))
            .where(~Product.is_deleted)
            .order_by(func.random())
        )
        products = (
            (await conn.execute(stmt.offset(offset).limit(limit))).scalars().all()
        )
        total = (await conn.execute(select(func.count(Product.id)))).scalar() or 0
    if not products:
        logger.warning("all products queried, but none found")
        return StandardResponse(
            status="success", message="there is no product available", data=None
        )
    data = PaginatedMetadata[ProductResponse](
        items=[ProductResponse.model_validate(product) for product in products],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    response = {"product data": data}
    full_response = StandardResponse(
        status="success", message="products data", data=response
    )
    await cached(cache_key, full_response, ttl=600)
    logger.info("Product data cached")
    logger.info(
        f"all products fetched successfully page={page}, limit={limit}, total={total}"
    )
    return full_response


async def search_product(product_name, category, page, limit, db):
    offset = (page - 1) * limit
    if page < 1 or limit < 1:
        raise HTTPException(
            status_code=400,
            detail="page and limit should atleast have a numerical value of 1",
        )
    version = await cache_version("product_key")
    cache_key = (
        f"product:{version}:{product_name or ''}:{category or ''}:{page}:{limit}"
    )
    product_cache = await cache(cache_key)
    if product_cache and isinstance(product_cache, dict):
        logger.info("Cache hit for searched products")
        return StandardResponse(**product_cache)
    stmt = (
        select(Product)
        .join(Category)
        .options(selectinload(Product.inventory))
        .where(~Product.is_deleted)
    )
    if product_name is None and category is None:
        logger.error("user tried to execute an empty request")
        raise HTTPException(status_code=400, detail="all fields can not be left blank")
    if product_name is not None:
        logger.info("filtering products by product name %s", product_name)
        stmt = stmt.where(Product.product_name.ilike(f"%{product_name}%"))
    if category is not None:
        logger.info("filltering products by category %s", category)
        stmt = stmt.where(Category.name.ilike(f"%{category}%"))
    result = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    if not result:
        return StandardResponse(
            status="success", message="your search has returned 0 result", data=None
        )
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar() or 0
    logger.info("total products querried %s", total)
    data = PaginatedMetadata[ProductResponse](
        items=[ProductResponse.model_validate(res) for res in result],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    response = {"product data": data}
    full_response = StandardResponse(
        status="success", message="products data", data=response
    )
    await cached(cache_key, full_response, ttl=600)
    logger.info("cached searched products")
    return full_response


async def delete_one(store_id, product_id, background_task, db, payload, get_supabase):
    user_id = payload.get("user_id")
    username = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=403, detail="Unauthorized access.")
    store_product = (
        await db.execute(
            select(Product)
            .join(Store, Product.store_id == Store.id)
            .where(
                Product.id == product_id,
                Store.id == store_id,
                or_(
                    Store.user_owners.any(User.id == user_id),
                    Store.user_staffs.any(User.id == user_id),
                ),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not store_product:
        logger.warning(
            f"{username}, tried deleting a product with invalid credentials, product id: {product_id}"
        )
        raise HTTPException(status_code=403, detail="invalid credentials")
    store_product.is_deleted = True
    (
        await db.execute(
            update(Inventory)
            .where(Inventory.product_id == product_id)
            .values(is_deleted=True)
        )
    )
    files_to_delete = orjson.loads(store_product.image) if store_product.image else []
    data_id = store_product.id
    try:
        await db.commit()
        background_task.add_task(
            cart_global_invalidation,
        )
        background_task.add_task(
            order_global_invalidation,
        )
        background_task.add_task(
            product_invalidation,
        )
        if files_to_delete:
            background_task.add_task(
                cleaned_up,
                get_supabase,
                files_to_delete,
                context_1="error removing orphaned product images",
                context_2="successfully removed orphaned product images",
            )
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        logger.exception(
            "error occured while delete product with product_id %s", product_id
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("deleted product %s", product_id)
    return {
        "status": "success",
        "message": "deleted product",
        "data": {
            "id": data_id,
            "username": username,
            "deleted": "Yes",
        },
    }
