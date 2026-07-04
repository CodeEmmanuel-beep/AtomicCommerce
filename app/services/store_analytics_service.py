from app.models import (
    Payment,
    Order,
    Review,
    Store,
    User,
    PaymentStatus,
    OrderStatus,
    Product,
    CartItem,
    OrderItem,
    Inventory,
    store_owners,
)
from app.utils.redis import cache, cached
from sqlalchemy import cast, Float, select, func, desc, asc, Integer, exists
from typing import cast as typing_cast
from fastapi import HTTPException
from app.logs.logger import get_logger
from app.api.v1.schemas import StandardResponse
from datetime import date, datetime, timezone
from dateutil.relativedelta import relativedelta

logger = get_logger("store_analytics")


async def view_performanc_helper(slug, context, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning(f"unauthorized attempt at the {context} endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    row = (
        await db.execute(
            select(
                Store,
                exists().where(
                    store_owners.c.users_id == user_id,
                    store_owners.c.stores_id == Store.id,
                ),
            ).where(
                Store.slug == slug,
                Store.approved.is_(True),
            )
        )
    ).fetchone()
    target_store, is_owner = row or (None, None)
    if not target_store or not is_owner:
        logger.warning(
            "user %s attempted to access %s for store %s without permission or store not found",
            user_id,
            context,
            slug,
        )
        raise HTTPException(status_code=403, detail="restricted access")
    cache_key = f"{context}:{slug}"
    cached_data = await cache(cache_key)
    if cached_data:
        logger.info(f"cache hit at the {context} endpoint for store: %s", slug)
        return cached_data
    return cache_key, target_store


async def view_store_data(slug, db):
    cache_key = f"store_data:{slug}"
    cached_data = await cache(cache_key)
    if cached_data:
        logger.info("cache hit at view store data endpoint for store %s", slug)
        return StandardResponse(**cached_data)
    store_id = (
        await db.execute(
            select(Store.id).where(Store.slug == slug, Store.approved.is_(True))
        )
    ).scalar_one_or_none()
    if not store_id:
        logger.error("user tried accessing an unvailable store: %s", slug)
        raise HTTPException(status_code=404, detail="store not found")
    target_store = select(func.count(Order.id), func.max(Order.created_at)).where(
        Order.store_id == store_id
    )
    result = await db.execute(target_store)
    row = result.fetchone()
    store_orders, last_order = row
    data = {"store_total_orders": store_orders or 0, "last_order": last_order}
    logger.info("data returned at view store data endpoint for store: %s", slug)
    full_response = StandardResponse(
        status="success", message="store data successfully retrieved", data=data
    )
    await cached(cache_key, full_response, ttl=300)
    return full_response


async def view_overall_performance(slug, db, payload):
    result = await view_performanc_helper(slug, "view_overall_performance", db, payload)
    if isinstance(result, dict):
        return StandardResponse(**result)
    c_key, target_ = result
    today = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)
    cache_key = typing_cast(str, c_key)
    target_store = typing_cast(Store, target_)
    if today < target_store.founded + relativedelta(months=1):
        return StandardResponse(
            status="success",
            message="performance statistics are revealed one month after onboarding",
            data=None,
        )
    days = (today - target_store.founded).days
    row = (
        await db.execute(
            select(func.sum(Payment.total_amount), func.sum(Payment.shipping_fee))
            .join(Order, Order.id == Payment.order_id)
            .where(
                Order.store_id == target_store.id,
                Payment.payment_status == PaymentStatus.SUCCESS.value,
            )
        )
    ).fetchone()
    total_amount, shipping_fees = row if row else (0, 0)
    total_amount = total_amount or 0
    shipping_fees = shipping_fees or 0
    total_gross_sales = total_amount - shipping_fees
    average_sales_per_day = round(float(total_gross_sales / days), 2)
    extreme_sale_row = (
        select(Payment.payment_date, Payment.total_amount, Payment.shipping_fee)
        .join(Order, Order.id == Payment.order_id)
        .where(
            Order.store_id == target_store.id,
            Payment.payment_status == PaymentStatus.SUCCESS.value,
        )
    )
    lowest_sale_row = (
        await db.execute(extreme_sale_row.order_by(Payment.total_amount.asc()).limit(1))
    ).fetchone()
    if lowest_sale_row:
        lowest_sale_date, lowest_sale_total, lowest_sale_shipping = lowest_sale_row or (
            0,
            0,
            0,
        )
        l_sale = lowest_sale_total - lowest_sale_shipping
        lowest_sale = {"date": lowest_sale_date, "sales": float(l_sale)}
    highest_sale_row = (
        await db.execute(
            extreme_sale_row.order_by(Payment.total_amount.desc()).limit(1)
        )
    ).fetchone()
    if highest_sale_row:
        highest_sale_date, highest_sale_total, highest_sale_shipping = (
            highest_sale_row
            or (
                0,
                0,
                0,
            )
        )
        h_sale = highest_sale_total - highest_sale_shipping
        highest_sale = {"date": highest_sale_date, "sales": float(h_sale)}
    data = {
        "total_gross_sales": round(float(total_gross_sales or 0), 2),
        "highest_sales": highest_sale,
        "lowest_sales": lowest_sale,
        "average_sales_per_day": average_sales_per_day or 0,
    }
    full_response = StandardResponse(
        status="success", message="overall performance", data=data
    )
    await cached(cache_key, full_response, ttl=300)
    logger.info(
        "data returned at view overall performance endpoint for store: %s", slug
    )
    return full_response


async def view_current_performance(slug, db, payload):
    result = await view_performanc_helper(
        slug, "view_ccurrent_performance", db, payload
    )
    if isinstance(result, dict):
        return StandardResponse(**result)
    c_key, t_store = result
    cache_key = typing_cast(str, c_key)
    target_store = typing_cast(Store, t_store)
    first_of_the_month = date.today().replace(day=1)
    days = date.today().day
    row = (
        await db.execute(
            select(func.sum(Payment.total_amount), func.sum(Payment.shipping_fee))
            .join(Order, Payment.order_id == Order.id)
            .where(
                Order.store_id == target_store.id,
                Payment.payment_status == PaymentStatus.SUCCESS.value,
                Payment.payment_date >= first_of_the_month,
            )
        )
    ).fetchone()
    total_amount, shipping_fees_this_month = row if row else (0, 0)
    total_amount = total_amount or 0
    shipping_fees_this_month = shipping_fees_this_month or 0
    gross_sales_this_month = total_amount - shipping_fees_this_month
    daily_avg = gross_sales_this_month / days if days > 0 else 0
    extreme_sale_row = (
        select(Payment.payment_date, Payment.total_amount, Payment.shipping_fee)
        .join(Order, Order.id == Payment.order_id)
        .where(
            Order.store_id == target_store.id,
            Payment.payment_status == PaymentStatus.SUCCESS.value,
            Payment.payment_date >= first_of_the_month,
        )
    )
    net_sales = Payment.total_amount - Payment.shipping_fee
    lowest_sale_row = (
        await db.execute(extreme_sale_row.order_by(net_sales.asc()).limit(1))
    ).fetchone()
    if lowest_sale_row:
        lowest_sale_date, lowest_sale_total, lowest_sale_shipping = lowest_sale_row or (
            0,
            0,
            0,
        )
        l_sale = lowest_sale_total - lowest_sale_shipping
        lowest_sale = {"date": lowest_sale_date, "sales": float(l_sale)}
    highest_sale_row = (
        await db.execute(extreme_sale_row.order_by(net_sales.desc()).limit(1))
    ).fetchone()
    if highest_sale_row:
        highest_sale_date, highest_sale_total, highest_sale_shipping = (
            highest_sale_row or (0, 0, 0)
        )
        h_sale = highest_sale_total - highest_sale_shipping
        highest_sale = {"date": highest_sale_date, "sales": float(h_sale)}
    ratings_orders_check = select(
        select(func.count(Order.id))
        .where(
            Order.store_id == target_store.id,
            Order.created_at >= first_of_the_month,
            Order.status.in_((OrderStatus.processing, OrderStatus.delivered)),
        )
        .scalar_subquery(),
        select(func.max(Order.created_at))
        .where(
            Order.store_id == target_store.id, Order.created_at >= first_of_the_month
        )
        .scalar_subquery(),
        select(func.count(Review.ratings))
        .where(
            Review.store_id == target_store.id,
            Review.time_of_post >= first_of_the_month,
        )
        .scalar_subquery(),
        select(func.avg(cast(Review.ratings, Float)))
        .where(
            Review.store_id == target_store.id,
            Review.time_of_post >= first_of_the_month,
        )
        .scalar_subquery(),
    )
    result_check = await db.execute(ratings_orders_check)
    row = result_check.fetchone()
    orders, last_order, ratings, avg_ratings = row
    data = {
        "orders_this_month": orders,
        "day_of_last_order": last_order,
        "total_ratings_this_month": ratings or 0,
        "average_ratings_this_month": round(float(avg_ratings or 0), 2),
        "gross_sales_this_month": round(float(gross_sales_this_month or 0), 2),
        "highest_sales": highest_sale,
        "lowest_sales": lowest_sale,
        "daily_average": round(float(daily_avg or 0), 2),
    }
    full_response = StandardResponse(
        status="success", message="current performance", data=data
    )
    await cached(cache_key, full_response, ttl=300)
    logger.info(
        "data returned at view current performance endpoint for store: %s", slug
    )
    return full_response


async def products_stats(slug, ranking, time_frame, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at the product_statistics endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    cache_key = f"product_statistics:{slug}:{ranking}:{time_frame}"
    cached_data = await cache(cache_key)
    if cached_data:
        logger.info("cache hit at the product_statistics endpoint for store: %s", slug)
        return StandardResponse(**cached_data)
    row = (
        await db.execute(
            select(
                Store,
                exists().where(
                    store_owners.c.users_id == user_id,
                    store_owners.c.stores_id == Store.id,
                ),
            ).where(
                Store.slug == slug,
                Store.approved.is_(True),
            )
        )
    ).fetchone()
    target_store, is_owner = row or (None, None)
    if not target_store or not is_owner:
        logger.warning(
            "user %s attempted to access product_statistics endpoint for store %s without permission or store not found",
            user_id,
            slug,
        )
        raise HTTPException(status_code=403, detail="restricted access")
    now = datetime.now(timezone.utc)
    time_map = {
        "1 year": now - relativedelta(years=1),
        "6 months": now - relativedelta(months=6),
        "3 months": now - relativedelta(months=3),
        "1 month": now - relativedelta(months=1),
        "1 week": now - relativedelta(days=7),
    }
    time_period = time_map.get(time_frame)
    if not time_period:
        raise HTTPException(
            status_code=400,
            detail="invalid time frame selected",
        )
    if target_store.founded > time_period:
        raise HTTPException(
            status_code=400,
            detail=f"store's existence is below {time_frame}",
        )
    if ranking not in ["top_product", "least_product"]:
        raise HTTPException(
            status_code=400,
            detail="this endpoint is only ranked by 'top_product' or 'least_product'",
        )
    order_count = desc if ranking == "top_product" else asc
    product_sales = func.sum(OrderItem.quantity).label("total_quantity")
    products = (
        await db.execute(
            select(
                Product.product_name,
                Product.product_size,
                cast(func.coalesce(product_sales, 0), Integer),
            )
            .join(Store, Product.store_id == Store.id)
            .join(OrderItem, OrderItem.product_id == Product.id)
            .join(Order, OrderItem.order_id == Order.id)
            .join(Payment, Order.id == Payment.order_id)
            .where(
                Payment.payment_status == PaymentStatus.SUCCESS.value,
                Order.created_at >= time_period,
                Store.slug == slug,
            )
            .group_by(
                Product.product_name,
                Product.product_size,
            )
            .order_by(order_count(product_sales))
            .limit(5)
        )
    ).all()
    avg_ratings = func.avg(Review.ratings).label("average_ratings")
    product_ratings = (
        await db.execute(
            select(
                Product.product_name,
                Product.product_size,
                cast(func.coalesce(avg_ratings, 0), Float),
            )
            .join(Review, Product.id == Review.product_id)
            .join(Store, Product.store_id == Store.id)
            .where(
                Review.time_of_post >= time_period,
                Store.slug == slug,
            )
            .group_by(Product.product_name, Product.product_size)
            .order_by(order_count(avg_ratings))
        ).limit(5)
    ).all()
    if not products and not product_ratings:
        logger.warning("user: %s product stats returned null", user_id)
        return StandardResponse(
            status="success",
            message=f"no available product statistics within {time_frame}",
            data=None,
        )
    message = (
        "most sold products and most rated products in descending order"
        if ranking == "top_product"
        else "least sold products and least rated products in ascending order"
    )
    data = {
        "product_sales": [
            {"product_name": name, "product_size": size, "quantity": int(qty)}
            for name, size, qty in products
        ],
        "product_ratings": [
            {"name": name, "product_size": size, "ratings": float(rts)}
            for name, size, rts in product_ratings
        ],
    }
    full_response = StandardResponse(status="success", message=message, data=data)
    await cached(cache_key, full_response, ttl=600)
    return full_response


async def inventory_stats(slug, stock_range, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at the inventory_statistics endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    cache_key = f"inventory_statistics:{slug}:{stock_range}"
    cached_data = await cache(cache_key)
    if cached_data:
        logger.info(
            "cache hit at the inventory_statistics endpoint for store: %s", slug
        )
        return StandardResponse(**cached_data)
    target_store = (
        await db.execute(
            select(Store).where(
                Store.slug == slug,
                Store.user_owners.any(User.id == user_id),
                Store.approved,
            )
        )
    ).scalar_one_or_none()
    if not target_store:
        logger.warning(
            "user %s attempted to access inventory_statistics endpoint for store %s without permission or store not found",
            user_id,
            slug,
        )
        raise HTTPException(status_code=403, detail="restricted access")
    s_range = {
        "out_of_stock": 0,
        "five_below": 5,
        "ten_below": 10,
        "twenty_below": 20,
        "thirty_below": 30,
        "fifty_below": 50,
        "above_fifty": 50,
    }
    ranges = s_range.get(stock_range)
    if not ranges:
        raise HTTPException(status_code=400, detail="invalid stock range selected")
    equator = ">" if stock_range == "above_fifty" else "<="
    inventories = (
        await db.execute(
            select(Product.product_name, Product.product_size, Inventory.stock_quantity)
            .join(Inventory, Product.id == Inventory.product_id)
            .where(
                Product.store_id == target_store.id,
                Inventory.stock_quantity.op(equator)(ranges),
            )
            .order_by(Inventory.stock_quantity.desc())
        )
    ).all()
    if not inventories:
        logger.warning("user: %s inventory stats returned null", user_id)
        return StandardResponse(
            status="success",
            message=f"No products found within the {stock_range} range.",
            data=None,
        )
    data = {
        "inventory": [
            {"product_name": name, "Product_size": size, "stock_quantity": qty}
            for name, size, qty in inventories
        ],
    }
    full_response = StandardResponse(
        status="success",
        message=f"inventory statistics for {stock_range} range",
        data=data,
    )
    await cached(cache_key, full_response, ttl=600)
    return full_response
