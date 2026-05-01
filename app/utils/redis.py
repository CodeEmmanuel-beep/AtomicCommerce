import orjson
from app.database.config import settings
from redis import asyncio as aioredis
from fastapi.encoders import jsonable_encoder
import asyncio
from typing import Optional
import aiopg
import time
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


async def product_review_invalidation():
    value = await redis_client.incr("product_review_key")
    await redis_client.expire("product_review_key", 18000)
    return value


async def product_reply_invalidation():
    value = await redis_client.incr("product_reply_key")
    await redis_client.expire("product_reply_key", 18000)
    return value


async def store_review_invalidation():
    value = await redis_client.incr("store_review_key")
    await redis_client.expire("store_review_key", 18000)
    return value


async def store_reply_invalidation():
    value = await redis_client.incr("store_reply_key")
    await redis_client.expire("store_reply_key", 18000)
    return value


async def store_invalidation():
    value = await redis_client.incr("store_key")
    await redis_client.expire("company_review_key", 18000)
    return value


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


async def run_router():
    dsn = f"db_name={settings.DB_NAME} user={settings.DB_USER} password={settings.DB_PASSWORD}"
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
                                user_id = payload.get("user_id")
                                if user_id is not None:
                                    channel_name = f"notifications_{user_id}"
                                    await redis_client.publish(
                                        channel_name, orjson.dumps(payload)
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
