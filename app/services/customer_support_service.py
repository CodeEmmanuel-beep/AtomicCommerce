from app.api.v1.schemas import (
    Chat,
    StandardResponse,
    PaginatedResponse,
)
from app.models import Messaging, User, Ticket, TicketStatus
from fastapi import HTTPException
from datetime import timezone, datetime
from app.logs.logger import get_logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, or_, func, and_, update
from app.utils.redis import cache, cached
from app.utils.helper import upload_photo_helper
from app.utils.supabase_url import cleaned_up

logger = get_logger("chat_support")


async def text_support(message, pics, subject, db, payload, get_supabase):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Unauthorized attempt st the text_support endpoint")
        raise HTTPException(status_code=401, detail="not a valid user")
    allowed_roles = ["Owner", "customer_care"]
    try:
        stmt = (
            select(User)
            .outerjoin(
                Ticket,
                and_(
                    User.id == Ticket.assigned_to,
                    Ticket.status.in_([TicketStatus.open, TicketStatus.in_progress]),
                ),
            )
            .where(
                User.role.in_(allowed_roles),
                User.is_active,
            )
            .group_by(User.id)
            .order_by(func.count(Ticket.id).asc())
        )
        receive = (await db.execute(stmt)).scalars().first()
    except Exception:
        logger.exception("database error while fetching customer support")
        raise HTTPException(status_code=400, detail="databaase error")
    if not receive:
        logger.info("Message send failed: support support not found.")
        raise HTTPException(status_code=404, detail="no active support found")
    filename = None
    if pics is not None:
        filename = await upload_photo_helper(pics, db, payload, get_supabase)
    else:
        pics = None
    if not message and not pics:
        logger.info(f"Message send failed: empty message from user '{user_id}'.")
        raise HTTPException(status_code=400, detail="can not send empty messages")
    logger.info(f"User '{user_id}' is sending a message to 'customer support'.")
    new_ticket = Ticket(
        user_id=user_id,
        subject=subject,
        description=message or "Attachment only",
        assigned_to=receive.id,
    )
    db.add(new_ticket)
    await db.flush()
    new_message = Messaging(
        user_id=user_id,
        pics=filename,
        message=message,
        ticket_id=new_ticket.id,
        time_of_chat=datetime.now(timezone.utc),
    )
    db.add(new_message)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                f"failed to remove orphaned  file for user '{user_id}'.",
                "removed orphaned file from database",
            )
        logger.error("database error at text_support endpoint")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                f"failed to remove orphaned  file for user '{user_id}'.",
                "removed orphaned file from database",
            )
        logger.exception("error at text_support endpoint")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"Message successfully sent from '{user_id}' to customer.")
    return {"success": "message successfully sent to customer support"}


async def ticket_thread(message, ticket_id, pics, db, payload, get_supabase):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Unauthorized attempt at text_customer endpoint")
        raise HTTPException(status_code=401, detail="not a valid user")
    filename = None
    if pics:
        filename = await upload_photo_helper(pics, db, payload, get_supabase)
    ticket = (
        await db.execute(
            select(Ticket)
            .where(
                Ticket.id == ticket_id,
                or_(Ticket.assigned_to == user_id, Ticket.user_id == user_id),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=403, detail="restricted service")
    if ticket.status == TicketStatus.closed:
        raise HTTPException(status_code=400, detail="ticket already closed")
    if not message and not pics:
        logger.info(f"Message send failed: empty message from user '{user_id}'.")
        raise HTTPException(status_code=400, detail="can not send empty messages")
    receiver = ticket.assigned_to if user_id == ticket.user_id else ticket.user_id
    logger.info(
        f"User '{user_id}' is sending a message to '{receiver}', ticket_id: {ticket.id}"
    )
    new_message = Messaging(
        user_id=user_id,
        ticket_id=ticket.id,
        pics=filename,
        message=message,
        time_of_chat=datetime.now(timezone.utc),
    )
    if ticket.user_id == user_id:
        new_message.support_id = ticket.assigned_to
        new_message.customer_id = user_id
    elif ticket.assigned_to == user_id:
        new_message.customer_id = ticket.user_id
        new_message.support_id = ticket.assigned_to
    else:
        raise HTTPException(status_code=403, detail="invalid participant")
    try:
        ticket.status = (
            TicketStatus.in_progress
            if ticket.status == TicketStatus.open
            else ticket.status
        )
        db.add(new_message)
        await db.commit()
        await db.refresh(new_message)
    except IntegrityError:
        await db.rollback()
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                f"failed to remove orphaned  file for user '{user_id}'.",
                "removed orphaned file from database",
            )
        logger.error("database error at text_customer endpoint")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                f"failed to remove orphaned  file for user '{user_id}'.",
                "removed orphaned file from database",
            )
        logger.exception("error at text_customer endpoint")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(
        f"Message successfully sent from '{user_id}' to '{receiver}', ticket_id:{ticket.id}"
    )
    return {"success": "message sent successfully"}


async def customer_support_view(
    ticket_id,
    view,
    page,
    limit,
    db,
    payload,
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Unauthorized attempt at the customer_view_message endpoint")
        raise HTTPException(status_code=401, detail="not a valid user")
    if page < 1 or limit < 1:
        raise HTTPException(
            status_code=400, detail="page number and limit must be greater than 0"
        )
    offset = (page - 1) * limit
    cache_key = f"mailbox:{user_id}:{ticket_id}:{view}:{page}:{limit}"
    message_cache = await cache(cache_key)
    if message_cache:
        logger.info(
            f"cache hit for ticket_id: {ticket_id}, page: {page} at customer_support_view endpoint"
        )
        return StandardResponse(**message_cache)
    conversation_key = func.concat(
        func.least(Messaging.customer_id, Messaging.support_id),
        ":",
        func.greatest(Messaging.support_id, Messaging.customer_id),
    )
    filters = (
        Messaging.customer_id == user_id
        if view == "customer_view"
        else Messaging.support_id == user_id
    )
    base_filter = or_(
        and_(
            Messaging.ticket_id == ticket_id,
            Messaging.user_id == user_id,
            ~Messaging.sender_deleted,
        ),
        and_(
            Messaging.ticket_id == ticket_id,
            filters,
            ~Messaging.receiver_deleted,
        ),
    )
    stmt = (
        select(Messaging, conversation_key.label("conversation_id"))
        .where(base_filter)
        .order_by(Messaging.time_of_chat.desc())
    )
    total = (
        await db.execute(select(func.count(Messaging.id)).where(base_filter))
    ).scalar() or 0
    logger.info(f"Total messages found with customer support: {total}")
    view_result = (await db.execute(stmt.offset(offset).limit(limit))).all()
    if not view_result:
        logger.info(
            "user: %s, search for customer support messages returned null", user_id
        )
        return {"status": "success", "message": "no messages"}
    if view == "customer_view":
        msg_ids_to_mark = [
            m.id
            for m, _ in view_result
            if m.customer_id == user_id and m.user_id != user_id and not m.delivered
        ]
        support_id = next((m.support_id for m, _ in view_result if m.support_id), None)
        if support_id is None:
            raise HTTPException(status_code=409, detail="can not access support")
        support_obj = await db.get(User, support_id)
    elif view == "support_view":
        msg_ids_to_mark = [
            m.id
            for m, _ in view_result
            if m.support_id == user_id and m.user_id != user_id and not m.delivered
        ]
        customer_id = next(
            (m.customer_id for m, _ in view_result if m.customer_id), None
        )
        if customer_id is None:
            raise HTTPException(status_code=409, detail="can not access support")
        customer_obj = await db.get(User, customer_id)
    if msg_ids_to_mark:
        await db.execute(
            update(Messaging)
            .where(Messaging.id.in_(msg_ids_to_mark), ~Messaging.delivered)
            .values(delivered=True, seen=True)
        )
        await db.commit()
    conversations = {}
    for msg, conv_id in view_result:
        chat_data = Chat.model_validate(msg)
        if view == "customer_view":
            chat_data.customer_support = support_obj.name
        elif view == "support_view":
            chat_data.customer = customer_obj.name
        conversations.setdefault(conv_id, []).append(chat_data)
    data = {
        "conversations": conversations,
        "pagination": PaginatedResponse(page=page, limit=limit, total=total),
    }
    logger.info(
        f"Fetched messages between '{user_id}' and customer support (page={page})."
    )
    full_response = StandardResponse(
        status="success", message="your messages", data=data
    )
    await cached(cache_key, full_response, ttl=30)
    return full_response


async def support_view(
    page,
    limit,
    db,
    payload,
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning(f"Unauthorized access attempt by user: {user_id}")
        raise HTTPException(status_code=403, detail="not a valid user")
    offset = (page - 1) * limit
    restricted = (
        (await db.execute(select(User).where(User.id == user_id, User.role == "c_c")))
        .scalars()
        .all()
    )
    if not restricted:
        raise HTTPException(status_code=403, detail="restricted service")
    conversation_key = func.concat(
        func.least(Messaging.customer, Messaging.customer_support),
        ":",
        func.greatest(Messaging.customer_support, Messaging.customer),
    )
    stmt = (
        select(Messaging, conversation_key.label("conversation_id"))
        .where(
            or_(
                and_(
                    Messaging.identifier == user_id, Messaging.sender_deleted == False
                ),
                and_(Messaging.user_id == user_id, Messaging.receiver_deleted == False),
            )
        )
        .distinct(conversation_key)
        .order_by(conversation_key, Messaging.time_of_chat.desc())
    )
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar() or 0
    logger.info(f"Total conversations found for user '{user_id}': {total}")
    view = (await db.execute(stmt.offset(offset).limit(limit))).all()
    for msg, _ in view:
        if msg.identifier == user_id:
            await db.execute(
                update(Messaging)
                .where(Messaging.identifier == user_id, Messaging.delivered == False)
                .values(delivered=True)
            )
    await db.commit()
    customer_ids = [msg.id for msg in view]
    customer = await db.execute(select(User).where(User.id.in_(customer_ids)))
    customer_map = {c.id: c for c in customer.scalars().all()}
    conversations = {}
    for msg, conv_id in view:
        chat_data = Chat.model_validate(msg)
        customer_name = customer_map.get(msg.id)
        chat_data.customer = customer_name.name
        conversations.setdefault(conv_id, []).append(chat_data)
    data = {
        "conversations": conversations,
        "pagination": PaginatedResponse(page=page, limit=limit, total=total),
    }
    logger.info(f"Fetched conversations for user '{user_id}' (page={page}).")
    return StandardResponse(status="success", message="your messages", data=data)


async def support_customer(
    customer_id,
    page,
    limit,
    db,
    payload,
):
    user_id = payload.get(user_id)
    username = payload.get("sub")
    if not user_id:
        logger.warning(f"Unauthorized access attempt by user: {username}")
        raise HTTPException(status_code=403, detail="not a valid user")
    offset = (page - 1) * limit
    restricted = (
        (await db.execute(select(User).where(User.id == user_id, User.role == "c_c")))
        .scalars()
        .all()
    )
    if not restricted:
        raise HTTPException(status_code=403, detail="restricted service")
    conversation_key = func.concat(
        func.least(Messaging.customer, Messaging.customer_support),
        ":",
        func.greatest(Messaging.customer_support, Messaging.customer),
    )
    stmt = (
        select(Messaging, conversation_key.label("conversation_id"))
        .where(
            or_(
                and_(
                    Messaging.user_id == user_id,
                    Messaging.customer_id == customer_id,
                    Messaging.sender_deleted == False,
                ),
                and_(
                    Messaging.customer_id == customer_id,
                    Messaging.identifier == user_id,
                    Messaging.receiver_deleted == False,
                ),
            )
        )
        .order_by(Messaging.time_of_chat.desc())
    )
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar() or 0
    logger.info(
        f"Total messages found between '{username}' and '{customer_id}': {total}"
    )
    view = (await db.execute(stmt.offset(offset).limit(limit))).all()
    for msg, _ in view:
        if msg.receiver == username:
            msg.seen = True
    await db.commit()
    customer_ids = [msg.user_id for msg in view]
    customer = await db.execute(select(User).where(User.id.in_(customer_ids)))
    customer_map = {c.id: c for c in customer}
    conversations = {}
    for msg, conv_id in view:
        chat_data = Chat.model_validate(msg)
        customer_name = customer_map.get(msg.user)
        chat_data.customer = customer_name.name
        conversations.setdefault(conv_id, []).append(chat_data)
    data = {
        "conversations": conversations,
        "pagination": PaginatedResponse(page=page, limit=limit, total=total),
    }
    logger.info(
        f"Fetched messages between '{username}' and '{customer_id}' (page={page})."
    )
    return StandardResponse(status="success", message="your messages", data=data)


async def customer_delete_message(
    message_id,
    db,
    payload,
):
    user_id = payload.get("user_id")
    username = payload.get("sub")
    if not user_id:
        logger.warning(f"Unauthorized access attempt by user: {user_id}")
        raise HTTPException(status_code=403, detail="not a valid user")
    stmt = select(Messaging).where(Messaging.id == message_id)
    message = (await db.execute(stmt)).scalar_one_or_none()
    if not message:
        logger.info(f"Delete failed: message ID '{message_id}' not found.")
        raise HTTPException(status_code=404, detail="message not found")
    if message.customer_id != user_id and message.user_id != user_id:
        logger.warning(
            f"Unauthorized delete attempt by user '{user_id}' on message ID '{message_id}'."
        )
        raise HTTPException(status_code=400, detail="invalid operation")
    if message.user_id == user_id:
        message.sender_deleted = True
    elif message.customer_id == user_id:
        message.receiver_deleted = True
    try:
        await db.commit()
    except IntegrityError:
        logger.error(
            f"Failed to delete message ID '{message_id}' by user '{username}'."
        )
        await db.rollback()
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"Message ID '{message_id}' deleted by user '{username}'.")
    return {"success": f"message ID {message_id} successfully deleted"}


async def customer_care_delete_message(
    message_id,
    db,
    payload,
):
    user_id = payload.get("user_id")
    username = payload.get("sub")
    if not user_id:
        logger.warning(f"Unauthorized access attempt by user: {user_id}")
        raise HTTPException(status_code=403, detail="not a valid user")
    stmt = select(Messaging).where(Messaging.id == message_id)
    message = (await db.execute(stmt)).scalar_one_or_none()
    if not message:
        logger.info(f"Delete failed: message ID '{message_id}' not found.")
        raise HTTPException(status_code=404, detail="message not found")
    if message.identifier != user_id and message.user_id != user_id:
        logger.warning(
            f"Unauthorized delete attempt by user '{user_id}' on message ID '{message_id}'."
        )
        raise HTTPException(status_code=400, detail="invalid operation")
    if message.user_id == user_id:
        message.sender_deleted = True
    elif message.identifier == user_id:
        message.receiver_deleted = True
    try:
        await db.commit()
    except IntegrityError:
        logger.error(
            f"Failed to delete message ID '{message_id}' by user '{username}'."
        )
        await db.rollback()
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"Message ID '{message_id}' deleted by user '{username}'.")
    return {"success": f"message ID {message_id} successfully deleted"}


async def clear_conversations(
    db,
    payload,
):
    user_id = payload.get("user_id")
    username = payload.get("sub")
    if not user_id:
        logger.warning(f"Unauthorized access attempt by user: {user_id}")
        raise HTTPException(status_code=403, detail="not a valid user")
    stmt = select(Messaging).where((Messaging.user_id == user_id))
    messages = (await db.execute(stmt)).scalars().all()
    if not messages:
        logger.info(
            f"No messages found between '{username}' and customer support to delete."
        )
        raise HTTPException(status_code=404, detail="no messages found to delete")
    for message in messages:
        if message.user_id == user_id:
            message.sender_deleted = True
        elif message.customer_id == user_id:
            message.receiver_deleted = True
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error(
            f"Failed to clear conversation between '{username}' and customer support."
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(
        f"All messages between '{username}' and customer support deleted by user '{username}'."
    )
    return {"success": f"all messages with customer support successfully deleted"}


async def clear_conversation(
    chat_id,
    db,
    payload,
):
    user_id = payload.get("user_id")
    username = payload.get("sub")
    if not user_id:
        logger.warning(f"Unauthorized access attempt by user: {user_id}")
        raise HTTPException(status_code=403, detail="not a valid user")
    stmt = select(Messaging).where(
        (Messaging.user_id == user_id, Messaging.customer_id == chat_id)
    )
    messages = (await db.execute(stmt)).scalars().all()
    if not messages:
        logger.info(
            f"No messages found between '{username}' and '{chat_id}' to delete."
        )
        raise HTTPException(status_code=404, detail="no messages found to delete")
    for message in messages:
        if message.user_id == user_id:
            message.sender_deleted = True
        elif message.customer_id == user_id:
            message.receiver_deleted = True
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error(
            f"Failed to clear conversation between '{username}' and '{chat_id}'."
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(
        f"All messages between '{username}' and '{chat_id}' deleted by user '{username}'."
    )
    return {"success": f"all messages with {chat_id} successfully deleted"}
