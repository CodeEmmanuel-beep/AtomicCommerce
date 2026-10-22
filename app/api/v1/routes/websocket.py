from websocket import WebSocket, WebSocketDisconnect
from app.models import (
    Messaging,
    User,
    Ticket,
    Store,
    TicketStatus,
    store_owners,
    store_staffs,
)
from sqlalchemy import select, or_, exists, func, update
from app.database.get import AsyncSessionLocal
from sqlalchemy.orm import selectinload
from app.utils.helper import unique_id, upload_photo_helper
from app.utils.supabase_url import create_signed_urls, _supabase
from fastapi import Depends, Request
from app.logs.logger import get_logger

logger = get_logger("websocket")

active_connections: dict[int, WebSocket] = {}


async def get_active_connections(user_id, ws: WebSocket) -> dict[int, WebSocket]:
    await ws.accept()
    active_connections[user_id] = ws
    return active_connections


def remove_active_connection(user_id: int):
    if user_id in active_connections:
        del active_connections[user_id]


async def get_connection(
    request: Request,
    ws: WebSocket,
    store_id: int,
    get_supabase=Depends(_supabase),
) -> WebSocket | None:
    user_id = unique_id(request)
    ticket_id = None
    try:
        async with AsyncSessionLocal() as db:
            sender = (
                await db.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if not sender:
                await ws.close(code=1008, reason="User not found")
                return
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
                    Ticket.status.in_([TicketStatus.open, TicketStatus.in_progress]),
                    Ticket.store_id == store_id,
                )
                .group_by(Ticket.assigned_to)
            )
            receiver = (
                (
                    await db.execute(
                        select(User)
                        .outerjoin(ticket_count, ticket_count.c.assigned_to == User.id)
                        .where(User.is_active.is_(True), or_(is_owner, is_staff))
                        .group_by(User.id, ticket_count.c.count)
                        .order_by(func.coalesce(ticket_count.c.count, 0).asc())
                    ).limit(1)
                )
                .scalars()
                .first()
            )
            if not receiver:
                await ws.close(code=1008, reason="Receiver not found")
                return
            ticket_ = Ticket(
                user_id=user_id,
                subject="Quick Ticket",
                assigned_to=receiver.id,
                store_id=store_id,
            )
            db.add(ticket_)
            await db.commit()
            await db.refresh(ticket_)
            ticket_id = ticket_.id
        await get_active_connections(user_id, ws)
        while True:
            data = await ws.receive_json()
            message = data.get("message")
            photo = data.get("photo")
            if not message and not photo:
                await ws.send_json({"error": "message or photo is required"})
                continue
            if photo:
                photo = await upload_photo_helper(
                    photo, context="message photo", get_supabase=get_supabase
                )
            async with AsyncSessionLocal() as db:
                new_message = Messaging(
                    user_id=user_id,
                    customer_id=user_id,
                    support_id=receiver.id,
                    ticket_id=ticket_.id,
                    message=message,
                    photo=photo,
                )
                db.add(new_message)
                await db.commit()
                await db.refresh(new_message)
            receiver_id = (
                new_message.support_id
                if new_message.user_id == new_message.customer_id
                else new_message.customer_id
            )
            new_message_id = new_message.id
            if receiver_id in active_connections:
                payload = {
                    "store_name": store_exist,
                    "sender": f"{sender.first_name} {sender.surname}",
                    "message": new_message.message,
                    "photo": None,
                }
                if new_message.photo:
                    payload["photo"] = await create_signed_urls(
                        new_message.photo,
                        expires=3600,
                        context="message photo",
                        get_supabase=get_supabase,
                    )
                await active_connections[receiver_id].send_json(payload)
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(Messaging)
                        .where(Messaging.id == new_message_id)
                        .values(delivered=True)
                    )
                    await db.commit()
    except WebSocketDisconnect:
        logger.info(f"User {user_id} disconnected from WebSocket")
        remove_active_connection(user_id)
        if ticket_id is not None:
            async with AsyncSessionLocal() as db:
                (
                    await db.execute(
                        update(Ticket)
                        .where(
                            Ticket.id == ticket_id,
                            Ticket.status != TicketStatus.closed,
                        )
                        .values(status=TicketStatus.closed)
                    )
                )
                await db.commit()
        await ws.close()
