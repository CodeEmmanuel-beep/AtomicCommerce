from app.models import (
    Messaging,
    User,
    Ticket,
    Store,
    TicketStatus,
    store_owners,
    store_staffs,
    OutboxEvent,
    OutboxStatus,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select, or_, func, update, text, and_
from sqlalchemy.orm import selectinload
from app.database.get import AsyncSessionLocal
from app.utils.helper import upload_photo_helper
from app.utils.supabase_url import create_signed_urls, _supabase, cleaned_up
from fastapi import Depends, WebSocket, APIRouter, WebSocketDisconnect
import orjson
import uuid
import time
import asyncio
from datetime import datetime, timedelta, timezone
from redis.exceptions import ResponseError
from jose import jwt, JWTError, ExpiredSignatureError
from app.database.config import settings
from app.utils.redis import redis_client
import socket
from app.logs.logger import get_logger

logger = get_logger("websocket")

router = APIRouter(prefix="/websocket", tags=["Real Time Messaging"])

active_connections: dict[int, WebSocket] = {}

STREAM_NAME = "chat_stream"
CONSUMER_GROUP = (
    f"chat_cross_worker_delivery:{socket.gethostname()} id: {uuid.uuid4().hex}"
)
CONSUMER_NAME = f"worker:{socket.gethostname()} id: {uuid.uuid4().hex}"
TIME_OUT_ZSET = "offline_ticket_tracker"
GRACE_PERIOD = 1800


def decode(val):
    if isinstance(val, bytes):
        return val.decode("utf-8")
    return val


async def get_active_connections(
    user_id, ws: WebSocket, get_supabase
) -> dict[int, WebSocket]:
    await ws.accept()
    active_connections[user_id] = ws
    now = time.time()
    not_expired = await redis_client.zrangebyscore(
        TIME_OUT_ZSET, min=now + 30, max="+inf"
    )
    not_expired = {int(decode(t)) for t in not_expired}
    try:
        async with AsyncSessionLocal() as db:
            try:
                messages = (
                    (
                        await db.execute(
                            select(Messaging)
                            .options(
                                selectinload(Messaging.ticket).selectinload(
                                    Ticket.store
                                ),
                                selectinload(Messaging.user),
                            )
                            .where(
                                or_(
                                    Messaging.support_id == user_id,
                                    Messaging.customer_id == user_id,
                                ),
                                Messaging.delivered.is_(False),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for message in messages:
                    try:
                        if message.ticket_id in not_expired:
                            payload = {
                                "store_name": message.ticket.store.store_name,
                                "ticket_id": message.ticket_id,
                                "sender": f"{message.user.first_name} {message.user.surname}",
                                "message": message.message,
                                "photo": None,
                            }
                            if message.photo:
                                payload["photo"] = await create_signed_urls(
                                    message.photo,
                                    expires=3600,
                                    context="message photo",
                                    get_supabase=get_supabase,
                                )
                            await ws.send_json(
                                {k: v for k, v in payload.items() if v is not None}
                            )
                            message.delivered = True
                    except Exception:
                        logger.exception("failed to deliver messages")
                        continue
                await db.commit()
            except SQLAlchemyError:
                logger.exception("failed to mark messages as delivered")
                await db.rollback()
    except Exception:
        logger.exception("failed to deliver messages")
    return active_connections


def remove_active_connection(user_id: int, ws: WebSocket):
    if active_connections.get(user_id) is ws:
        del active_connections[user_id]


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


async def faniout_message():
    delay = 1
    try:
        await create_consumer_group()
    except Exception:
        logger.exception("failed to initialize redis consumer group")
        raise
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
            for stream_key, messages in streams:
                for message_id, message in messages:
                    data = decode(message.get("data"))
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
                    ticket_id = event.get("ticket_id")
                    receiver_id = event.get("receiver_id")
                    broadcast_payload = event.get("broadcast_payload")
                    try:
                        if receiver_id in active_connections:
                            await active_connections[receiver_id].send_json(
                                {
                                    k: v
                                    for k, v in broadcast_payload.items()
                                    if v is not None
                                }
                            )
                            await redis_client.zrem(TIME_OUT_ZSET, ticket_id)
                        else:
                            expire_time = time.time() + GRACE_PERIOD
                            await redis_client.zadd(
                                TIME_OUT_ZSET, {ticket_id: expire_time}
                            )
                        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
                    except Exception:
                        logger.exception(
                            "failed to process message '%s' for receiver '%s'",
                            message_id,
                            receiver_id,
                        )
        except asyncio.CancelledError:
            logger.info("stream consumer task cancelled gracefully")
            raise
        except Exception:
            logger.exception("stream consumer encountered an error, reconnecting...")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


async def ticket_timeout_sweeper():
    while True:
        try:
            await asyncio.sleep(60)
            now = time.time()
            expired = await redis_client.zrangebyscore(TIME_OUT_ZSET, min=0, max=now)
            if expired:
                try:
                    ticket_ids = {decode(t) for t in expired}
                    async with AsyncSessionLocal() as db:
                        await db.execute(
                            update(Ticket)
                            .where(Ticket.id.in_(ticket_ids), Ticket.status != "closed")
                            .values(status="closed")
                        )
                        await db.commit()
                    logger.info(
                        "Closed %d stale ticket(s) due to offline timeout",
                        len(ticket_ids),
                    )
                except SQLAlchemyError:
                    logger.exception("Error occurred while closing stale tickets")
                    await db.rollback()
                await redis_client.zremrangebyscore(TIME_OUT_ZSET, min=0, max=now)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Error in ticket timeout sweeper worker")


@router.websocket("/ws/{token}")
async def get_connection(
    ws: WebSocket,
    token: str,
    store_id: int | None = None,
    cus_id: int | None = None,
    tick_id: int | None = None,
    get_supabase=Depends(_supabase),
) -> WebSocket | None:
    accepted = False
    if token is None:
        await ws.close(code=4001, reason="missing token")
        return
    user_id = None
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id = payload.get("user_id")
        jti = payload.get("jti")
        if not user_id or not jti:
            await ws.accept()
            await ws.close(code=4001, reason="Invalid token payload")
            return
        try:
            async with redis_client.pipeline(transaction=False) as pipe:
                pipe.exists(f"banned_client:{user_id}")
                pipe.exists(f"blacklist:{jti}")
                is_banned, is_blacklist = await pipe.execute()
        except Exception:
            await ws.accept()
            await ws.close(code=4500, reason="Authentication store error")
            return
        if is_banned:
            await ws.accept()
            await ws.close(code=4003, reason="User is banned")
            return
        if is_blacklist:
            await ws.accept()
            await ws.close(code=4001, reason="User is logged out")
            return
    except ExpiredSignatureError:
        await ws.accept()
        await ws.close(code=4001, reason="Token expired")
        return
    except JWTError:
        await ws.accept()
        await ws.close(code=4001, reason="Invalid token")
        return
    try:
        try:
            receiver_id = None
            first_name = None
            last_name = None
            ticket_id = None
            store_name = None
            async with AsyncSessionLocal() as db:
                sender = (
                    await db.execute(
                        select(User.first_name, User.surname).where(User.id == user_id)
                    )
                ).one_or_none()
                if not sender:
                    await ws.close(code=1008, reason="User not found")
                    return
                first_name, last_name = sender
                if store_id:
                    store_exist = (
                        await db.execute(
                            select(Store.store_name).where(
                                Store.id == store_id, Store.is_deleted.is_(False)
                            )
                        )
                    ).scalar()
                    if not store_exist:
                        await ws.close(code=1008, reason="Store not found")
                        return
                    store_name = store_exist
                    is_owner = (
                        select(1)
                        .where(
                            store_owners.c.users_id == User.id,
                            store_owners.c.stores_id == store_id,
                        )
                        .exists()
                    )
                    is_staff = (
                        select(1)
                        .where(
                            store_staffs.c.users_id == User.id,
                            store_staffs.c.stores_id == store_id,
                        )
                        .exists()
                    )
                    ticket_count = (
                        select(
                            Ticket.assigned_to.label("assigned_to"),
                            func.count(Ticket.id).label("count"),
                        )
                        .where(
                            Ticket.status.in_(
                                [TicketStatus.open, TicketStatus.in_progress]
                            ),
                            Ticket.store_id == store_id,
                        )
                        .group_by(Ticket.assigned_to)
                        .subquery()
                    )
                    open_tickets = (
                        (
                            await db.execute(
                                select(Ticket)
                                .where(
                                    Ticket.user_id == user_id,
                                    Ticket.store_id == store_id,
                                    Ticket.subject == "Quick Ticket",
                                    Ticket.status.in_(
                                        [TicketStatus.open, TicketStatus.in_progress]
                                    ),
                                    Ticket.updated_at
                                    > (func.now() - text("INTERVAL '30 minutes'")),
                                )
                                .order_by(Ticket.updated_at.desc())
                                .limit(1)
                                .with_for_update(of=Ticket)
                            )
                        )
                        .scalars()
                        .all()
                    )
                    if open_tickets:
                        ticket_id = open_tickets[0].id
                        receiver_id = open_tickets[0].assigned_to
                    else:
                        receiver = (
                            (
                                await db.execute(
                                    select(User.id)
                                    .outerjoin(
                                        ticket_count,
                                        ticket_count.c.assigned_to == User.id,
                                    )
                                    .where(
                                        User.is_active.is_(True),
                                        or_(is_owner, is_staff),
                                    )
                                    .order_by(
                                        func.coalesce(ticket_count.c.count, 0).asc()
                                    )
                                    .limit(1)
                                    .with_for_update(of=User)
                                )
                            )
                            .scalars()
                            .first()
                        )
                        if not receiver:
                            await ws.close(code=1008, reason="Receiver not found")
                            return
                        receiver_id = receiver
                        ticket_ = Ticket(
                            user_id=user_id,
                            subject="Quick Ticket",
                            assigned_to=receiver_id,
                            store_id=store_id,
                        )
                        db.add(ticket_)
                        await db.commit()
                        await db.refresh(ticket_)
                        ticket_id = ticket_.id
                else:
                    customer_ticket = (
                        await db.execute(
                            select(Ticket)
                            .options(selectinload(Ticket.store))
                            .where(
                                Ticket.assigned_to == user_id,
                                Ticket.user_id == cus_id,
                                Ticket.id == tick_id,
                                Ticket.updated_at
                                > (func.now() - text("INTERVAL '30 minutes'")),
                                Ticket.status.in_(
                                    [TicketStatus.open, TicketStatus.in_progress]
                                ),
                            )
                            .order_by(Ticket.updated_at.desc())
                        )
                    ).scalar_one_or_none()
                    if not customer_ticket:
                        await ws.close(code=1008, reason="No ticket found")
                        return
                    customer_ticket.status = TicketStatus.in_progress
                    store_name = customer_ticket.store.store_name
                    await db.commit()
        except SQLAlchemyError as e:
            logger.exception(f"Database Error: {e}")
            await ws.close(code=1011, reason="database error")
            return
        await get_active_connections(user_id, ws, get_supabase)
        accepted = True
        while True:
            data = await ws.receive_json()
            if store_id is not None:
                current_ticket_id = ticket_id
                current_customer_id = user_id
                current_support_id = receiver_id
                receiver_id = receiver_id
            else:
                current_ticket_id = tick_id
                current_customer_id = cus_id
                current_support_id = user_id
                receiver_id = cus_id
            if not isinstance(data, dict):
                await ws.send_json(
                    {"error": "Invalid event, data must be a dictionary"}
                )
                continue
            action = data.get("action")
            if not isinstance(action, dict):
                await ws.send_json(
                    {"error": "Invalid event, action must be a dictionary"}
                )
                continue
            if action.get("activity") and action.get("activity") == "typing":
                broadcast_data = {
                    "ticket_id": current_ticket_id,
                    "receiver_id": receiver_id,
                    "broadcast_payload": {
                        "action": "typing",
                        "message": f"{first_name} is typing...",
                    },
                }
                await redis_client.xadd(
                    STREAM_NAME,
                    {"data": orjson.dumps(broadcast_data)},
                )
                continue
            if action.get("activity") and action.get("activity") == "ack":
                action_msg_id = action.get("msg_id")
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(Messaging)
                        .where(
                            or_(
                                Messaging.support_id == user_id,
                                Messaging.customer_id == user_id,
                            ),
                            Messaging.user_id != user_id,
                            Messaging.id == action_msg_id,
                            Messaging.delivered.is_(False),
                        )
                        .values(delivered=True)
                    )
                    await db.commit()
                await ws.send_json({"acknowledged": action_msg_id})
                continue
            if action.get("activity") and action.get("activity") == "read":
                action_msg_id = action.get("msg_id")
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(Messaging)
                        .where(
                            or_(
                                Messaging.support_id == user_id,
                                Messaging.customer_id == user_id,
                            ),
                            Messaging.user_id != user_id,
                            Messaging.id == action_msg_id,
                            Messaging.seen.is_(False),
                        )
                        .values(seen=True)
                    )
                    await db.commit()
                await ws.send_json({"seen": action_msg_id})
                continue
            message = data.get("message")
            photo = data.get("photo")
            if not message and not photo:
                await ws.send_json({"error": "message or photo is required"})
                continue
            if photo:
                photo = await upload_photo_helper(
                    photo, context="message photo", get_supabase=get_supabase
                )
            payload = {
                "action": "message",
                "store_name": store_name,
                "sender": f"{first_name} {last_name}",
                "message": message,
                "photo": photo,
            }
            try:
                async with AsyncSessionLocal() as db:
                    new_message = Messaging(
                        user_id=user_id,
                        customer_id=current_customer_id,
                        support_id=current_support_id,
                        ticket_id=current_ticket_id,
                        message=message,
                        photo=photo,
                    )
                    db.add(new_message)
                    await db.flush()
                    await db.refresh(new_message)
                    outbox_event = OutboxEvent(
                        aggregate_id=new_message.id,
                        event_type="websocket.customer_support",
                        payload={
                            "ticket_id": new_message.ticket_id,
                            "receiver_id": receiver_id,
                            "broadcast_payload": payload,
                        },
                    )
                    db.add(outbox_event)
                    await db.commit()
            except SQLAlchemyError as e:
                logger.exception(f"Database Error: {e}")
                await db.rollback()
                await cleaned_up(
                    get_supabase,
                    photo,
                    context_1="websocket photo cleanup success",
                    context_2="websocket photo cleanup failed",
                )
                await ws.send_json({"error": "Failed to save message"})
                continue
    except WebSocketDisconnect as e:
        logger.info(f"User {user_id} disconnected from WebSocket {e}")
    finally:
        remove_active_connection(user_id, ws)
        if accepted:
            await ws.close()


async def claim_outbox_events():
    try:
        async with AsyncSessionLocal() as db:
            try:
                token = uuid.uuid4().hex
                now = datetime.now(timezone.utc)
                result = await db.execute(
                    select(OutboxEvent)
                    .where(
                        or_(
                            and_(
                                OutboxEvent.status == OutboxStatus.pending,
                                or_(
                                    OutboxEvent.next_attempt_at <= now,
                                    OutboxEvent.next_attempt_at.is_(None),
                                ),
                            ),
                            and_(
                                OutboxEvent.status == OutboxStatus.processing,
                                OutboxEvent.locked_until <= now,
                            ),
                        )
                    )
                    .order_by(OutboxEvent.created_at.asc())
                    .limit(50)
                    .with_for_update(skip_locked=True)
                )
                events = result.scalars().all()
                claimed = []
                for event in events:
                    if event.attempts >= 5:
                        event.status = OutboxStatus.dead_letter
                        event.claim_token = None
                        event.locked_until = None
                        continue
                    event.status = OutboxStatus.processing
                    event.locked_until = now + timedelta(minutes=5)
                    event.claim_token = token
                    event.attempts += 1

                    claimed.append(
                        {
                            "event_id": event.id,
                            "event_type": event.event_type,
                            "aggregate_id": event.aggregate_id,
                            "payload": event.payload,
                            "claim_token": token,
                            "attempts": event.attempts,
                        }
                    )
                await db.commit()
                return claimed
            except SQLAlchemyError as e:
                logger.exception(f"Database Error: {e}")
                await db.rollback()
                return []
    except Exception as e:
        logger.exception(f"Unexpected Error during outbox claim: {e}")
        return []


async def mark_event_as_published(event_id, claim_token):
    try:
        async with AsyncSessionLocal() as db:
            try:
                await db.execute(
                    update(OutboxEvent)
                    .where(
                        OutboxEvent.id == event_id,
                        OutboxEvent.status == OutboxStatus.processing,
                        OutboxEvent.claim_token == claim_token,
                    )
                    .values(
                        status=OutboxStatus.published,
                        locked_until=None,
                        claim_token=None,
                        last_error=None,
                        published_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()
            except SQLAlchemyError as e:
                logger.exception(
                    f"Database Error while marking event as published: {e}"
                )
                await db.rollback()
    except Exception:
        logger.exception(f"Unexpected Error while marking event as published")


async def schedule_retry(event_id, claim_token, error_message):
    try:
        async with AsyncSessionLocal() as db:
            try:
                await db.execute(
                    update(OutboxEvent)
                    .where(
                        OutboxEvent.id == event_id,
                        OutboxEvent.claim_token == claim_token,
                    )
                    .values(
                        status=OutboxStatus.pending,
                        next_attempt_at=datetime.now(timezone.utc)
                        + timedelta(minutes=5),
                        last_error=error_message[:2000] if error_message else None,
                        locked_until=None,
                        claim_token=None,
                    )
                )
                await db.commit()
            except SQLAlchemyError as e:
                logger.exception(
                    f"Database Error while scheduling retry for event {event_id}: {e}"
                )
                await db.rollback()
    except Exception:
        logger.exception(
            f"Unexpected Error while scheduling retry for event {event_id}"
        )


async def publish_events():
    delay = 1
    while True:
        try:
            events = await claim_outbox_events()
            if not events:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 16)
                continue
            delay = 1
            for event in events:
                while True:
                    try:
                        await redis_client.xadd(
                            STREAM_NAME,
                            {
                                "event_id": str(event["event_id"]),
                                "event_type": event["event_type"],
                                "data": orjson.dumps(event["payload"]),
                            },
                        )
                        await mark_event_as_published(
                            event["event_id"], event["claim_token"]
                        )
                        break
                    except ResponseError as e:
                        logger.error(f"failed to publish event: {e}")
                        await schedule_retry(
                            event["event_id"], event["claim_token"], str(e)
                        )
                        break
                    except Exception as e:
                        logger.error(
                            f"Unexpected error publishing event {event['event_id']}: {e}"
                        )
                        await schedule_retry(
                            event["event_id"], event["claim_token"], str(e)
                        )
                        break
        except Exception:
            logger.exception("Unexpected error in publish_events loop")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 16)
