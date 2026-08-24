from fastapi import HTTPException, status, Response
from app.logs.logger import get_logger
from app.api.v1.schemas import (
    PaginatedMetadata,
    StandardResponse,
    CursorPaginatedResponse,
    ProductVariantResponse,
    ProductImageResponse,
)
from app.models import (
    Product,
    Inventory,
    ProductVariant,
    VariantImage,
)
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import select, func, update, delete
from sqlalchemy.orm import selectinload, contains_eager
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone
from app.utils.redis import (
    product_variant_invalidation,
    product_variants_invalidation,
    cart_global_invalidation,
    order_global_invalidation,
    store_products_invalidation,
    cache_version,
    cached,
    cache,
    product_version_invalidation,
)
from app.utils.helper import upload_photo_helper, store_auth, deep_merge
from app.utils.supabase_url import cleaned_up, get_public_url

logger = get_logger("products")


async def create_v(
    variant,
    db,
    request,
    background_tasks,
):
    user_id = await store_auth(variant.store_id, db, request)
    stmt = select(Product).where(
        Product.id == variant.product_id, Product.is_deleted.is_(False)
    )
    product = (await db.execute(stmt)).scalar_one_or_none()
    if not product:
        logger.warning(
            "invalid attempt to query non existent product: %s",
            variant.product_id,
        )
        raise HTTPException(status_code=404, detail="product not found")
    if product.sku == variant.sku:
        raise HTTPException(status_code=400, detail="sku already in use")
    try:
        new_variant = ProductVariant(
            product_id=product.id,
            created_by=user_id,
            price=variant.price,
            attributes=variant.attributes,
            sku=variant.sku,
        )
        db.add(new_variant)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error while saving product variant data")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while saving product variant data")
        raise HTTPException(status_code=500, detail="internal server error")
    background_tasks.add_task(product_variants_invalidation, variant.product_id)
    background_tasks.add_task(store_products_invalidation, variant.store_id)
    logger.info(
        "product variant for product %s created successfully by user %s",
        variant.product_id,
        user_id,
    )
    return StandardResponse(
        status="success", message="product variant added to shelve", data=None
    )


async def add_vimage(
    variant_id,
    store_id,
    image,
    db,
    request,
    get_supabase,
):
    user_id = await store_auth(store_id, db, request)
    stmt = (
        select(ProductVariant)
        .join(Product, ProductVariant.product_id == Product.id)
        .where(
            ProductVariant.id == variant_id,
            ProductVariant.is_deleted.is_(False),
            Product.store_id == store_id,
            Product.is_deleted.is_(False),
        )
        .with_for_update()
    )
    variant = (await db.execute(stmt)).scalar_one_or_none()
    if not variant:
        logger.warning(
            "unauthorized attempt to query product variant: %s",
            variant_id,
        )
        raise HTTPException(status_code=404, detail="product variant not found")
    image_count = (
        await db.execute(
            select(func.count(VariantImage.id)).where(
                VariantImage.variant_id == variant_id
            )
        )
    ).scalar() or 0
    if image_count >= 5:
        logger.warning(
            "user: %s, tried uploading more than 5 images for product variant: %s",
            user_id,
            variant_id,
        )
        raise HTTPException(status_code=400, detail="maximum of 5 images allowed")
    filename = None
    filename = await upload_photo_helper(image, request, get_supabase)
    new_images = VariantImage(variant_id=variant_id, image=filename)
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
    logger.info("image for product variant %s uploaded successfully", variant_id)
    return StandardResponse(
        status="success",
        message="product variant image uploaded successfully",
        data=None,
    )


async def view_variant_photos(variant_id, db):
    cache_key = f"variant_image:{variant_id}"
    product_image_cache = await cache(cache_key)
    if product_image_cache:
        logger.info("Cache hit for product_images")
        return StandardResponse(**product_image_cache)
    stmt = select(VariantImage).where(VariantImage.variant_id == variant_id)
    p_image = (await db.execute(stmt)).scalars().all()
    if not p_image:
        raise HTTPException(status_code=404, detail="product images not found")
    data = [ProductImageResponse.model_validate(p) for p in p_image]
    response = StandardResponse(status="success", message="product_images", data=data)
    await cached(cache_key, response, ttl=600)
    return response


async def delete_image(store_id, variant_id, image_id, db, request, get_supabase):
    user_id = await store_auth(store_id, db, request)
    delete_img = (
        await db.execute(
            select(VariantImage)
            .join(ProductVariant, VariantImage.variant_id == ProductVariant.id)
            .join(Product, ProductVariant.product_id == Product.id)
            .where(
                VariantImage.id == image_id,
                Product.store_id == store_id,
                VariantImage.variant_id == variant_id,
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
    except IntegrityError:
        await db.rollback()
        logger.error("database error while deleting product variant image")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while deleting product variant image")
        raise HTTPException(status_code=500, detail="internal server error")
    if filename:
        await cleaned_up(
            get_supabase,
            filename,
            context_1="error removing orphaned product variant image",
            context_2="successfully removed orphaned product variant image",
        )
    logger.info("successfully deleted variant image: %s", image_id)
    return StandardResponse(
        status="success", message="product variant image deleted", data=None
    )


async def variant_change(
    edit_mode,
    variant,
    db,
    request,
    background_tasks,
):
    user_id = await store_auth(variant.store_id, db, request)
    has_changed = False
    try:
        stmt = (
            select(ProductVariant)
            .join(Product, ProductVariant.product_id == Product.id)
            .options(selectinload(ProductVariant.product))
            .where(
                Product.store_id == variant.store_id,
                ProductVariant.id == variant.id,
                ProductVariant.is_deleted.is_(False),
                Product.is_deleted.is_(False),
            )
            .with_for_update(of=ProductVariant)
        )
        product_variant = (await db.execute(stmt)).scalar_one_or_none()
        if not product_variant:
            logger.warning(
                "user: %s, tried editing a non existent product variant, variant_id: %s",
                user_id,
                variant.id,
            )
            raise HTTPException(status_code=404, detail="product variant not found")
        product_id = product_variant.product.id
        if variant.attributes is not None:
            if edit_mode == "add":
                old_attr = product_variant.attributes or {}
                new_attr = variant.attributes or {}
                product_variant.attributes = deep_merge(old_attr, new_attr)
                has_changed = True
            else:
                product_variant.attributes = variant.attributes
                has_changed = True
            if has_changed:
                flag_modified(product_variant, "attributes")
        update_fields = ["sku", "price"]
        for field in update_fields:
            value = getattr(variant, field, None)
            if value and value != getattr(product_variant, field):
                setattr(product_variant, field, value)
                has_changed = True
        if not has_changed:
            await db.rollback()
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        product_variant.updated_by = user_id
        await db.commit()
        logger.info("successfully updated product data")
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error occurred while updating product data")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error occurred while updating product data")
        raise HTTPException(status_code=500, detail="internal server error")
    background_tasks.add_task(cart_global_invalidation, variant.store_id)
    background_tasks.add_task(order_global_invalidation, variant.store_id)
    background_tasks.add_task(product_version_invalidation, product_id)
    background_tasks.add_task(product_variant_invalidation, variant.id)
    background_tasks.add_task(product_variants_invalidation, product_id)
    logger.info("user %s edited product variant %s successfully", user_id, variant.id)
    return StandardResponse(
        status="success", message="product variant updated successfully", data=None
    )


async def product_variant(
    db,
    variant_id,
):
    version = await cache_version(f"variant_key:{variant_id}")
    cache_key = f"variant:{version}:{variant_id}"
    product_cache = await cache(cache_key)
    if product_cache:
        logger.info("Cache hit for product variant %s", variant_id)
        return StandardResponse(**product_cache)
    stmt = (
        select(ProductVariant)
        .options(selectinload(ProductVariant.vimage))
        .where(
            ProductVariant.is_deleted.is_(False),
            ProductVariant.id == variant_id,
        )
    )
    product_variant = (await db.execute(stmt)).scalar_one_or_none()
    if not product_variant:
        logger.warning("Product variant %s not found", variant_id)
        raise HTTPException(status_code=404, detail="Product variant not found")
    p_image = None
    if product_variant.vimage:
        p_image = min(
            product_variant.vimage,
            key=lambda img: (
                img.created_at
                if getattr(img, "created_at", None) is not None
                else datetime.max
            ),
        )
    data = ProductVariantResponse.model_validate(product_variant)
    if p_image:
        data.primary_image = get_public_url(p_image.image)
    full_response = StandardResponse(
        status="success", message="product variant data", data=data
    )
    await cached(cache_key, full_response, ttl=7200)
    logger.info(
        "product variant %s fetched successfully",
        variant_id,
    )
    return full_response


async def list_product_variants(
    db,
    product_id,
    cursor_id,
    limit,
):
    version = await cache_version(f"product_variant_key:{product_id}")
    cache_key = f"product_variants:{version}:{product_id}:{cursor_id}:{limit}"
    product_cache = await cache(cache_key)
    if product_cache:
        logger.info("Cache hit for product variants of product: %s", product_id)
        return StandardResponse(**product_cache)
    stmt = (
        select(ProductVariant)
        .options(selectinload(ProductVariant.vimage))
        .where(
            ProductVariant.is_deleted.is_(False),
            ProductVariant.product_id == product_id,
        )
        .order_by(ProductVariant.id.asc())
    )
    if cursor_id is not None:
        stmt = stmt.where(ProductVariant.id > cursor_id)
    product_variants = (
        (await db.execute(stmt.limit(limit + 1))).unique().scalars().all()
    )
    has_more = len(product_variants) > limit
    if has_more:
        product_variants = product_variants[:limit]
    next_cursor = product_variants[-1].id if product_variants else None
    items = []
    for product in product_variants:
        data_item = ProductVariantResponse.model_validate(product)
        if product.vimage:
            primary_image = min(
                product.vimage,
                key=lambda img: (
                    img.created_at
                    if not isinstance(img, str)
                    and getattr(img, "created_at", None) is not None
                    else datetime.max
                ),
            )
            data_item.primary_image = get_public_url(primary_image.image)
        items.append(data_item)
    data = PaginatedMetadata[ProductVariantResponse](
        items=items,
        cursor_pagination=CursorPaginatedResponse(
            next_cursor=next_cursor, limit=limit, has_more=has_more
        ),
    )
    full_response = StandardResponse(
        status="success",
        message="product variants data",
        data=data,
    )
    await cached(cache_key, full_response, ttl=7200)
    logger.info(
        "variants of prouct %s fetched successfully, cursor_id: %s, limit: %s",
        product_id,
        cursor_id,
        limit,
    )
    return full_response


async def delete_one_variant(
    store_id, variant_id, background_task, db, request, get_supabase
):
    user_id = await store_auth(store_id, db, request)
    try:
        stmt = (
            select(ProductVariant)
            .join(Product, ProductVariant.product_id == Product.id)
            .options(
                selectinload(ProductVariant.vimage),
                contains_eager(ProductVariant.product),
            )
            .where(
                Product.store_id == store_id,
                ProductVariant.id == variant_id,
                ProductVariant.is_deleted.is_(False),
            )
            .with_for_update()
        )
        product_variant = (await db.execute(stmt)).scalar_one_or_none()
        if not product_variant:
            logger.warning(
                "user: %s, tried deleting a non existent product variant, variant_id: %s",
                user_id,
                variant_id,
            )
            raise HTTPException(status_code=404, detail="product variant not found")
        product_id = product_variant.product.id
        now = datetime.now(timezone.utc)
        product_variant.is_deleted = True
        product_variant.deleted_by = user_id
        product_variant.deleted_at = now
        files_to_delete = [p.image for p in product_variant.vimage if p]
        await db.execute(
            delete(VariantImage).where(VariantImage.variant_id == variant_id)
        )
        (
            await db.execute(
                update(Inventory)
                .where(Inventory.variant_id == variant_id)
                .values(is_deleted=True, deleted_at=now, deleted_by=user_id)
            )
        )
        await db.commit()
        background_task.add_task(cart_global_invalidation, store_id)
        background_task.add_task(order_global_invalidation, store_id)
        background_task.add_task(product_version_invalidation, product_id)
        background_task.add_task(product_variants_invalidation, product_id)
        background_task.add_task(product_variant_invalidation, variant_id)
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
            "database error occurred while deleting product variant with id %s",
            variant_id,
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            "error occurred while deleting product variant with id %s", variant_id
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("deleted product variant %s successfully", variant_id)
    return StandardResponse(
        status="success",
        message="product variant deleted",
        data={
            "id": variant_id,
            "user_id": user_id,
            "deleted": True,
        },
    )
