from app.api.v1.models import (
    CartResponse,
    PaginatedMetadata,
    PaginatedResponse,
    StandardResponse,
    CartItemReponse,
)
from app.models_sql import Cart, CartItem, Product
from fastapi import HTTPException
from app.logs.logger import get_logger
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from app.utils.redis import cache, cached, cart_invalidation, cache_version

import asyncio

logger = get_logger("cart")


async def create_cart(
    db,
    payload,
):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=401, detail="you must be a registered user to shop"
        )
    logger.info(f"Creating cart for user {user_id}")
    cart = Cart(user_id=user_id)
    try:
        db.add(cart)
        await db.commit()
        await cart_invalidation(user_id=user_id)
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("Database integrity error while creating cart")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while creating cart")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"Cart created successfully for user {user_id}")
    return {"status": "success", "message": "cart successfully created"}


async def shopping(cart, db, payload):
    user_id = payload.get("user_id")
    stmt = (
        select(Cart)
        .options(selectinload(Cart.cartitems))
        .where(Cart.id == cart.cart_id, Cart.user_id == user_id)
        .with_for_update()
    )
    logger.info(
        f"User {user_id} is attempting to add product {cart.product_id} to cart {cart.cart_id}"
    )
    carts = (await db.execute(stmt)).scalar_one_or_none()
    if not carts:
        raise HTTPException(status_code=400, detail="pick a cart before proceeding")
    if len(carts.cartitems) > 30:
        raise HTTPException(status_code=403, detail="cart full")
    cartitem = next(
        (item for item in carts.cartitems if item.product_id == cart.product_id), None
    )
    if cart.quantity <= 0:
        raise HTTPException(
            status_code=400, detail="quantity must be an integer higher than zero"
        )
    available = (
        await db.execute(
            select(Product).where(
                Product.id == cart.product_id,
                Product.product_availability == "available",
                ~Product.is_deleted,
            )
        )
    ).scalar_one_or_none()
    try:
        if not available:
            raise HTTPException(status_code=400, detail="product out of stock")
        difference = None
        if cartitem:
            difference = cart.quantity - cartitem.quantity
            cartitem.quantity = cart.quantity
        else:
            difference = cart.quantity
            items = CartItem(
                cart_id=cart.cart_id,
                product_id=cart.product_id,
                quantity=cart.quantity,
            )
            db.add(items)
        carts.total_quantity = Cart.total_quantity + difference
        logger.info(
            f"Adding product {cart.product_id} to cart {cart.cart_id} for user {user_id}"
        )
        await db.commit()
        await cart_invalidation(user_id=user_id)
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("Database integrity error while adding product to cart")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while adding product to cart")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(
        f"Product {cart.product_id} added to cart {cart.cart_id} for user {user_id}"
    )
    return {"status": "success", "message": "product added to cart"}


async def retrieve_all(page, limit, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at retrieve_all endpoint")
        raise HTTPException(status_code=401, detail="not a registered buyer")
    offset = (page - 1) * limit
    if page < 1 or limit < 1:
        raise HTTPException(
            status_code=400, detail="page number and limit must be greater than 0"
        )
    version = await cache_version("cart_key")
    cart_keys = f"carts:v{version}:{user_id}:{page}:{limit}"
    cached_data = await cache(cart_keys)
    if cached_data:
        logger.info(f"Cache hit for all carts, for user {user_id}")
        return StandardResponse(**cached_data)
    stmt = (
        select(Cart)
        .options(selectinload(Cart.cartitems).selectinload(CartItem.product))
        .where(Cart.user_id == user_id, ~Cart.check_out)
    )
    total_gather, cart_gather = await asyncio.gather(
        db.execute(
            select(func.count()).select_from(Cart).where(Cart.user_id == user_id)
        ),
        db.execute(stmt.offset(offset).limit(limit)),
    )
    total = total_gather.scalar() or 0
    logger.info(f"Total {total} carts found for user {user_id}")
    carts = cart_gather.scalars().all()
    if not carts:
        logger.error("search for carts returned an empty list for user %s", user_id)
        return StandardResponse(status="success", message="no cart found", data=None)
    data = PaginatedMetadata[CartResponse](
        items=[CartResponse.model_validate(c) for c in carts],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    full_data = StandardResponse(status="success", message="cart", data=data)
    await cached(cart_keys, full_data, ttl=3600)
    logger.info(f"All cart data cached for user {user_id}")
    return full_data


async def retrieve_cart(cart_id, page, limit, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning(f"Attempting to retrieve cart i {cart_id}")
        raise HTTPException(status_code=401, detail="not a registered buyer")
    offset = (page - 1) * limit
    if page < 1 or limit < 1:
        raise HTTPException(
            status_code=400, detail="page number and limit must be greater than 0"
        )
    version = await cache_version("cart_key")
    cart_keys = f"carts:v{version}:{user_id}:{cart_id}:{page}:{limit}"
    cached_data = await cache(cart_keys)
    if cached_data:
        logger.info(f"Cache hit for cart {cart_id} for user {user_id}")
        return StandardResponse(**cached_data)
    stmt = (
        select(Cart)
        .options(selectinload(Cart.cartitems).selectinload(CartItem.product))
        .where(Cart.user_id == user_id, Cart.id == cart_id, ~Cart.check_out)
    )
    cart = (await db.execute(stmt)).scalar_one_or_none()
    if not cart:
        logger.error("user %s, tried retrieving a non-existent cart")
        raise HTTPException(status_code=404, detail="no cart found")
    logger.info(f"Cart {cart_id} found for user {user_id}, retrieving items")
    cart_model = CartResponse.model_validate(cart)
    total = len(cart.cartitems)
    logger.info("total number of cart items found in cart %s", total)
    items = cart.cartitems[offset : offset + limit]
    logger.info(f"Total {total} items found in cart {cart_id} for user {user_id}")
    cartitem_model = PaginatedMetadata[CartItemReponse](
        items=[CartItemReponse.model_validate(cartitem) for cartitem in items],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    data = {"cart": cart_model, "cart_item": cartitem_model}
    full_data = StandardResponse(status="success", message="cart", data=data)
    await cached(cart_keys, full_data, ttl=3600)
    logger.info(f"Cart {cart_id} data cached for user {user_id}")
    return full_data


async def edit_quantity(cart_id, cartitem_id, new_quantity, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="register and continue")
    logger.warning(
        f"Attempting to edit quantity of cart item {cartitem_id} in cart {cart_id}"
    )
    stmt = (
        select(CartItem)
        .join(Cart.cartitems)
        .where(Cart.id == cart_id, Cart.user_id == user_id, CartItem.id == cartitem_id)
        .with_for_update()
    )
    result = (await db.execute(stmt)).scalar_one_or_none()
    if new_quantity <= 0:
        raise HTTPException(
            status_code=400, detail="quantity must be greater than zero"
        )
    if not result:
        logger.error("user %s, tried editing a non-existent cart_item")
        raise HTTPException(status_code=404, detail="cart item not found")
    old_quantity = result.quantity
    difference = new_quantity - old_quantity
    result.quantity = new_quantity
    cart = (
        await db.execute(
            select(Cart)
            .where(Cart.user_id == user_id, Cart.id == cart_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    logger.info(
        f"Cart item {cartitem_id} found in cart {cart_id} for user {user_id}, updating quantity from {old_quantity} to {new_quantity}"
    )
    try:
        cart.total_quantity += difference
        await db.commit()
        await cart_invalidation(user_id=user_id)
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.exception("Failed to commit")
        raise HTTPException(status_code=400, detail="database error")
    except Exception as e:
        await db.rollback()
        logger.exception(f"Failed to commit: {e}")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(
        f"Cart item {cartitem_id} quantity updated successfully in cart {cart_id} for user {user_id}"
    )
    return {"message": "cart item quantity updated"}


async def update_cart(cart_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt to access update_cart endpoint")
        raise HTTPException(status_code=401, detail="not authorized")
    stmt = (
        select(Cart)
        .options(selectinload(Cart.cartitems).selectinload(CartItem.product))
        .where(Cart.user_id == user_id, Cart.id == cart_id)
    )
    result = (await db.execute(stmt)).scalar_one_or_none()
    if not result:
        logger.error("user %s, tried updating a non-existent cart", user_id)
        raise HTTPException(status_code=404, detail="invalid cart_id")
    items = [i.id for i in result.cartitems if i.product.is_deleted]
    if not items:
        return {"message": "cart up to date"}
    (await db.execute(delete(CartItem).where(CartItem.id.in_(items))))
    try:
        await db.commit()
        await cart_invalidation(user_id=user_id)
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error(
            f"Database integrity error while updating cart with id: {cart_id} for user {user_id}"
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            f"error while updating cart with id: {cart_id} for user {user_id}"
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"Cart with id: {cart_id} for user {user_id} successfully updated")
    return {"message": "cart successfully updated"}


async def delete_one(
    cart_id,
    cartitem_id,
    db,
    payload,
):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="not authorized")
    logger.warning(f"Attempting to delete cart item {cartitem_id} from cart {cart_id}")
    stmt = (
        select(CartItem)
        .join(Cart.cartitems)
        .where(Cart.id == cart_id, Cart.user_id == user_id, CartItem.id == cartitem_id)
    )
    result = (await db.execute(stmt)).scalar_one_or_none()
    if not result:
        logger.error("user %s, tried deleting a cart item that does not exist", user_id)
        raise HTTPException(status_code=404, detail="cart item not found")
    cart = (
        await db.execute(
            select(Cart)
            .where(Cart.user_id == user_id, Cart.id == cart_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    logger.info(
        f"Cart item {cartitem_id} found in cart {cart_id} for user {user_id}, proceeding to delete"
    )
    try:
        await db.delete(result)
        cart.total_quantity -= result.quantity
        await db.commit()
        await cart_invalidation(user_id=user_id)
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error(
            f"Database integrity error while deleting cart item {cartitem_id} from cart {cart_id} for user {user_id}"
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            f"error while deleting cart item {cartitem_id} from cart {cart_id} for user {user_id}"
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(
        f"Cart item {cartitem_id} deleted from cart {cart_id} for user {user_id}"
    )
    return {"message": "cart item deleted"}


async def delete(
    cart_id,
    db,
    payload,
):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="not authorized")
    logger.info(f"Attempting to delete cart {cart_id}")
    stmt = select(Cart).where(Cart.user_id == user_id, Cart.id == cart_id)
    result = (await db.execute(stmt)).scalar_one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="cart item not found")
    logger.info(f"Cart {cart_id} found for user {user_id}, proceeding to delete")
    try:
        await db.delete(result)
        await db.commit()
        await cart_invalidation(user_id=user_id)
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error(
            f"Database integrity error while deleting cart {cart_id} for user {user_id}"
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(f"error while deleting cart {cart_id} for user {user_id}")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"Cart {cart_id} successfully deleted for user {user_id}")
    return {"message": "cart emptied"}
