from fastapi import HTTPException, status, Response
import uuid
from werkzeug.utils import secure_filename
from app.logs.logger import get_logger
from app.api.v1.schemas import (
    PaginatedMetadata,
    ProductResponse,
    StandardResponse,
    PaginatedResponse,
    ProductImageResponse,
)
from app.database.config import settings
from app.models import Product, Category, Inventory, ProductImage, SubCategory, Store
from sqlalchemy import select, func, cast, update, String, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
import asyncio
from app.utils.redis import (
    cart_global_invalidation,
    order_global_invalidation,
    product_invalidation,
    cache_version,
    cached,
    cache,
)
from app.utils.helper import file_generator, upload_photo_helper, store_auth
from app.utils.supabase_url import cleaned_up

logger = get_logger("products")


async def create(
    store_id,
    sub_category_name,
    product_name,
    product_type,
    product_size,
    product_description,
    product_price,
    primary_image,
    get_supabase,
    db,
    payload,
):
    user_id = await store_auth(store_id, db, payload)
    stmt = select(Store).where(Store.id == store_id)
    eligible = (await db.execute(stmt)).scalar_one_or_none()
    if not eligible:
        logger.warning(
            "unauthorized attempt to query store: %s",
            store_id,
        )
        raise HTTPException(status_code=403, detail="not authorized")
    filename = None
    files_allowed = ("image/jpeg", "image/png", "image/webp")
    try:
        if primary_image.content_type not in files_allowed:
            logger.warning(
                "user: %s, tried uploading a file with an unsupported format",
                user_id,
            )
            raise HTTPException(status_code=400, detail="file format not supported")
        filename = f"{uuid.uuid4()}_{secure_filename(primary_image.filename)}"
        file_byte = await file_generator(primary_image, user_id)
        client = await get_supabase.storage.from_(settings.BUCKET).upload(
            filename, file_byte, {"content-type": primary_image.content_type}
        )
        if hasattr(client, "error"):
            logger.exception("could not upload product primary image %s", client)
            raise HTTPException(
                status_code=500, detail="error uploading product primary image"
            )
        logger.info("saved product primary image")
    except Exception as e:
        logger.exception("could not save product image")
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
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
    if sub_category_name.strip() not in [s.strip() for s in eligible.sub_category]:
        logger.warning("user: %s, entered an unvalid sub_category", user_id)
        raise HTTPException(
            status_code=409,
            detail="your store is not registered under this sub_category",
        )
    sub_category = (
        await db.execute(
            select(SubCategory.id).where(
                func.trim(SubCategory.name) == sub_category_name.strip(),
                SubCategory.category_id == eligible.category_id,
            )
        )
    ).scalar_one_or_none()
    if not sub_category:
        logger.warning("user: %s, entered an unvalid sub_category", user_id)
        raise HTTPException(status_code=404, detail="sub_category not found")
    new_product = Product(
        store_id=eligible.id,
        product_name=product_name,
        primary_image=filename,
        product_type=product_type,
        product_size=product_size,
        product_description=product_description,
        product_price=product_price,
        category_id=eligible.category_id,
        sub_category_id=sub_category,
    )
    try:
        db.add(new_product)
        await db.commit()
        await asyncio.gather(
            cart_global_invalidation(),
            order_global_invalidation(),
            product_invalidation(),
        )
    except HTTPException:
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned product images",
                context_2="successfully removed orphaned product images",
            )
        raise
    except IntegrityError as e:
        await db.rollback()
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned product images",
                context_2="successfully removed orphaned product images",
            )
        logger.error(f"database error while saving product data: {e}")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned product images",
                context_2="successfully removed orphaned product images",
            )
        logger.exception("error while saving product data")
        raise HTTPException(status_code=500, detail="internal server error")
    return StandardResponse(
        status="success", message="product added to shelve", data=None
    )


async def add_image(
    product_id,
    store_id,
    image,
    db,
    payload,
    get_supabase,
):
    user_id = await store_auth(store_id, db, payload)
    stmt = (
        select(Store)
        .options(selectinload(Store.products))
        .join(Product, Store.id == Product.store_id)
        .where(
            Store.id == store_id,
            Store.is_deleted.is_(False),
            Product.is_deleted.is_(False),
            Product.id == product_id,
        )
    )
    eligible = (await db.execute(stmt)).scalar_one_or_none()
    if not eligible:
        logger.warning(
            "unauthorized attempt to query store: %s",
            store_id,
        )
        raise HTTPException(status_code=404, detail="store or product not found")
    image_count = (
        await db.execute(
            select(func.count(ProductImage.id)).where(
                ProductImage.product_id == product_id, ProductImage.store_id == store_id
            )
        )
    ).scalar() or 0
    if image_count >= 5:
        logger.warning(
            "user: %s, tried uploading more than 5 images for product: %s",
            user_id,
            product_id,
        )
        raise HTTPException(status_code=400, detail="maximum of 5 images allowed")
    filename = None
    filename = await upload_photo_helper(image, payload, get_supabase)
    new_images = ProductImage(store_id=store_id, product_id=product_id, image=filename)
    try:
        db.add(new_images)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned product images",
                context_2="successfully removed orphaned product images",
            )
        logger.error("database error occurred while uploading product images")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned product images",
                context_2="successfully removed orphaned product images",
            )
        logger.exception("error occurred while uploading product images")
        raise HTTPException(status_code=500, detail="internal server error")
    return StandardResponse(
        status="success", message="product image uploaded successfully", data=None
    )


async def view_product_pics(store_id, product_id, db):
    stmt = select(ProductImage).where(
        ProductImage.product_id == product_id, ProductImage.store_id == store_id
    )
    cache_key = f"product_image:{store_id}:{product_id}"
    product_image_cache = await cache(cache_key)
    if product_image_cache:
        logger.info("Cache hit for product_images")
        return StandardResponse(**product_image_cache)
    p_image = (await db.execute(stmt)).scalars().all()
    if not p_image:
        raise HTTPException(status_code=404, detail="product images not found")
    data = [ProductImageResponse.model_validate(p) for p in p_image]
    response = StandardResponse(status="success", message="product_images", data=data)
    await cached(cache_key, response, ttl=600)
    return response


async def delete_images(store_id, product_id, image_id, db, payload, get_supabase):
    user_id = await store_auth(store_id, db, payload)
    delete_img = (
        await db.execute(
            select(ProductImage).where(
                ProductImage.id == image_id,
                ProductImage.store_id == store_id,
                ProductImage.product_id == product_id,
            )
        )
    ).scalar_one_or_none()
    if not delete_img:
        logger.warning(
            "user: %s, tried deleting an image that does not exist for store: %s",
            user_id,
            store_id,
        )
        raise HTTPException(status_code=404, detail="image not found")
    filename = delete_img.image
    try:
        await db.delete(delete_img)
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"database error while deleting product image: {e}")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while deleting product image")
        raise HTTPException(status_code=500, detail="internal server error")
    if filename:
        await cleaned_up(
            get_supabase,
            filename,
            context_1="error removing orphaned product images",
            context_2="successfully removed orphaned product images",
        )
    logger.info("successfully deleted image: %s", image_id)
    return StandardResponse(
        status="success", message="product image deleted", data=None
    )


async def product_change(
    store_id,
    product_id,
    primary_image,
    product_name,
    product_price,
    product_size,
    product_type,
    product_description,
    db,
    payload,
    get_supabase,
):
    user_id = await store_auth(store_id, db, payload)
    stmt = (
        select(Product)
        .where(
            Product.store_id == store_id,
            Product.id == product_id,
            Product.is_deleted.is_(False),
        )
        .with_for_update()
    )
    product = (await db.execute(stmt)).scalar_one_or_none()
    if not product:
        logger.warning(
            "user: %s, tried editing a non existent product, product_id: %s",
            user_id,
            product_id,
        )
        raise HTTPException(status_code=404, detail="product not found")
    filename = None
    old_photo = None
    has_changed = False
    if primary_image:
        try:
            old_photo = product.primary_image
            allowed_types = ("image/jpeg", "image/png", "image/webp")
            if primary_image.content_type not in allowed_types:
                logger.warning(
                    "user: %s, tried uploading an unsupported file in product change endpoint, file_type: %s",
                    user_id,
                    primary_image.content_type,
                )
                raise HTTPException(status_code=400, detail="file type not supported")
            filename = f"{uuid.uuid4()}_{secure_filename(primary_image.filename)}"
            file_byte = await file_generator(primary_image, user_id)
            response = await get_supabase.storage.from_(settings.BUCKET).upload(
                filename,
                file_byte,
                {"content-type": primary_image.content_type},
            )
            if hasattr(response, "error"):
                logger.error("error updating product primary image %s", response)
                raise HTTPException(status_code=500, detail="internal server error")
            logger.info("updated product primary image")
            product.primary_image = filename
            has_changed = True
        except Exception as e:
            await db.rollback()
            if filename:
                await cleaned_up(
                    get_supabase,
                    filename,
                    context_1="error removing orphaned product images",
                    context_2="successfully removed orphaned product images",
                )
            if isinstance(e, HTTPException):
                raise e
            logger.exception("error updating product images")
            raise HTTPException(status_code=500, detail="error saving product image")
    update_fields = {
        "product_name": product_name,
        "product_price": product_price,
        "product_size": product_size,
        "product_type": product_type,
        "product_description": product_description,
    }
    for attr, field in update_fields.items():
        if field is not None:
            setattr(product, attr, field)
            has_changed = True
    if not has_changed:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
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
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned product images",
                context_2="successfully removed orphaned product images",
            )
        raise
    except IntegrityError:
        await db.rollback()
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned product images",
                context_2="successfully removed orphaned product images",
            )
        logger.error("database error occurred while updating product data")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned product images",
                context_2="successfully removed orphaned product images",
            )
        logger.exception("error occurred while updating product data")
        raise HTTPException(status_code=500, detail="internal server error")
    return StandardResponse(
        status="success", message="product updated successfully", data=None
    )


async def list_products(
    seed,
    db,
    page,
    limit,
):
    offset = (page - 1) * limit
    version = await cache_version("product_key")
    cache_key = f"product:{version}:{seed}:{page}:{limit}"
    product_cache = await cache(cache_key)
    if product_cache and isinstance(product_cache, dict):
        logger.info("Cache hit for products")
        return StandardResponse(**product_cache)
    total = None
    async with db as conn:
        stmt = (
            select(Product)
            .options(selectinload(Product.inventory))
            .where(Product.is_deleted.is_(False))
            .order_by(func.md5(func.concat(cast(Product.id, String), str(seed))))
        )
        products = (
            (await conn.execute(stmt.offset(offset).limit(limit))).scalars().all()
        )
        total = (await conn.execute(select(func.count(Product.id)))).scalar() or 0
        logger.info("total products in the market: %s", total)
    if not products:
        logger.warning("all products queried, but none found")
        return StandardResponse(
            status="success", message="there is no product available", data=None
        )
    data = PaginatedMetadata[ProductResponse](
        items=[ProductResponse.model_validate(product) for product in products],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    full_response = StandardResponse(
        status="success", message="products data", data=data
    )
    await cached(cache_key, full_response, ttl=600)
    logger.info("Product data cached")
    logger.info(
        f"all products fetched successfully page={page}, limit={limit}, total={total}"
    )
    return full_response


async def search_product(
    seed, filters, product_name, category, sub_category, page, limit, db
):
    offset = (page - 1) * limit
    if not product_name and not category and not sub_category:
        logger.error("user tried to execute an empty request")
        raise HTTPException(status_code=400, detail="all fields can not be left blank")
    normalized_product = product_name.strip().lower() if product_name else ""
    normalized_category = category.strip().lower() if category else ""
    normalized_sub_category = sub_category.strip().lower() if sub_category else ""
    version = await cache_version("product_key")
    cache_key = f"product:{version}:{filters}:{normalized_product}:{normalized_category}:{normalized_sub_category}:{page}:{limit}"
    product_cache = await cache(cache_key)
    if product_cache:
        logger.info("Cache hit for searched products")
        return StandardResponse(**product_cache)
    order_map = {
        None: (func.md5(func.concat(cast(Product.id, String), str(seed))),),
        "cheap": (Product.product_price.asc(),),
        "quality": (Product.avg_rating.desc(), Product.review_count.desc()),
        "latest": (Inventory.last_updated.desc(),),
    }
    if filters not in order_map:
        raise HTTPException(status_code=400, detail="invalid filter")
    order = order_map[filters]
    stmt = (
        select(Product)
        .join(Category, Product.category_id == Category.id)
        .join(SubCategory, Product.sub_category_id == SubCategory.id)
        .where(Product.is_deleted.is_(False))
    )
    if product_name is not None:
        logger.info("filtering products by product name %s", product_name)
        stmt = stmt.where(Product.product_name.ilike(f"%{product_name}%"))
    if category is not None:
        logger.info("filltering products by category %s", category)
        stmt = stmt.where(Category.name.ilike(f"%{category}%"))
    if sub_category is not None:
        logger.info("filltering products by sub_category %s", sub_category)
        stmt = stmt.where(SubCategory.name.ilike(f"%{sub_category}%"))
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar() or 0
    logger.info("total products querried %s", total)
    if filters == "latest":
        stmt = stmt.outerjoin(Inventory, Product.id == Inventory.product_id)
    stmt = stmt.options(selectinload(Product.inventory))
    result = (
        (await db.execute(stmt.order_by(*order).offset(offset).limit(limit)))
        .scalars()
        .all()
    )
    if not result:
        return StandardResponse(
            status="success", message="your search has returned 0 result", data=None
        )
    data = PaginatedMetadata[ProductResponse](
        items=[ProductResponse.model_validate(res) for res in result],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    full_response = StandardResponse(
        status="success", message="products data", data=data
    )
    await cached(cache_key, full_response, ttl=600)
    logger.info("cached searched products")
    return full_response


async def delete_one(store_id, product_id, background_task, db, payload, get_supabase):
    user_id = await store_auth(store_id, db, payload)
    stmt = (
        select(Product)
        .options(selectinload(Product.product_images))
        .where(
            Product.store_id == store_id,
            Product.id == product_id,
            Product.is_deleted.is_(False),
        )
        .with_for_update()
    )
    product = (await db.execute(stmt)).scalar_one_or_none()
    if not product:
        logger.warning(
            "user: %s, tried editing a non existent product, product_id: %s",
            user_id,
            product_id,
        )
        raise HTTPException(status_code=404, detail="product not found")
    product.is_deleted = True
    (
        await db.execute(
            update(Inventory)
            .where(Inventory.product_id == product_id)
            .values(is_deleted=True)
        )
    )
    files_to_delete = [p.image for p in product.product_images if p]
    data_id = product.id
    await db.execute(delete(ProductImage).where(ProductImage.product_id == product_id))
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
    except IntegrityError:
        await db.rollback()
        logger.exception(
            "database error occurred while delete product with product_id %s",
            product_id,
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            "error occurred while delete product with product_id %s", product_id
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("deleted product %s", product_id)
    return StandardResponse(
        status="success",
        message="deleted product",
        data={
            "id": data_id,
            "user_id": user_id,
            "deleted": True,
        },
    )
