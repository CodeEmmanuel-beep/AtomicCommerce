from app.models import (
    Messaging,
    User,
    Ticket,
    Store,
    TicketStatus,
    store_owners,
    store_staffs,
    OutboxEvent,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select, or_, func, update
from sqlalchemy.orm import selectinload
from app.database.get import AsyncSessionLocal
from app.utils.helper import upload_photo_helper
from app.utils.supabase_url import create_signed_urls, _supabase, cleaned_up
from fastapi import Depends, WebSocket, APIRouter, WebSocketDisconnect
from starlette.requests import HTTPConnection
import orjson
import uuid
import asyncio
from redis.exceptions import ResponseError
from jose import jwt, JWTError, ExpiredSignatureError
from app.database.config import settings
from app.utils.redis import redis_client, STREAM_NAME
from app.services.transactional_outbox_service import (
    mark_event_as_published,
    schedule_retry,
    claim_outbox_events,
)
from app.logs.logger import get_logger

logger = get_logger("websocket")

router = APIRouter(prefix="/websocket", tags=["Real Time Messaging"])

active_connections: dict[int, WebSocket] = {}


async def get_active_connections(
    user_id, ws: WebSocket, get_supabase
) -> dict[int, WebSocket]:
    active_connections[user_id] = ws
    try:
        async with AsyncSessionLocal() as db:
            try:
                messages = (
                    (
                        await db.execute(
                            select(Messaging)
                            .join(Ticket, Messaging.ticket_id == Ticket.id)
                            .options(
                                selectinload(Messaging.ticket).selectinload(
                                    Ticket.store
                                ),
                                selectinload(Messaging.user),
                            )
                            .where(
                                Ticket.status.in_(
                                    (TicketStatus.open, TicketStatus.in_progress)
                                ),
                                or_(
                                    Messaging.support_id == user_id,
                                    Messaging.customer_id == user_id,
                                ),
                                Messaging.user_id != user_id,
                                Messaging.delivered.is_(False),
                            )
                            .order_by(Messaging.time_of_chat.asc(), Messaging.id.asc())
                        )
                    )
                    .scalars()
                    .all()
                )
                for message in messages:
                    try:
                        payload = {
                            "message_id": message.id,
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


async def publish_to_users(user_id):
    delay = 1
    channel_name = f"chat:{user_id}"
    while True:
        pubsub = None
        try:
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(channel_name)
            async for message in pubsub.listen():
                ws = active_connections.get(user_id)
                if message["type"] != "message":
                    continue
                delay = 1
                if ws is not None and message["type"] == "message":
                    await ws.send_json(orjson.loads(message["data"]))
        except asyncio.CancelledError:
            logger.error("async publisher for customer support websocket closed")
            raise
        except Exception:
            logger.exception(
                "failed to process message for receiver '%s'",
                user_id,
            )
            await asyncio.sleep(delay)
            delay = min(2 * delay, 20)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(channel_name)
                except Exception:
                    logger.exception("Failed to unsubscribe from %s", channel_name)
                await pubsub.aclose()


@router.websocket("/ws/{token}")
async def get_connection(
    ws: WebSocket,
    token: str,
    request: HTTPConnection,
    store_id: int | None = None,
    cus_id: int | None = None,
    tick_id: int | None = None,
    get_supabase=Depends(_supabase),
) -> WebSocket | None:
    accepted = False
    publisher_task = None
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
                if store_id is not None:
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
        await ws.accept()
        accepted = True
        publisher_task = asyncio.create_task(publish_to_users(user_id))
        await get_active_connections(user_id, ws, get_supabase)
        while True:
            data = await ws.receive_json()
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
                    {
                        "event_id": str(uuid.uuid4()),
                        "event_type": "websocket.typing",
                        "data": orjson.dumps(broadcast_data),
                    },
                )
                continue
            if action.get("activity") and action.get("activity") == "ack":
                action_msg_id = action.get("msg_id")
                if not isinstance(action_msg_id, int) or isinstance(
                    action_msg_id, bool
                ):
                    await ws.send_json({"error": "Invalid message ID"})
                    continue
                async with AsyncSessionLocal() as db:
                    delivered = await db.execute(
                        update(Messaging)
                        .where(
                            or_(
                                Messaging.support_id == user_id,
                                Messaging.customer_id == user_id,
                            ),
                            Messaging.user_id != user_id,
                            Messaging.ticket_id == current_ticket_id,
                            Messaging.id == action_msg_id,
                            Messaging.delivered.is_(False),
                        )
                        .values(delivered=True)
                    )
                    await db.commit()
                if delivered.rowcount == 1:
                    await ws.send_json({"acknowledged": action_msg_id})
                continue
            if action.get("activity") and action.get("activity") == "read":
                action_msg_id = action.get("msg_id")
                if not isinstance(action_msg_id, int) or isinstance(
                    action_msg_id, bool
                ):
                    await ws.send_json({"error": "Invalid message ID"})
                    continue
                async with AsyncSessionLocal() as db:
                    seen = await db.execute(
                        update(Messaging)
                        .where(
                            or_(
                                Messaging.support_id == user_id,
                                Messaging.customer_id == user_id,
                            ),
                            Messaging.user_id != user_id,
                            Messaging.id == action_msg_id,
                            Messaging.seen.is_(False),
                            Messaging.ticket_id == current_ticket_id,
                        )
                        .values(seen=True)
                    )
                    await db.commit()
                if seen.rowcount == 1:
                    await ws.send_json({"seen": action_msg_id})
                continue
            message = data.get("message")
            photo = data.get("photo")
            if not message and not photo:
                await ws.send_json({"error": "message or photo is required"})
                continue
            if photo:
                photo = await upload_photo_helper(
                    photo, request, get_supabase, user_id, settings.BUCKET1, skip=True
                )
                photo_url = await create_signed_urls(
                    photo,
                    expires=3600,
                    context="message photo",
                    get_supabase=get_supabase,
                )
            payload = {
                "action": "message",
                "store_name": store_name,
                "sender": f"{first_name} {last_name}",
                "message": message,
                "photo": photo_url,
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
                    payload["message_id"] = new_message.id
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
    except WebSocketDisconnect:
        logger.info("User %s disconnected from WebSocket", user_id)
    except Exception:
        logger.exception("Unexpected WebSocket error for user %s", user_id)
    finally:
        if publisher_task is not None:
            publisher_task.cancel()
            try:
                await publisher_task
            except asyncio.CancelledError:
                pass
        remove_active_connection(user_id, ws)
        if accepted:
            try:
                await ws.close()
            except Exception:
                pass


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
