from app.models import Payment, Order, Review, Store, User
from app.utils.redis import cache, cached
from sqlalchemy import cast, Float, Date, select, func
from fastapi import HTTPException
from app.logs.logger import get_logger
from datetime import date
from dateutil.relativedelta import relativedelta

logger = get_logger("store_analytics")


async def view_store_data(slug, db):
    cache_key = f"store_data:{slug}"
    cached_data = await cache(cache_key)
    if cached_data:
        logger.info("cache hit at view store data endpoint for store %s", slug)
        return cached_data
    store_exists = (
        await db.execute(select(Store).where(Store.slug == slug, Store.approved))
    ).scalar_one_or_none()
    if not store_exists:
        logger.error("user tried accessing an unvailable store: %s", slug)
        raise HTTPException(status_code=404, detail="store not found")
    target_store = select(
        func.count(Order.id)
        .where(Order.store_id == store_exists.id)
        .scalar_subquery()
        .label("store_orders"),
        select(func.max(Order.created_at))
        .where(Order.store_id == store_exists.id)
        .scalar_subquery()
        .label("last_order"),
        select(func.count(Review.ratings))
        .where(Review.store_id == store_exists.id)
        .scalar_subquery()
        .label("total_ratings"),
        select(func.avg(cast(Review.ratings, Float)))
        .where(Review.store_id == store_exists.id)
        .scalar_subquery()
        .label("avg_ratings"),
    )
    result = await db.execute(target_store)
    row = result.first()
    (
        store_orders,
        last_order,
        store_total_ratings,
        store_average_ratings,
    ) = row
    data = {
        "store_total_orders": store_orders or 0,
        "last_order": last_order,
        "store_total_ratings": store_total_ratings or 0,
        "store_average_ratings": round(float(store_average_ratings or 0), 2),
    }
    await cached(cache_key, data, ttl=300)
    logger.info("data returned at view store data endpoint for store: %s", slug)
    return data


async def view_store_details(slug, db):
    cache_key = f"store_details:{slug}"
    cached_data = await cache(cache_key)
    if cached_data:
        logger.info("cache hit at view store details endpoint for store: %s", slug)
        return cached_data
    target_store = (
        await db.execute(select(Store).where(Store.slug == slug, Store.approved))
    ).scalar_one_or_none()
    if not target_store:
        logger.error("user tried accessing an unvailable store: %s", slug)
        raise HTTPException(status_code=404, detail="store not found")
    data = {
        "store_previous_name": target_store.store_previous_name,
        "motto": target_store.motto,
        "store_description": target_store.store_description,
        "founded": target_store.founded,
    }
    data = {k: v for k, v in data.items() if v is not None}
    await cached(cache_key, data, ttl=300)
    logger.info(
        "data returned at view store details endpoint for store: %s", target_store.id
    )
    return data


async def view_overall_performance(slug, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at the view overall performance endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    cache_key = f"overall_performance:{slug}"
    cached_data = await cache(cache_key)
    if cached_data:
        logger.info(
            "cache hit at the view overall performance endpoint for store: %s", slug
        )
        return cached_data
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
        logger.warning("user: %s, tried experienced permission err: %s", user_id, slug)
        raise HTTPException(status_code=403, detail="restricted access")
    today = date.today()
    if today < target_store.founded + relativedelta(months=1):
        return {
            "message": "performance statistics are revealed one month after onboarding"
        }
    total_gross_sales = (
        await db.execute(
            select(func.sum(Payment.amount_paid))
            .join(Order, Order.id == Payment.order_id)
            .where(
                Order.store_id == target_store.id, Payment.payment_status == "approved"
            )
        ).scalar()
        or 0
    )
    daily_sales = (
        select(
            cast(Payment.payment_date, Date).label("day"),
            func.sum(Payment.amount_paid).label("daily_sale"),
        )
        .join(Order, Payment.order_id == Order.id)
        .where(Order.store_id == target_store.id, Payment.payment_status == "approved")
        .group_by(cast(Payment.payment_date, Date))
        .cte("daily_turnover")
    )
    avg_daily = select(func.avg(daily_sales.c.daily_sale))
    average_sales = (await db.execute(avg_daily)).scalar() or 0
    average_sales_per_day = round(float(average_sales or 0), 2)
    extreme_sale_row = (
        select(Payment.payment_date, Payment.amount_paid)
        .join(Order, Order.id == Payment.order_id)
        .where(Order.store_id == target_store.id, Payment.payment_status == "approved")
    )
    lowest_sale_row = (
        await db.execute(extreme_sale_row.order_by(Payment.amount_paid.asc()).limit(1))
    ).first()
    lowest_sale = (
        {"date": lowest_sale_row[0], "sales": float(lowest_sale_row[1])}
        if lowest_sale_row
        else None
    )
    highest_sale_row = (
        await db.execute(extreme_sale_row.order_by(Payment.amount_paid.desc()).limit(1))
    ).first()
    highest_sale = (
        {"date": highest_sale_row[0], "sales": float(highest_sale_row[1])}
        if highest_sale_row
        else None
    )
    average_sales_per_week = round(average_sales_per_day * 7, 2)
    average_sales_per_month = round(average_sales_per_day * 30, 2)
    data = {
        "total_gross_sales": round(float(total_gross_sales or 0), 2),
        "highest_sales": highest_sale,
        "lowest_sales": lowest_sale,
        "average_sales_per_day": average_sales_per_day or 0,
        "average_sales_per_week": average_sales_per_week or 0,
        "average_sales_per_month": average_sales_per_month or 0,
    }
    await cached(cache_key, data, ttl=300)
    logger.info(
        "data returned at view overall performance endpoint for store: %s", slug
    )
    return data


async def view_current_performance(slug, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at the view current performance endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    cache_key = f"current_performance:{slug}"
    cached_data = await cache(cache_key)
    if cached_data:
        logger.info(
            "cache hit at the view current performance endpoint for store: %s", slug
        )
        return cached_data
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
        logger.warning("user: %s, tried experienced permission err: %s", user_id, slug)
        raise HTTPException(status_code=403, detail="restricted access")
    today = date.today()
    gross_sales_this_month = (
        await db.execute(
            select(func.sum(Payment.amount_paid))
            .join(Order, Payment.order_id == Order.id)
            .where(
                Order.store_id == target_store.id,
                Payment.payment_status == "approved",
                Payment.payment_date >= today.replace(day=1),
            )
        ).scalar()
        or 0
    )
    extreme_sale_row = (
        select(Payment.payment_date, Payment.amount_paid)
        .join(Order, Order.id == Payment.order_id)
        .where(
            Order.store_id == target_store.id,
            Payment.payment_status == "approved",
            Payment.payment_date >= today.replace(day=1),
        )
    )
    turnover = (
        select(
            cast(Payment.payment_date, Date),
            func.sum(Payment.amount_paid).label("daily_sum"),
        )
        .join(Order, Payment.order_id == Order.id)
        .where(
            Order.store_id == target_store.id,
            Payment.payment_status == "approved",
            Payment.payment_date >= today.replace(day=1),
        )
        .group_by(cast(Payment.payment_date, Date))
        .cte("monthly_average")
    )
    result = select(func.avg(cast(turnover.c.daily_sum, Float)))
    daily_avg = (await db.execute(result)).scalar() or 0
    lowest_sale_row = (
        await db.execute(extreme_sale_row.order_by(Payment.amount_paid.asc()).limit(1))
    ).first()
    lowest_sale = (
        {"date": lowest_sale_row[0], "sales": float(lowest_sale_row[1])}
        if lowest_sale_row
        else None
    )
    highest_sale_row = (
        await db.execute(extreme_sale_row.order_by(Payment.amount_paid.desc()).limit(1))
    ).first()
    highest_sale = (
        {"date": highest_sale_row[0], "sales": float(highest_sale_row[1])}
        if highest_sale_row
        else None
    )
    today = date.today()
    ratings_orders__check = select(
        (
            select(func.count(Order.id))
            .where(
                Order.store_id == target_store.id,
                Order.created_at >= today.replace(day=1),
            )
            .scalar_subquery()
        ),
        select(func.max(Order.created_at))
        .where(
            Order.store_id == target_store.id, Order.created_at >= today.replace(day=1)
        )
        .scalar_subquery(),
        select(func.count(Review.ratings))
        .where(
            Review.store_id == target_store.id,
            Review.date_of_review >= today.replace(day=1),
        )
        .scalar_subquery(),
        select(func.avg(cast(Review.ratings, Float)))
        .where(
            Review.store_id == target_store.id,
            Review.date_of_review >= today.replace(day=1),
        )
        .scalar_subquery(),
    )
    result_check = await db.execute(ratings_orders__check)
    row = result_check.first()
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
    await cached(cache_key, data, ttl=300)
    logger.info(
        "data returned at view current performance endpoint for store: %s", slug
    )
    return data
