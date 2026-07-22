from app.models import (
    Payment,
    Order,
    Review,
    Store,
    PaymentStatus,
    OrderStatus,
    Product,
    OrderItem,
    Inventory,
)
from app.utils.redis import cache, cached
from sqlalchemy import cast, select, func, desc, asc, Integer
from decimal import Decimal
from typing import cast as typing_cast
from fastapi import HTTPException
from app.logs.logger import get_logger
from app.utils.supabase_url import get_public_url
from app.api.v1.schemas import StandardResponse
from datetime import date, datetime, timezone
from dateutil.relativedelta import relativedelta
from app.utils.helper import view_performance_helper

logger = get_logger("store_analytics")

TWO_PLACES = Decimal("0.01")


async def view_store_data(slug, db):
    cache_key = f"store_data:{slug}"
    cached_data = await cache(cache_key)
    if cached_data:
        logger.info("cache hit at view store data endpoint for store %s", slug)
        return StandardResponse(**cached_data)
    target_store = (
        select(Store.id, func.count(Order.id), func.max(Order.created_at))
        .outerjoin(Order, Store.id == Order.store_id)
        .where(Store.slug == slug, Store.approved.is_(True))
        .group_by(Store.id)
    )
    result = await db.execute(target_store)
    row = result.fetchone()
    store_id, store_orders, last_order = row or (None, 0, None)
    product_sales = func.sum(OrderItem.quantity).label("total_quantity")
    if not store_id:
        logger.error("user tried accessing an unvailable store: %s", slug)
        raise HTTPException(status_code=404, detail="store not found")
    if not store_orders or store_orders == 0:
        logger.warning("store %s has no orders yet", slug)
        empty_response = StandardResponse(
            status="success",
            message="store has no orders yet",
            data={},
        )
        await cached(cache_key, empty_response.model_dump(), ttl=300)
        return empty_response
    product = (
        await db.execute(
            select(
                Product.id,
                Product.primary_image,
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
                Store.slug == slug,
            )
            .group_by(
                Product.id,
                Product.primary_image,
                Product.product_name,
                Product.product_size,
            )
            .order_by(product_sales.desc())
            .limit(1)
        )
    ).fetchone()
    top_product_data = None
    if product:
        p_id, img, name, size, qty = product
        top_product_data = {
            "id": p_id,
            "image": get_public_url(img),
            "product_name": name,
            "product_size": size,
            "quantity_sold": int(qty),
        }
    data = {
        "store_total_orders": int(store_orders),
        "last_order": last_order if last_order else None,
        "top_performing_product": top_product_data,
    }
    full_response = StandardResponse(
        status="success", message="store data successfully retrieved", data=data
    )
    await cached(cache_key, full_response, ttl=300)
    logger.info("data returned at view store data endpoint for store: %s", slug)
    return full_response


async def view_overall_performance(slug, db, payload):
    result = await view_performance_helper(
        slug=slug, context="view_overall_performance", db=db, payload=payload
    )
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
    average_sales_per_day = Decimal(total_gross_sales / days).quantize(TWO_PLACES)
    extreme_sale_row = (
        select(Payment.payment_date, Payment.total_amount, Payment.shipping_fee)
        .join(Order, Order.id == Payment.order_id)
        .where(
            Order.store_id == target_store.id,
            Payment.payment_status == PaymentStatus.SUCCESS.value,
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
        lowest_sale = {
            "date": lowest_sale_date,
            "sales": Decimal(l_sale).quantize(TWO_PLACES),
        }
    highest_sale_row = (
        await db.execute(extreme_sale_row.order_by(net_sales.desc()).limit(1))
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
        highest_sale = {
            "date": highest_sale_date,
            "sales": Decimal(h_sale).quantize(TWO_PLACES),
        }
    data = {
        "total_gross_sales": Decimal(total_gross_sales or "0.00").quantize(TWO_PLACES),
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
    result = await view_performance_helper(
        slug=slug, context="view_current_performance", db=db, payload=payload
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
        lowest_sale = {
            "date": lowest_sale_date,
            "sales": Decimal(l_sale).quantize(TWO_PLACES),
        }
    highest_sale_row = (
        await db.execute(extreme_sale_row.order_by(net_sales.desc()).limit(1))
    ).fetchone()
    if highest_sale_row:
        highest_sale_date, highest_sale_total, highest_sale_shipping = (
            highest_sale_row or (0, 0, 0)
        )
        h_sale = highest_sale_total - highest_sale_shipping
        highest_sale = {
            "date": highest_sale_date,
            "sales": Decimal(h_sale).quantize(TWO_PLACES),
        }
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
            Review.product_id.is_(None),
            Review.time_of_post >= first_of_the_month,
        )
        .scalar_subquery(),
        select(func.avg(Review.ratings))
        .where(
            Review.store_id == target_store.id,
            Review.product_id.is_(None),
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
        "average_ratings_this_month": Decimal(avg_ratings or "0.00").quantize(
            Decimal("0.1")
        ),
        "gross_sales_this_month": Decimal(gross_sales_this_month or "0.00").quantize(
            TWO_PLACES
        ),
        "highest_sales": highest_sale,
        "lowest_sales": lowest_sale,
        "daily_average": Decimal(daily_avg or "0.00").quantize(TWO_PLACES),
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
    result = await view_performance_helper(
        slug=slug,
        context="products_stats",
        context_1=ranking,
        context_2=time_frame,
        db=db,
        payload=payload,
    )
    if isinstance(result, dict):
        return StandardResponse(**result)
    c_key, target_ = result
    cache_key = typing_cast(str, c_key)
    target_store = typing_cast(Store, target_)
    now = datetime.now(timezone.utc)
    time_map = {
        "total": target_store.founded,
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
                Product.id,
                Product.primary_image,
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
                Product.id,
                Product.primary_image,
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
                Product.id,
                Product.primary_image,
                Product.product_name,
                Product.product_size,
                func.coalesce(avg_ratings, 0.00),
            )
            .join(Review, Product.id == Review.product_id)
            .join(Store, Product.store_id == Store.id)
            .where(
                Review.time_of_post >= time_period,
                Store.slug == slug,
            )
            .group_by(
                Product.id,
                Product.primary_image,
                Product.product_name,
                Product.product_size,
            )
            .order_by(order_count(avg_ratings))
            .limit(5)
        )
    ).all()
    if not products and not product_ratings:
        logger.warning("product stats returned null")
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
            {
                "id": p_id,
                "image": get_public_url(img),
                "product_name": name,
                "product_size": size,
                "quantity_sold": int(qty),
            }
            for p_id, img, name, size, qty in products
        ],
        "product_ratings": [
            {
                "id": p_id,
                "image": get_public_url(img),
                "product_name": name,
                "product_size": size,
                "ratings": Decimal(rts).quantize(Decimal("0.1")),
            }
            for p_id, img, name, size, rts in product_ratings
        ],
    }
    full_response = StandardResponse(status="success", message=message, data=data)
    await cached(cache_key, full_response, ttl=600)
    return full_response


async def select_products_stats(slug, product_id, stats, db, payload):
    result = await view_performance_helper(
        slug=slug,
        context="select_products_stats",
        context_1=product_id,
        context_2=stats,
        db=db,
        payload=payload,
    )
    if isinstance(result, dict):
        return StandardResponse(**result)
    c_key, _ = result
    cache_key = typing_cast(str, c_key)
    if stats not in ["product_sales", "product_ratings"]:
        raise HTTPException(
            status_code=400,
            detail="this endpoint is only ranked by 'product_sales' or 'product_ratings'",
        )
    products = None
    product_ratings = None
    if stats == "product_sales":
        product_sales = func.sum(OrderItem.quantity).label("total_quantity")
        products = (
            await db.execute(
                select(
                    Product.id,
                    Product.primary_image,
                    Product.product_name,
                    Product.product_size,
                    cast(func.coalesce(product_sales, 0), Integer),
                )
                .join(Store, Product.store_id == Store.id)
                .join(OrderItem, OrderItem.product_id == Product.id)
                .join(Order, OrderItem.order_id == Order.id)
                .join(Payment, Order.id == Payment.order_id)
                .where(
                    Store.slug == slug,
                    Product.id == product_id,
                    Payment.payment_status == PaymentStatus.SUCCESS.value,
                )
                .group_by(
                    Product.id,
                    Product.primary_image,
                    Product.product_name,
                    Product.product_size,
                )
            )
        ).fetchone()
    else:
        avg_ratings = func.avg(Review.ratings).label("average_ratings")
        product_ratings = (
            await db.execute(
                select(
                    Product.id,
                    Product.primary_image,
                    Product.product_name,
                    Product.product_size,
                    func.coalesce(avg_ratings, 0.00),
                )
                .join(Review, Product.id == Review.product_id)
                .join(Store, Product.store_id == Store.id)
                .where(
                    Store.slug == slug,
                    Product.id == product_id,
                )
                .group_by(
                    Product.id,
                    Product.primary_image,
                    Product.product_name,
                    Product.product_size,
                )
            )
        ).fetchone()
    if not products and not product_ratings:
        logger.warning("product stats returned null")
        return StandardResponse(
            status="success",
            message=f"no available {stats} found for product: {product_id}",
            data=None,
        )
    message = "product sales" if stats == "product_sales" else "product ratings"
    if stats == "product_sales" and products:
        p_id, img, name, size, qty = products
        data = {
            "id": p_id,
            "image": get_public_url(img),
            "product_name": name,
            "product_size": size,
            "quantity_sold": int(qty),
        }
    elif stats == "product_ratings" and product_ratings:
        p_id, img, name, size, rts = product_ratings
        data = {
            "id": p_id,
            "image": get_public_url(img),
            "name": name,
            "product_size": size,
            "ratings": Decimal(rts).quantize(Decimal("0.1")),
        }
    full_response = StandardResponse(status="success", message=message, data=data)
    await cached(cache_key, full_response, ttl=60)
    return full_response


async def inventory_stats(slug, stock_range, db, payload):
    result = await view_performance_helper(
        slug=slug, context=stock_range, db=db, payload=payload
    )
    if isinstance(result, dict):
        return StandardResponse(**result)
    c_key, target_ = result
    cache_key = typing_cast(str, c_key)
    target_store = typing_cast(Store, target_)
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
    if not ranges and ranges != 0:
        raise HTTPException(status_code=400, detail="invalid stock range selected")
    inventories_stmt = (
        select(
            Product.id,
            Product.primary_image,
            Product.product_name,
            Product.product_size,
            Inventory.stock_quantity,
        )
        .join(Inventory, Product.id == Inventory.product_id)
        .where(
            Product.store_id == target_store.id,
        )
        .order_by(Inventory.stock_quantity.desc())
    )
    if stock_range == "above_fifty":
        inventories_stmt = inventories_stmt.where(Inventory.stock_quantity > ranges)
    elif stock_range == "out_of_stock":
        inventories_stmt = inventories_stmt.where(Inventory.stock_quantity == ranges)
    elif stock_range == "ten_below":
        inventories_stmt = inventories_stmt.where(
            Inventory.stock_quantity <= ranges, Inventory.stock_quantity > 5
        )
    elif stock_range == "five_below":
        inventories_stmt = inventories_stmt.where(
            Inventory.stock_quantity <= ranges, Inventory.stock_quantity > 0
        )
    elif stock_range == "twenty_below":
        inventories_stmt = inventories_stmt.where(
            Inventory.stock_quantity <= ranges, Inventory.stock_quantity > 10
        )
    elif stock_range == "thirty_below":
        inventories_stmt = inventories_stmt.where(
            Inventory.stock_quantity <= ranges, Inventory.stock_quantity > 10
        )
    elif stock_range == "fifty_below":
        inventories_stmt = inventories_stmt.where(
            Inventory.stock_quantity <= ranges, Inventory.stock_quantity > 30
        )
    inventories = (await db.execute(inventories_stmt)).all()
    if not inventories:
        logger.warning("inventory stats returned null")
        return StandardResponse(
            status="success",
            message=f"No products found within the {stock_range} range.",
            data=None,
        )
    data = {
        "items": [
            {
                "id": p_id,
                "image": get_public_url(img),
                "product_name": name,
                "product_size": size,
                "stock_quantity": qty,
            }
            for p_id, img, name, size, qty in inventories
        ],
    }
    full_response = StandardResponse(
        status="success",
        message=f"inventory statistics for {stock_range} range",
        data=data,
    )
    await cached(cache_key, full_response, ttl=600)
    return full_response
