from app.models import Order, Product, OrderItem, OrderStatus
from app.database.async_config import AsyncSessionLocal, engine
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from datetime import timedelta, datetime, timezone
from app.logs.logger import get_logger
import asyncio
from celery.signals import worker_process_init
from celery import shared_task

logger = get_logger("celery")


async def invalidate_order():
    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        time_limit = now - timedelta(hours=1)
        retry_limit = now - timedelta(minutes=30)
        try:
            stmt = (
                select(Order)
                .options(
                    selectinload(Order.orderitems)
                    .selectinload(OrderItem.product)
                    .selectinload(Product.inventory)
                )
                .where(
                    or_(
                        Order.created_at <= time_limit,
                        Order.re_order_time <= retry_limit,
                    ),
                    Order.status == OrderStatus.pending,
                )
                .with_for_update()
            )
            result = await session.execute(stmt)
            row = result.scalars().all()
            if not row:
                logger.info("No expired orders found for invalidation.")
                return
            logger.info("preparing to invalidate order")
            CHUNK_SIZE = 100
            for i in range(0, len(row), CHUNK_SIZE):
                chunk = row[i : i + CHUNK_SIZE]
                for order in chunk:
                    order.status = OrderStatus.cancelled
                    if order.re_order_time and order.re_order_time <= retry_limit:
                        order.order_delete = True
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


def get_worker_loop():
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


@worker_process_init.connect
def set_up_worker_process(**kwargs):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(engine.dispose())
    logger.info("worker process database engine reset complete.")


@shared_task(
    name="app.utils.scheduled_task.cancel_order",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5, "countdown": 10},
)
def cancel_order():
    try:
        loop = get_worker_loop()
        loop.run_until_complete(invalidate_order())
    except Exception as e:
        logger.exception(
            "fatal processing exception occurred during batch order invalidation"
        )
        raise e
