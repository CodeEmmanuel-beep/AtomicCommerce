from app.models import Inventory, Product, store_owners, store_staffs, ProductVariant
from sqlalchemy.exc import IntegrityError
from app.api.v1.schemas import (
    StandardResponse,
    PaginatedMetadata,
    PaginatedResponse,
    ProductRes,
    InventoryResponse,
)
from fastapi import HTTPException, Response, status
from app.utils.helper import store_auth, store_inventory, unique_id
from app.logs.logger import get_logger
from sqlalchemy import select, exists, func
from sqlalchemy.orm import selectinload, contains_eager
from app.utils.redis import (
    cache,
    cached,
    product_version_invalidation,
    product_variant_invalidation,
    product_variants_invalidation,
)

logger = get_logger("inventory")


async def create(store_id, request, variant_id, stock_quantity, db, background_task):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized attempt at the create endpoint")
        raise HTTPException(status_code=401, detail="not authenticated")
    stmt = select(
        exists().where(
            store_owners.c.stores_id == store_id,
            store_owners.c.users_id == user_id,
        ),
        exists().where(
            store_staffs.c.stores_id == store_id,
            store_staffs.c.users_id == user_id,
        ),
        exists(
            select(1)
            .select_from(ProductVariant)
            .join(Product, ProductVariant.product_id == Product.id)
            .where(
                ProductVariant.is_deleted.is_(False),
                ProductVariant.id == variant_id,
                Product.store_id == store_id,
                Product.is_deleted.is_(False),
            )
        ),
        exists().where(Inventory.variant_id == variant_id),
    )
    result = (await db.execute(stmt)).fetchone() or (False, False, False, False)
    owner, staff, productvariant_verified, already_stocked = result
    if not owner and not staff:
        logger.warning(
            "user: %s, made an ineligible attempt in create inventory endpoint", user_id
        )
        raise HTTPException(status_code=403, detail="ineligible credentials")
    if not productvariant_verified:
        logger.warning(
            "user: %s tried creating inventory for invalid or cross-tenant variant_id: %s",
            user_id,
            variant_id,
        )
        raise HTTPException(
            status_code=404, detail="product variant not found in this store"
        )
    if already_stocked:
        logger.warning(
            "user: %s tried duplicating inventory for variant: %s", user_id, variant_id
        )
        raise HTTPException(status_code=400, detail="stock already exists")
    product_update = (
        await db.execute(
            select(Product)
            .join(ProductVariant, Product.id == ProductVariant.product_id)
            .where(ProductVariant.id == variant_id, Product.is_deleted.is_(False))
        )
    ).scalar_one_or_none()
    if not product_update:
        logger.warning(
            "user: %s tried creating inventory for invalid or cross-tenant variant_id: %s",
            user_id,
            variant_id,
        )
        raise HTTPException(
            status_code=404, detail="product variant not found in this store"
        )
    if product_update.product_availability == "out_of_stock":
        product_update.product_availability = "available"
    product_id = product_update.id
    stock = Inventory(
        store_id=store_id, variant_id=variant_id, stock_quantity=stock_quantity
    )
    try:
        db.add(stock)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error(
            "database error occurred while creating inventory for store: %s, user affected '%s'",
            store_id,
            user_id,
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            "error occurred while creating inventory for store: %s, user affected '%s'",
            store_id,
            user_id,
        )
        raise HTTPException(status_code=500, detail="internal server error")
    background_task.add_task(product_variants_invalidation, product_id)
    background_task.add_task(product_variant_invalidation, variant_id)
    background_task.add_task(product_version_invalidation, product_id)
    logger.info("inventory created successfully for variant: %s", variant_id)
    return StandardResponse(status="success", message="inventory created", data=None)


async def read(store_id, request, inventory_id, db):
    user_id = await store_auth(store_id, db, request)
    stmt = store_inventory(store_id, inventory_id)
    cache_key = f"inventory:{store_id}:{inventory_id}"
    inventory_cache = await cache(cache_key)
    if inventory_cache:
        logger.info(
            "inventory cache hit for store_id: %s, inventory_id: %s",
            store_id,
            inventory_id,
        )
        return StandardResponse(**inventory_cache)
    result = (await db.execute(stmt)).scalar_one_or_none()
    if not result:
        logger.warning("user: %s, tried fetching a non existent inventory", user_id)
        raise HTTPException(status_code=404, detail="inventory not found")
    logger.info("read function returned data for user %s", user_id)
    data = InventoryResponse.model_validate(result)
    response = StandardResponse(status="success", message="inventory", data=data)
    await cached(cache_key, response, ttl=30)
    logger.info(
        "inventory data returned for user_id: %s, store_id: %s, inventory_id: %s",
        user_id,
        store_id,
        inventory_id,
    )
    return response


async def read_prod_inventory(store_id, product_id, request, page, limit, db):
    user_id = await store_auth(store_id, db, request)
    offset = (page - 1) * limit
    cache_key = f"inventory_list:{store_id}:{product_id}:{page}:{limit}"
    inventory_cache = await cache(cache_key)
    if inventory_cache:
        logger.info(
            "inventory cache hit for store_id: %s product_id %s", store_id, product_id
        )
        return StandardResponse(**inventory_cache)
    stmt = (
        select(Inventory)
        .join(ProductVariant, Inventory.variant_id == ProductVariant.id)
        .join(Product, ProductVariant.product_id == Product.id)
        .options(contains_eager(Inventory.variant).selectinload(ProductVariant.product))
        .where(
            ProductVariant.product_id == product_id,
            ProductVariant.is_deleted.is_(False),
            Inventory.is_deleted.is_(False),
            Product.is_deleted.is_(False),
            Inventory.store_id == store_id,
        )
    )
    results = (
        (
            await db.execute(
                stmt.order_by(Inventory.last_updated.desc()).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not results:
        logger.warning("user: %s, tried fetching a non existent inventory", user_id)
        raise HTTPException(status_code=404, detail="inventory not found")
    total = (
        await db.execute(
            select(func.count(Inventory.id))
            .join(ProductVariant, Inventory.variant_id == ProductVariant.id)
            .where(
                Inventory.store_id == store_id,
                Inventory.is_deleted.is_(False),
                ProductVariant.product_id == product_id,
                ProductVariant.is_deleted.is_(False),
            )
        )
    ).scalar() or 0
    logger.info("total inventories for store: %s, is: %s", store_id, total)
    product = ProductRes.model_validate(results[0].variant.product)
    data = PaginatedMetadata[InventoryResponse](
        items=[InventoryResponse.model_validate(r) for r in results],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    full_response = StandardResponse(
        status="success",
        message="product inventory",
        data={"product": product, "stocks": data},
    )
    await cached(cache_key, full_response, ttl=60)
    logger.info("read_all function returned data for user %s", user_id)
    return full_response


async def read_all(store_id, request, page, limit, db):
    user_id = await store_auth(store_id, db, request)
    offset = (page - 1) * limit
    cache_key = f"inventory_list:{store_id}:{page}:{limit}"
    inventory_cache = await cache(cache_key)
    if inventory_cache:
        logger.info("inventory cache hit for store_id: %s", store_id)
        return StandardResponse(**inventory_cache)
    stmt = store_inventory(store_id)
    results = (
        (
            await db.execute(
                stmt.order_by(Inventory.last_updated.desc()).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not results:
        logger.warning("user: %s, tried fetching a non existent inventory", user_id)
        raise HTTPException(status_code=404, detail="inventory not found")
    total = (
        await db.execute(
            select(func.count(Inventory.id)).where(
                Inventory.store_id == store_id, Inventory.is_deleted.is_(False)
            )
        )
    ).scalar() or 0
    logger.info("total inventories for store: %s, is: %s", store_id, total)
    data = PaginatedMetadata[InventoryResponse](
        items=[InventoryResponse.model_validate(r) for r in results],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    full_response = StandardResponse(
        status="success", message="store inventory", data=data
    )
    await cached(cache_key, full_response, ttl=60)
    logger.info("read_all function returned data for user %s", user_id)
    return full_response


async def update(store_id, inventory_id, stock_quantity, db, request, background_task):
    user_id = await store_auth(store_id, db, request)
    stmt = store_inventory(store_id, inventory_id)
    stmt = stmt.options(
        selectinload(Inventory.variant).selectinload(ProductVariant.product)
    ).with_for_update()
    inventory = (await db.execute(stmt)).scalar_one_or_none()
    if not inventory:
        logger.warning("user: %s, tried updating a non existent inventory", user_id)
        raise HTTPException(status_code=404, detail="inventory not found")
    if inventory.stock_quantity == stock_quantity:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    inventory.stock_quantity = stock_quantity
    if inventory.variant.product.product_availability == "out_of_stock":
        inventory.variant.product.product_availability = "available"
    product_id = inventory.variant.product.id
    variant_id = inventory.variant.id
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error(
            "database error occurred while updating inventory for store: %s, user affected '%s'",
            store_id,
            user_id,
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            "error occurred while updating inventory for store: %s, user affected '%s'",
            store_id,
            user_id,
        )
        raise HTTPException(status_code=500, detail="internal server error")
    background_task.add_task(product_variants_invalidation, product_id)
    background_task.add_task(product_variant_invalidation, variant_id)
    background_task.add_task(product_version_invalidation, product_id)
    logger.info("inventory: %s, updated successfully", inventory_id)
    return StandardResponse(status="success", message="inventory updated", data=None)
