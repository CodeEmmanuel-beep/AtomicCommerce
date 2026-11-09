import orjson
from app.database.config import settings
from redis import asyncio as aioredis
from fastapi.encoders import jsonable_encoder
import asyncio
import aiopg
import time
from datetime import datetime
from app.models import Notification
from app.database.async_config import AsyncSessionLocal
from app.logs.logger import get_logger
from dataclasses import dataclass
from sqlalchemy.exc import SQLAlchemyError
import socket
import uuid
from redis.exceptions import ResponseError

STREAM_NAME = "chat_stream"
CONSUMER_GROUP = f"chat_cross_worker_delivery"
CONSUMER_NAME = f"worker:{socket.gethostname()} id: {uuid.uuid4().hex}"


def decode(val):
    if isinstance(val, bytes):
        return val.decode("utf-8")
    return val


redis_url = settings.REDIS_URL
if redis_url.startswith("rediss://"):
    redis_client = aioredis.from_url(
        redis_url, ssl_cert_reqs=None, decode_responses=True, socket_timeout=15
    )
else:
    redis_client = aioredis.from_url(
        redis_url, decode_responses=True, socket_timeout=15
    )


async def cache_version(key: str, ttl: int = 18000) -> int:
    value = await redis_client.get(key)
    if value is None:
        await redis_client.set(key, 1, ex=ttl, nx=True)
        return 1
    try:
        return int(value)
    except (ValueError, TypeError):
        await redis_client.set(key, 1, ex=ttl)
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


async def store_products_invalidation(store_id: int):
    value = await redis_client.incr(f"store_product_key:{store_id}")
    await redis_client.expire(f"store_product_key:{store_id}", 9000)
    return value


async def product_review_invalidation(product_id: int):
    value = await redis_client.incr(f"product_review_key:{product_id}")
    await redis_client.expire(f"product_review_key:{product_id}", 7200)
    return value


async def product_reply_invalidation(product_id: int):
    version_key = f"product_reply_key:{product_id}"
    value = await redis_client.incr(version_key)
    await redis_client.expire(version_key, 7200)
    return value


async def store_review_invalidation(store_id: int):
    value = await redis_client.incr(f"store_review_key:{store_id}")
    await redis_client.expire(f"store_review_key:{store_id}", 7200)
    return value


async def store_reply_invalidation(store_id: int):
    value = await redis_client.incr(f"store_reply_key:{store_id}")
    await redis_client.expire(f"store_reply_key:{store_id}", 7200)
    return value


async def store_invalidation_global():
    value = await redis_client.incr("store_key")
    await redis_client.expire("store_key", 18100)
    return value


async def product_variant_invalidation(variant_id: int | str | list):
    if isinstance(variant_id, (str, int)):
        variant_id = [variant_id]
    for v_id in variant_id:
        value = await redis_client.incr(f"variant_key:{v_id}")
        await redis_client.expire(f"variant_key:{v_id}", 7300)
    return value


async def product_variants_invalidation(product_id: str | int | list):
    if isinstance(product_id, (str, int)):
        product_id = [product_id]
    for p_id in product_id:
        value = await redis_client.incr(f"product_variant_key:{p_id}")
        await redis_client.expire(f"product_variant_key:{p_id}", 7300)
    return value


async def profile_global_invalidation():
    version = "profile_keys"
    value = await redis_client.incr(version)
    await redis_client.expire(version, 4500)
    return value


async def store_invalidation(user_id: int):
    cursor = 0
    pattern = f"store_view:{user_id}:*"
    delete = False
    while True:
        cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=1000)
        if keys:
            await redis_client.unlink(*keys)
            delete = True
        if cursor == 0 or cursor == b"0":
            break
    return delete


async def notification_invalidation(user_id: int | None = None):
    cursor = 0
    pattern = f"notification:{user_id}:*"
    delete = False
    while True:
        cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=1000)
        if keys:
            await redis_client.unlink(*keys)
            delete = True
        if cursor == 0 or cursor == b"0":
            break
    return delete


async def order_global_invalidation(store_id: int):
    value = await redis_client.incr(f"store_order_key:{store_id}")
    await redis_client.expire(f"store_order_key:{store_id}", 4000)
    return value


async def cart_invalidation(user_id: int):
    cursor = 0
    pattern = f"carts:v*:{user_id}:*"
    delete = False
    while True:
        cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=1000)
        if keys:
            await redis_client.unlink(*keys)
            delete = True
        if cursor == 0 or cursor == b"0":
            break
    return delete


async def product_version_invalidation(product_id: str | int | list):
    if isinstance(product_id, (str, int)):
        product_id = [product_id]
    for p_id in product_id:
        value = await redis_client.incr(f"product_key:{p_id}")
        await redis_client.expire(f"product_key:{p_id}", 9000)
    return value


async def cart_global_invalidation(store_id: int):
    value = await redis_client.incr(f"store_cart_key:{store_id}")
    await redis_client.expire(f"store_cart_key:{store_id}", 4000)
    return value


async def member_global_invalidation(store_id: int):
    value = await redis_client.incr(f"store_member_key:{store_id}")
    await redis_client.expire(f"store_member_key:{store_id}", 18100)
    return value


async def order_address_invalidation(user_id: int):
    cursor = 0
    pattern = f"delivery_address:{user_id}:*"
    delete = False
    while True:
        cursor, key = await redis_client.scan(cursor=cursor, match=pattern, count=1000)
        if key:
            redis_client.unlink(*key)
            delete = True
        if cursor == 0 or cursor == b"0":
            break
    return delete


async def profile_invalidation(user_id: int):
    cursor = 0
    pattern = f"profile:{user_id}"
    delete = False
    while True:
        cursor, key = await redis_client.scan(cursor=cursor, match=pattern, count=1000)
        if key:
            await redis_client.unlink(*key)
            delete = True
        if cursor in (0, "0", b"0"):
            break
    return delete


async def create_consumer_group():
    try:
        await redis_client.xgroup_create(
            STREAM_NAME, CONSUMER_GROUP, id="$", mkstream=True
        )
        logger.info(
            f"consumer group '{CONSUMER_GROUP}' created for stream: {STREAM_NAME}"
        )
    except ResponseError as e:
        if "BUSYGROUP" in str(e):
            logger.info(f"consumer group: {CONSUMER_GROUP} already running")
        else:
            raise


async def fanout_message():
    delay = 1
    while True:
        try:
            streams = await redis_client.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={STREAM_NAME: ">"},
                count=100,
                block=5000,
            )
            if not streams:
                delay = 1
            delay = 1
            for stream_key, messages in streams:
                for message_id, message in messages:
                    data = decode(message.get("data"))
                    event_id = decode(message.get("event_id", None))
                    event_type = decode(message.get("event_type", None))
                    try:
                        event = orjson.loads(data) if data else None
                    except (orjson.JSONDecodeError, TypeError):
                        logger.error("failed to parse data for message: %s", message_id)
                        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
                        continue
                    if not isinstance(event, dict):
                        logger.error("Redis event must be a dictionary")
                        await redis_client.xack(
                            STREAM_NAME,
                            CONSUMER_GROUP,
                            message_id,
                        )
                        continue
                    ticket_id = event.get("ticket_id", None)
                    receiver_id = event.get("receiver_id", None)
                    broadcast_payload = event.get("broadcast_payload")
                    if not isinstance(event_type, str):
                        logger.error("Invalid event_type for message %s", message_id)
                        await redis_client.xack(
                            STREAM_NAME,
                            CONSUMER_GROUP,
                            message_id,
                        )
                        continue
                    if not isinstance(broadcast_payload, dict):
                        logger.error(
                            "Invalid broadcast_payload for message %s", message_id
                        )
                        await redis_client.xack(
                            STREAM_NAME,
                            CONSUMER_GROUP,
                            message_id,
                        )
                        continue
                    if event_type.startswith("websocket"):
                        if not receiver_id:
                            logger.error(
                                "Missing receiver_id for message %s", message_id
                            )
                            await redis_client.xack(
                                STREAM_NAME, CONSUMER_GROUP, message_id
                            )
                            continue
                        await redis_client.publish(
                            f"chat:{receiver_id}",
                            orjson.dumps(
                                {
                                    k: v
                                    for k, v in broadcast_payload.items()
                                    if v is not None
                                },
                            ),
                        )
                        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
        except asyncio.CancelledError:
            logger.info("stream consumer task cancelled gracefully")
            raise
        except Exception:
            logger.exception("stream consumer encountered an error, reconnecting...")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


async def autoclaims():
    min_idle_time_ms = 60000
    start_id = "0-0"
    delay = 1
    while True:
        try:
            claimed_result = await redis_client.xautoclaim(
                name=STREAM_NAME,
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                min_idle_time=min_idle_time_ms,
                start_id=start_id,
                count=50,
            )
            next_start_id, messages, _ = claimed_result
            start_id = next_start_id
            if not messages:
                await asyncio.sleep(10)
                continue
            delay = 1
            for message_id, message in messages:
                event_id = decode(message.get("event_id"))
                event_type = decode(message.get("event_type"))
                data = decode(message.get("data"))
                if (
                    not isinstance(event_id, str)
                    or not isinstance(event_type, str)
                    or not isinstance(data, (str, bytes))
                ):
                    logger.error("invalid event payload for message: %s", message_id)
                    await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
                    continue
                try:
                    event = orjson.loads(data)
                except orjson.JSONDecodeError:
                    logger.error("failed to parse reclaimed message: %s", message_id)
                    await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
                    continue
                if not isinstance(event, dict):
                    logger.error("Reclaimed event must be a dictionary")
                    await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
                    continue
                ticket_id = event.get("ticket_id")
                receiver_id = event.get("receiver_id")
                broadcast_payload = event.get("broadcast_payload")
                if not isinstance(broadcast_payload, dict):
                    logger.error(
                        "reclaimed broadcast payload for message '%s' must be dictionary",
                        message_id,
                    )
                    await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
                    continue
                if event_type.startswith("websocket"):
                    if not receiver_id:
                        logger.error("Missing receiver_id for message %s", message_id)
                        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
                        continue
                    await redis_client.publish(
                        f"chat:{receiver_id}",
                        orjson.dumps(
                            {
                                k: v
                                for k, v in broadcast_payload.items()
                                if v is not None
                            }
                        ),
                    )
                    await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
        except asyncio.CancelledError:
            logger.info("autoclaim worker cancelled gracefully")
            raise
        except Exception:
            logger.exception("autoclaim worker encountered an error, retrying...")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 20)


async def notifications_stream(user_id: int | None = None):
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


@dataclass
class QueueNotifications:
    data: dict
    retries: int = 0


async def add_commit_periodically(queue: asyncio.Queue[QueueNotifications]):
    while True:
        items: list[QueueNotifications] = []
        try:
            item = await queue.get()
            items.append(item)
            try:
                while len(items) < 100:
                    item = await asyncio.wait_for(queue.get(), timeout=0.1)
                    items.append(item)
            except asyncio.TimeoutError:
                pass
            db_objects = []
            for item in items:
                db_objects.append(Notification(**item.data))
            try:
                async with AsyncSessionLocal() as db:
                    db.add_all(db_objects)
                    await db.commit()
            except SQLAlchemyError:
                logger.exception(
                    "Failed to persist notification batch of %d",
                    len(items),
                )
                for item in items:
                    item.retries += 1
                    if item.retries < 3:
                        try:
                            queue.put_nowait(item)
                            queue.task_done()
                        except asyncio.QueueFull:
                            logger.error(
                                "Queue full. Dropping notification on retry attempt %d",
                                item.retries,
                            )
                            queue.task_done()
                    else:
                        logger.error(
                            "Dropping notifications which failed to commit after %s retries",
                            item.retries,
                        )
                        queue.task_done()
            else:
                for _ in items:
                    queue.task_done()
        except asyncio.CancelledError:
            logger.warning(
                "Worker task cancelled mid-batch. Attempting to preserve %d items",
                len(items),
            )
            for item in items:
                try:
                    queue.put_nowait(item)
                    queue.task_done()
                except asyncio.QueueFull:
                    logger.error("Queue full during task cancellation. Dropping item.")
                    queue.task_done()
            raise
        except Exception:
            logger.exception("could not save notification")
            for item in items:
                try:
                    item.retries += 1
                    if item.retries < 3:
                        queue.put_nowait(item)
                        queue.task_done()
                    else:
                        logger.error("Dropping notification after retries")
                        queue.task_done()
                except asyncio.QueueFull:
                    logger.error(
                        "Queue full. Dropping notification on retry attempt %d",
                        item.retries,
                    )
                    queue.task_done()
                except Exception:
                    logger.exception(
                        "Unexpected error handling item retry. Dropping item."
                    )
                    queue.task_done()
            await asyncio.sleep(1.0)


notification_queue = asyncio.Queue(maxsize=1000)


async def run_router():
    dsn = f"dbname={settings.DB_NAME} user={settings.DB_USER} password={settings.DB_PASSWORD} host={settings.DB_HOST} port={settings.DB_PORT}"
    last_heartbeat = 0
    delay = 1
    while True:
        try:
            async with aiopg.connect(dsn) as conn, conn.cursor() as cursor:
                await cursor.execute("LISTEN app_events;")
                logger.info("Router running.. waiting for database events")
                delay = 1
                while True:
                    current_time = time.time()
                    if current_time - last_heartbeat > 180:
                        await redis_client.set(
                            "router_heartbeat", int(current_time), ex=185
                        )
                        last_heartbeat = current_time
                        logger.info("Heartbeat sent: Router is healthy.")
                    try:
                        notify = await asyncio.wait_for(conn.notifies.get(), timeout=5)
                    except asyncio.TimeoutError:
                        continue
                    payload = orjson.loads(notify.payload)
                    time_op = payload.get("time")
                    notice = QueueNotifications(
                        data={
                            "notification": payload.get("notification"),
                            "from_user": payload.get("inserter"),
                            "notified_user": payload.get("user_id"),
                            "time_of_op": datetime.fromisoformat(
                                time_op.replace("Z", "+00:00")
                            ),
                            "product_id": payload.get("product_id"),
                            "variant_id": payload.get("variant_id"),
                            "store_id": payload.get("store_id"),
                            "status": payload.get("status"),
                            "membership_type": payload.get("type"),
                            "is_active": payload.get("is_active"),
                            "is_deleted": payload.get("is_deleted"),
                        }
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
        except Exception:
            logger.exception("run_router crash")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
