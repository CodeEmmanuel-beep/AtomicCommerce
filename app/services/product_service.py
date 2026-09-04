from fastapi import HTTPException, status, Response
import uuid
from werkzeug.utils import secure_filename
from app.logs.logger import get_logger
from app.api.v1.schemas import (
    PaginatedMetadata,
    ProductResponse,
    StandardResponse,
    PaginatedResponse,
    CursorPaginatedResponse,
    StoreRes,
    SingleProductResponse,
    ProductVariantResponse,
    ProductImageResponse,
)
from app.database.config import settings
from app.models import (
    Product,
    Category,
    Inventory,
    SubCategory,
    Store,
    ProductVariant,
    VariantImage,
)
from sqlalchemy import select, func, cast, update, String, delete
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone
from app.utils.redis import (
    store_products_invalidation,
    cache_version,
    cached,
    cache,
    product_version_invalidation,
    product_variants_invalidation,
    product_variant_invalidation,
)
from app.utils.helper import file_generator, upload_photo_helper, store_auth
from app.utils.supabase_url import cleaned_up
import re

logger = get_logger("products")


async def create(
    store_id,
    sub_category_name,
    product_name,
    product_description,
    primary_image,
    get_supabase,
    db,
    request,
    background_tasks,
):
    user_id = await store_auth(store_id, db, request)
    stmt = select(Store).where(Store.id == store_id, Store.is_deleted.is_(False))
    eligible = (await db.execute(stmt)).scalar_one_or_none()
    if not eligible:
        logger.warning(
            "invalid attempt to query non existent store: %s",
            store_id,
        )
        raise HTTPException(status_code=404, detail="store not found")
    if sub_category_name.strip() not in [s.strip() for s in eligible.sub_category]:
        logger.warning("user: %s, entered an invalid sub_category", user_id)
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
        logger.warning("user: %s, entered an invalid sub_category", user_id)
        raise HTTPException(status_code=404, detail="sub_category not found")
    filename = None
    files_allowed = ("image/jpeg", "image/png", "image/webp")
    if primary_image.content_type not in files_allowed:
        logger.warning(
            "user: %s, tried uploading a file with an unsupported format",
            user_id,
        )
        raise HTTPException(status_code=400, detail="file format not supported")
    filename = f"{uuid.uuid4()}_{secure_filename(primary_image.filename)}"
    try:
        file_byte = await file_generator(primary_image, user_id)
        client = await get_supabase.storage.from_(settings.BUCKET).upload(
            filename, file_byte, {"content-type": primary_image.content_type}
        )
        if hasattr(client, "error"):
            logger.exception("could not upload product primary image %s", client)
            raise HTTPException(
                status_code=500, detail="error uploading product primary image"
            )
        logger.info("saved product image, uploaded by user: %s", user_id)
        primary_image = filename
        new_product = Product(
            store_id=eligible.id,
            product_name=product_name,
            primary_image=filename,
            created_by=user_id,
            product_description=product_description,
            category_id=eligible.category_id,
            sub_category_id=sub_category,
        )
        db.add(new_product)
        await db.commit()
    except HTTPException:
        await db.rollback()
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned product image",
                context_2="successfully removed orphaned product image",
            )
        raise
    except IntegrityError:
        await db.rollback()
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned product image",
                context_2="successfully removed orphaned product image",
            )
        logger.error("database error while saving product data")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned product image",
                context_2="successfully removed orphaned product image",
            )
        logger.exception("error while saving product data")
        raise HTTPException(status_code=500, detail="internal server error")
    background_tasks.add_task(store_products_invalidation, store_id)
    logger.info("product created successfully by user %s", user_id)
    return StandardResponse(
        status="success", message="product added to shelve", data=None
    )


async def view_product_pics(product_id, db):
    cache_key = f"product_image:{product_id}"
    product_image_cache = await cache(cache_key)
    if product_image_cache:
        logger.info("Cache hit for product_images")
        return StandardResponse(**product_image_cache)
    stmt = (
        select(VariantImage)
        .join(ProductVariant, VariantImage.variant_id == ProductVariant.id)
        .where(ProductVariant.product_id == product_id)
    )
    p_image = (await db.execute(stmt)).scalars().all()
    if not p_image:
        raise HTTPException(status_code=404, detail="product images not found")
    data = [ProductImageResponse.model_validate(p) for p in p_image]
    response = StandardResponse(status="success", message="product_images", data=data)
    await cached(cache_key, response, ttl=600)
    return response


async def product_change(
    store_id,
    product_id,
    primary_image,
    product_name,
    product_description,
    db,
    request,
    get_supabase,
    background_tasks,
):
    user_id = await store_auth(store_id, db, request)
    filename = None
    old_photo = None
    has_changed = False
    if primary_image:
        try:
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
        except HTTPException:
            if filename:
                await cleaned_up(
                    get_supabase,
                    filename,
                    context_1="error removing orphaned product images",
                    context_2="successfully removed orphaned product images",
                )
            raise
        except Exception:
            if filename:
                await cleaned_up(
                    get_supabase,
                    filename,
                    context_1="error removing orphaned product images",
                    context_2="successfully removed orphaned product images",
                )
            logger.exception("error updating product images")
            raise HTTPException(status_code=500, detail="error saving product image")
    try:
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
        if filename:
            old_photo = product.primary_image
            product.primary_image = filename
            has_changed = True
        update_fields = {
            "product_name": product_name,
            "product_description": product_description,
        }
        for attr, field in update_fields.items():
            if field is not None:
                setattr(product, attr, field)
                has_changed = True
        if not has_changed:
            await db.rollback()
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        product.updated_by = user_id
        await db.commit()
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
    background_tasks.add_task(product_version_invalidation, product_id)
    logger.info("user %s edited product %s successfully", user_id, product_id)
    return StandardResponse(
        status="success", message="product updated successfully", data=None
    )


async def store_product(
    db,
    store_id,
    product_id,
):
    version = await cache_version(f"product_key:{product_id}")
    cache_key = f"product:{version}:{store_id}:{product_id}"
    product_cache = await cache(cache_key)
    if product_cache:
        logger.info("Cache hit for product %s in store: %s", product_id, store_id)
        return StandardResponse(**product_cache)
    stmt = (
        select(Product)
        .join(Store, Product.store_id == Store.id)
        .options(
            selectinload(Product.store),
            selectinload(Product.productvariants).selectinload(
                ProductVariant.inventory
            ),
        )
        .where(
            Product.is_deleted.is_(False),
            Store.id == store_id,
            Store.approved.is_(True),
            Store.is_deleted.is_(False),
            Product.id == product_id,
        )
    )
    product = (await db.execute(stmt)).scalar_one_or_none()
    if not product:
        logger.warning("Product %s not found in store %s", product_id, store_id)
        raise HTTPException(status_code=404, detail="Product not found")
    productvariants = [v for v in product.productvariants if not v.is_deleted]
    data = SingleProductResponse.model_validate(product)
    if productvariants:
        data.productvariants = [
            ProductVariantResponse.model_validate(v) for v in productvariants
        ]
    full_response = StandardResponse(
        status="success", message="product data", data=data
    )
    await cached(cache_key, full_response, ttl=7200)
    logger.info(
        "product %s of store %s fetched successfully",
        product_id,
        store_id,
    )
    return full_response


async def list_store_products(
    db,
    store_id,
    cursor_id,
    limit,
):
    version = await cache_version(f"store_product_key:{store_id}")
    cache_key = f"store_product:{version}:{store_id}:{cursor_id}:{limit}"
    product_cache = await cache(cache_key)
    if product_cache:
        logger.info("Cache hit for products in store: %s", store_id)
        return StandardResponse(**product_cache)
    stmt = (
        select(Product)
        .join(Store, Product.store_id == Store.id)
        .options(joinedload(Product.store))
        .where(
            Product.is_deleted.is_(False),
            Store.id == store_id,
            Store.is_deleted.is_(False),
            Store.approved.is_(True),
        )
        .order_by(Product.id.asc())
    )
    if cursor_id is not None:
        stmt = stmt.where(Product.id > cursor_id)
    products = (await db.execute(stmt.limit(limit + 1))).unique().scalars().all()
    has_more = len(products) > limit
    if has_more:
        products = products[:limit]
    next_cursor = products[-1].id if products else None
    if products:
        store_data = StoreRes.model_validate(products[0].store)
    else:
        store_obj = await db.get(Store, store_id)
        if not store_obj or store_obj.is_deleted or not store_obj.approved:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Store not found"
            )
        store_data = StoreRes.model_validate(store_obj)
    data = PaginatedMetadata[ProductResponse](
        items=[ProductResponse.model_validate(product) for product in products],
        cursor_pagination=CursorPaginatedResponse(
            next_cursor=next_cursor, limit=limit, has_more=has_more
        ),
    )
    full_response = StandardResponse(
        status="success",
        message="products data",
        data={"store": store_data, "products": data},
    )
    await cached(cache_key, full_response, ttl=7200)
    logger.info(
        "products of store %s fetched successfully, cursor_id: %s, limit: %s",
        store_id,
        cursor_id,
        limit,
    )
    return full_response


async def search_product(seed, filters, search, search_value, page, limit, db):
    offset = (page - 1) * limit
    if not search_value:
        logger.warning("user tried to execute an empty request")
        raise HTTPException(status_code=400, detail="you can not search a blank field")
    clean_search = search_value.strip()
    sanitized = re.sub(r"[^\w\s]", "", clean_search)
    formatted_words = [words for words in sanitized.split() if words]
    if not formatted_words:
        raise HTTPException(
            status_code=400, detail="search query contains no valid search terms"
        )
    ts_query_str = " & ".join(f"{word}:*" for word in formatted_words)
    version = await cache_version("search_product_key")
    cache_key = f"platform_product:{version}:{filters}:{search}:{ts_query_str}:{clean_search}:{page}:{limit}"
    product_cache = await cache(cache_key)
    if product_cache:
        logger.info("Cache hit for searched products")
        return StandardResponse(**product_cache)
    order_map = {
        None: (func.md5(func.concat(cast(Product.id, String), str(seed))),),
        "quality": (Product.avg_rating.desc(), Product.review_count.desc()),
        "latest": (Product.created_at.desc(),),
    }
    if filters not in order_map:
        raise HTTPException(status_code=400, detail="invalid filter")
    order = order_map[filters]
    stmt = (
        select(
            Product,
        )
        .join(Store, Product.store_id == Store.id)
        .where(
            Store.approved.is_(True),
            Store.is_deleted.is_(False),
            Product.is_deleted.is_(False),
        )
    )
    ranking = None
    if search == "product_name":
        ts_query = func.to_tsquery("english", ts_query_str)
        logger.info("filtering products by product name %s", ts_query_str)
        ranking = func.ts_rank(Product.searchable_text, ts_query)
        stmt = stmt.add_columns(ranking).where(
            Product.searchable_text.op("@@")(ts_query)
        )
    elif search == "category":
        logger.info("filltering products by category %s", clean_search)
        stmt = stmt.join(Category, Product.category_id == Category.id).where(
            Category.name.ilike(f"%{clean_search}%")
        )
    elif search == "sub_category":
        logger.info("filltering products by sub_category %s", clean_search)
        stmt = stmt.join(SubCategory, Product.sub_category_id == SubCategory.id).where(
            SubCategory.name.ilike(f"%{clean_search}%")
        )
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar() or 0
    logger.info("total products querried %s", total)
    stmt = stmt.options(selectinload(Product.store))
    if ranking is not None:
        ordering = (
            ranking.desc(),
            *order,
            Product.id.asc(),
        )
    else:
        ordering = (
            *order,
            Product.id.asc(),
        )
    result = (
        await db.execute(stmt.order_by(*ordering).offset(offset).limit(limit))
    ).all()
    data = PaginatedMetadata[ProductResponse](
        items=[ProductResponse.model_validate(res[0]) for res in result],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    full_response = StandardResponse(
        status="success", message="products data", data=data
    )
    await cached(cache_key, full_response, ttl=600)
    logger.info("global search for products returned data successfully")
    return full_response


async def delete_one(store_id, product_id, background_task, db, request, get_supabase):
    user_id = await store_auth(store_id, db, request)
    try:
        stmt = (
            select(Product)
            .options(
                selectinload(Product.productvariants).selectinload(
                    ProductVariant.vimage
                ),
            )
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
                "user: %s, tried deleting a non existent product, product_id: %s",
                user_id,
                product_id,
            )
            raise HTTPException(status_code=404, detail="product not found")
        now = datetime.now(timezone.utc)
        product.is_deleted = True
        product.deleted_by = user_id
        product.deleted_at = now
        if product.productvariants:
            for variant in product.productvariants:
                files_to_delete = [v.image for v in variant.vimage if v and v.image]
        rows = await db.execute(
            update(ProductVariant)
            .where(
                ProductVariant.product_id == product_id,
                ProductVariant.is_deleted.is_(False),
            )
            .values(is_deleted=True, deleted_at=now, deleted_by=user_id)
            .returning(ProductVariant.id)
        )
        variant_ids = rows.scalars().all()
        if variant_ids:
            (
                await db.execute(
                    update(Inventory)
                    .where(
                        Inventory.variant_id.in_(variant_ids),
                        Inventory.is_deleted.is_(False),
                    )
                    .values(is_deleted=True, deleted_at=now, deleted_by=user_id)
                )
            )
            await db.execute(
                delete(VariantImage).where(VariantImage.variant_id.in_(variant_ids))
            )
        await db.commit()
        background_task.add_task(product_version_invalidation, product_id)
        background_task.add_task(store_products_invalidation, store_id)
        background_task.add_task(product_variants_invalidation, product_id)
        if variant_ids:
            background_task.add_task(product_variant_invalidation, variant_ids)
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
    except IntegrityError:
        await db.rollback()
        logger.exception(
            "database error occurred while deleting product with id %s",
            product_id,
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error occurred while deleting product with id %s", product_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("deleted product %s", product_id)
    return StandardResponse(
        status="success",
        message="deleted product",
        data={
            "id": product_id,
            "user_id": user_id,
            "deleted": True,
        },
    )
