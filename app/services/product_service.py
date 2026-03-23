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
from app.models_sql import Product, User, Category
from sqlalchemy import select, func, text
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
from app.utils.supabase_url import cleaned_up

logger = get_logger("products")


async def create(
    prod,
    get_supabase,
    db,
    payload,
):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="user not authenticated")
    stmt = select(User).where(User.id == user_id)
    admin = (await db.execute(stmt)).scalar_one_or_none()
    if not admin or admin.role not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="not authorized")
    uploaded_file = []
    images = []
    tasks = []
    try:
        filename = f"{uuid.uuid4()}_{secure_filename(prod.primary_image.filename)}"
        file_byte = await prod.primary_image.read()
        client = await get_supabase.storage.from_(settings.BUCKET).upload(
            filename, file_byte, {"content-type": prod.primary_image.content_type}
        )
        if hasattr(client, "error"):
            logger.exception("could not upload product primary image %s", client)
            raise HTTPException(
                status_code=500, detail="error uploading product primary image"
            )
        uploaded_file.append(filename)
        logger.info("saved product primary image")
        if prod.image is not None:
            max_image = 7
            if len(prod.image) > max_image:
                raise HTTPException(
                    status_code=400,
                    detail=f"maximum number of images allowed is {max_image}",
                )
            read_files = [file.read() for file in prod.image]
            file_byte_list = await asyncio.gather(*read_files)
            for file, file_byte in zip(prod.image, file_byte_list):
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
            prod.image = None
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
    prod.primary_image = filename
    new_product = Product(
        product_name=prod.product_name,
        primary_image=filename,
        image=orjson.dumps(images).decode("utf-8"),
        product_price=prod.product_price,
        category_id=prod.category_id,
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


async def product_change(prod, db, payload, get_supabase):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="user not authenticated")

    stmt = select(User).where(User.id == user_id)
    admin = (await db.execute(stmt)).scalar_one_or_none()
    if not admin or admin.role not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="not authorized")
    stmt = select(Product).where(Product.id == prod.product_id).with_for_update()
    product = (await db.execute(stmt)).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=403, detail="invalid id")
    uploaded_file = []
    images = []
    tasks = []
    old_photo = []
    if prod.image or prod.primary_image is not None:
        try:
            if prod.primary_image is not None:
                if product.primary_image:
                    old_photo.append(product.primary_image)
                filename = (
                    f"{uuid.uuid4()}_{secure_filename(prod.primary_image.filename)}"
                )
                file_byte = await prod.primary_image.read()
                response = await get_supabase.storage.from_(settings.BUCKET).upload(
                    filename,
                    file_byte,
                    {"content-type": prod.primary_image.content_type},
                )
                if hasattr(response, "error"):
                    logger.error("error updating product primary image %s", response)
                    raise HTTPException(status_code=500, detail="internal server error")
                logger.info("updated product primary image")
                product.primary_image = filename
                uploaded_file.append(filename)
            if prod.image is not None:
                if product.image and len(str(product.image)) > 2:
                    old_photo.extend(orjson.loads(product.image))
                max_image = 7
                if len(prod.image) > max_image:
                    raise HTTPException(
                        status_code=400,
                        detail=f"maximum number of images allowed is {max_image}",
                    )
                read_tasks = [file.read() for file in prod.image]
                file_byte_list = await asyncio.gather(*read_tasks)
                for file, file_byte in zip(prod.image, file_byte_list):
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
                product.image = orjson.dumps(images).decode("utf-8")
                uploaded_file.extend(images)
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
    if prod.product_name is not None:
        product.product_name = prod.product_name
    if prod.product_price is not None:
        product.product_price = prod.product_price
    if prod.product_availability is not None:
        product.product_availability = prod.product_availability
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
    (await db.execute(text("SELECT setseed(:s)"), {"s": seed}))
    version = await cache_version("product_key")
    cache_key = f"product:{version}:{seed}:{page}:{limit}"
    product_cache = await cache(cache_key)
    if product_cache and isinstance(product_cache, dict):
        logger.info("Cache hit for products")
        return StandardResponse(**product_cache)
    stmt = select(Product).where(~Product.is_deleted).order_by(func.random())
    total = (await db.execute(select(func.count(Product.id)))).scalar() or 0
    products = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
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
    stmt = select(Product).join(Category).where(~Product.is_deleted)
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


async def delete_one(product_id, db, payload, get_supabase):
    user_id = payload.get("user_id")
    username = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=403, detail="Unauthorized access.")
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if not user or user.role not in ["Admin", "Owner"]:
        logger.warning(
            f"{username}, tried deleting a product without admin powers, product id: {product_id}"
        )
        raise HTTPException(status_code=403, detail="Not authorized")
    stmt = select(Product).where(Product.id == product_id)
    data = (await db.execute(stmt)).scalar_one_or_none()
    if not data:
        logger.warning(
            f"{username}, tried deleting a nonexistent product, product id: {product_id}"
        )
        raise HTTPException(status_code=404, detail="invalid field")
    data.is_deleted = True
    files_to_delete = orjson.loads(data.image) if data.image else []
    try:
        await db.commit()
        await asyncio.gather(
            cart_global_invalidation(),
            order_global_invalidation(),
            product_invalidation(),
        )
        if files_to_delete:
            await cleaned_up(
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
            "id": data.id,
            "username": username,
            "deleted": "Yes",
        },
    }
