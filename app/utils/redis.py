import orjson
from app.database.config import settings
from redis import asyncio as aioredis
from fastapi.encoders import jsonable_encoder


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
