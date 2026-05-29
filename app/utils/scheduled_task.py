from app.models import Order, Product, OrderItem, OrderStatus
from app.database.async_config import AsyncSessionLocal
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import timedelta, datetime, timezone
from app.logs.logger import get_logger
from functools import wraps
import asyncio
from app.utils.celery_app import celery_app

logger = get_logger("celery")


async def invalidate_order():
    async with AsyncSessionLocal() as session:
        time_limit = datetime.now(timezone.utc) - timedelta(hours=5)
        try:
            stmt = (
                select(Order)
                .options(
                    selectinload(Order.orderitems)
                    .selectinload(OrderItem.product)
                    .selectinload(Product.inventory)
                )
                .where(
                    Order.created_at <= time_limit, Order.status == OrderStatus.pending
                )
                .with_for_update(of=Order)
            )
            result = await session.execute(stmt)
            row = result.scalars().all()
            if not row:
                logger.info("No expired orders found for invalidation.")
                return
            logger.info("preparing to invalidate order")
            CHUNK_SIZE = 100
            for i in range(0, len(row), CHUNK_SIZE):
                chunk = all_expired_orders[i : i + CHUNK_SIZE]
                for order in chunk:
                    order.status = OrderStatus.cancelled
                    if order.orderitems:
                        for orderitems in order.orderitems:
                            if orderitems.product and orderitems.product.inventory:
                                stock = orderitems.product.inventory
                                stock.stock_quantity += orderitems.quantity
                                if (
                                    orderitems.product.product_availability
                                    == "out_of_stock"
                                ):
                                    orderitems.product.product_availability = (
                                        "available"
                                    )
                    logger.info(
                        "Order %s has been successfully cancelled and stock returned.",
                        order.id,
                    )
            await session.commit()
            logger.info("Batch order invalidated successfully")
        except Exception:
            await session.rollback()
            logger.exception(
                "fatal processing exception occurred during batch order invalidation"
            )


def async_wrapper(coro):
    @wraps(coro)
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro(*args, **kwargs))
        finally:
            loop.close()

    return wrapper


@celery_app.task
@async_wrapper
async def cancel_order():
    await invalidate_order()
