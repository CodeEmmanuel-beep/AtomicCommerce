import orjson
from app.database.config import settings
from redis import asyncio as aioredis
from fastapi.encoders import jsonable_encoder
import asyncio
from typing import Optional
import aiopg
import time
from app.models import Notification
from app.database.async_config import AsyncSessionLocal
from app.logs.logger import get_logger

redis_url = settings.REDIS_URL
if redis_url.startswith("rediss://"):
    redis_client = aioredis.from_url(
        redis_url, ssl_cert_reqs=None, decode_responses=True
    )
else:
    redis_client = aioredis.from_url(redis_url, decode_responses=True)


async def cache_version(key: str):
    value = await redis_client.get(key)
    if value is None:
        return 1
    try:
        return int(value)
    except (ValueError, TypeError):
        return 1


async def cache(key: str):
    value = await redis_client.get(key)
    if value:
        return orjson.loads(value)
    return None


async def cached(key: str, data, ttl=60):
    data = data.model_dump(exclude_none=True, exclude_defaults=True)
    payload = jsonable_encoder(data)
    await redis_client.set(key, orjson.dumps(payload), ex=ttl)


async def product_invalidation():
    value = await redis_client.incr("product_key")
    await redis_client.expire("product_key", 18000)
    return value


async def product_review_invalidation(product_id: int):
    value = await redis_client.incr(f"product_review_key:{product_id}")
    await redis_client.expire(f"product_review_key:{product_id}", 18000)
    return value


async def product_reply_invalidation(product_id: int):
    version_key = f"product_reply_key:{product_id}"
    value = await redis_client.incr(version_key)
    await redis_client.expire(version_key, 18000)
    return value


async def store_review_invalidation(store_id: int):
    value = await redis_client.incr(f"store_review_key:{store_id}")
    await redis_client.expire(f"store_review_key:{store_id}", 18000)
    return value


async def store_reply_invalidation(store_id: int):
    value = await redis_client.incr(f"store_reply_key:{store_id}")
    await redis_client.expire(f"store_reply_key:{store_id}", 18000)
    return value


async def store_invalidation_global():
    value = await redis_client.incr("store_key")
    await redis_client.expire("store_key", 18000)
    return value


async def store_invalidation(user_id: int):
    cursor = 0
    pattern = f"store_view:{user_id}:*"
    delete = False
    while True:
        cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=1000)
        if keys:
            await redis_client.delete(*keys)
            delete = True
        if cursor == 0 or cursor == b"0":
            break
    return delete


async def order_invalidation(user_id: int):
    cursor = 0
    pattern = f"orders:v*:{user_id}:*"
    delete = False
    while True:
        cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=1000)
        if keys:
            await redis_client.delete(*keys)
            delete = True
        if cursor == 0 or cursor == b"0":
            break
    return delete


async def notification_invalidation(user_id: Optional[int]):
    cursor = 0
    pattern = f"notification:{user_id}:*"
    delete = False
    while True:
        cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=1000)
        if keys:
            await redis_client.delete(*keys)
            delete = True
        if cursor == 0 or cursor == b"0":
            break
    return delete


async def order_global_invalidation():
    value = await redis_client.incr("order_key")
    await redis_client.expire("order_key", 18000)
    return value


async def cart_invalidation(user_id: int):
    cursor = 0
    pattern = f"carts:v*:{user_id}:*"
    delete = False
    while True:
        cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=1000)
        if keys:
            await redis_client.delete(*keys)
            delete = True
        if cursor == 0 or cursor == b"0":
            break
    return delete


async def cart_global_invalidation():
    value = await redis_client.incr("cart_key")
    await redis_client.expire("cart_key", 18000)
    return value


async def member_invalidation(user_id: int):
    cursor = 0
    pattern = f"members:v*:{user_id}:*"
    delete = False
    while True:
        cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=1000)
        if keys:
            await redis_client.delete(*keys)
            delete = True
        if cursor == 0 or cursor == b"0":
            break
    return delete


async def member_global_invalidation():
    value = await redis_client.incr("member_key")
    await redis_client.expire("member_key", 18000)
    return value


async def order_address_invalidation(user_id):
    cursor = 0
    pattern = f"delivery_address:{user_id}:*"
    delete = False
    while True:
        cursor, key = await redis_client.scan(cursor=cursor, match=pattern, count=1000)
        if key:
            redis_client.delete(*key)
            delete = True
        if cursor == 0 or cursor == b"0":
            break
    return delete


async def notifications_stream(user_id: Optional[int]):
    pubsub = redis_client.pubsub()
    channel_name = f"notifications_{user_id}"
    await pubsub.subscribe(channel_name)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                yield {"data": message["data"]}
            else:
                continue
    except asyncio.CancelledError:
        await pubsub.unsubscribe(channel_name)
        raise
    finally:
        await pubsub.close()


logger = get_logger("listener")


async def add_commit_periodically(queue: asyncio.Queue):
    while True:
        items = []
        try:
            item = await queue.get()
            items.append(item)
            try:
                while len(items) < 100:
                    item = await asyncio.wait_for(queue.get(), timeout=0.1)
                    items.append(item)
            except asyncio.TimeoutError:
                pass
            async with AsyncSessionLocal() as db:
                db.add_all(items)
                await db.commit()
            for _ in items:
                queue.task_done()
        except Exception:
            logger.exception("could not save notification")
            retry_items = []
            for item in items:
                item.retries = getattr(item, "retries", 0) + 1
                if item.retries < 3:
                    retry_items.append(item)
                else:
                    logger.error("Dropping notification after retries")
            for item in retry_items:
                await queue.put(item)


notification_queue = asyncio.Queue(maxsize=1000)


async def run_router():
    dsn = f"dbname={settings.DB_NAME} user={settings.DB_USER} password={settings.DB_PASSWORD} host={settings.DB_HOST} port={settings.DB_PORT}"
    last_heartbeat = 0
    while True:
        try:
            async with aiopg.connect(dsn) as conn:
                async with conn.cursor() as cur:
                    await cur.execute("LISTEN app_events;")
                    logger.info("Router running.. waiting for database events")
                    while True:
                        current_time = time.time()
                        if current_time - last_heartbeat > 180:
                            await redis_client.set(
                                "router_heartbeat", int(current_time)
                            )
                            last_heartbeat = current_time
                            logger.info("Heartbeat sent: Router is healthy.")
                        while conn.notifies:
                            try:
                                notify = conn.notifies.get_nowait()
                                payload = orjson.loads(notify.payload)
                                notice = Notification(
                                    notification=payload.get("notification"),
                                    notified_user=payload.get("user_id"),
                                    time_of_op=payload.get("time"),
                                )
                                await notification_queue.put(notice)
                                user_id = payload.get("user_id")
                                if user_id is not None:
                                    channel_name = f"notifications_{user_id}"
                                    await redis_client.publish(
                                        channel_name, orjson.dumps(payload).decode()
                                    )
                                    logger.info(
                                        "Routed event for op %s to %s",
                                        payload.get("action"),
                                        channel_name,
                                    )
                            except asyncio.QueueEmpty:
                                break
                        await asyncio.sleep(0.05)
        except Exception:
            logger.exception("run_router crash")
            await asyncio.sleep(1)
