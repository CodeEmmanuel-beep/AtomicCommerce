from app.api.v1.schemas import (
    Chat,
    StandardResponse,
    PaginatedResponse,
)
from app.models import (
    Messaging,
    User,
    Ticket,
    TicketStatus,
    Store,
    store_staffs,
    store_owners,
)
from app.database.config import settings
from sqlalchemy.orm import selectinload, contains_eager
from fastapi import HTTPException
from datetime import timezone, datetime, timedelta
from app.logs.logger import get_logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, or_, func, and_, update, case, exists
from app.utils.redis import cache, cached
from app.utils.supabase_url import cleaned_up, create_signed_urls, get_public_url
from app.utils.helper import upload_photo_helper

logger = get_logger("chat_support")


async def text_support(store_id, message, pics, subject, db, payload, get_supabase):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Unauthorized attempt at the text_support endpoint")
        raise HTTPException(status_code=401, detail="not a valid user")
    allowed_roles = ["Owner", "customer_care"]
    store_exist = (
        await db.execute(
            select(exists().where(Store.id == store_id, Store.is_deleted.is_(False)))
        )
    ).scalar()
    if not store_exist:
        raise HTTPException(status_code=404, detail="store not found")
    ticket_exist = (
        await db.execute(
            select(
                exists().where(
                    Ticket.user_id == user_id, Ticket.status != TicketStatus.closed
                )
            )
        )
    ).scalar()
    if ticket_exist:
        raise HTTPException(status_code=409, detail="you already have an active ticket")
    try:
        domain_check = (
            or_(
                store_owners.c.stores_id == store_id,
                store_staffs.c.stores_id == store_id,
            )
            if store_id
            else User.role.in_(allowed_roles)
        )
        subq = (
            select(
                Ticket.assigned_to.label("assigned"),
                func.count(Ticket.id).label("cnt"),
            )
            .where(Ticket.status.in_([TicketStatus.open, TicketStatus.in_progress]))
            .group_by(Ticket.assigned_to)
        ).subquery()
        stmt = select(User.id).outerjoin(subq, User.id == subq.c.assigned)
        if store_id:
            stmt = stmt.outerjoin(store_owners, User.id == store_owners.c.users_id)
            stmt = stmt.outerjoin(store_staffs, User.id == store_staffs.c.users_id)
        stmt = (
            stmt.where(
                domain_check,
                User.is_active.is_(True),
            )
            .group_by(User.id, subq.c.cnt)
            .order_by(func.coalesce(subq.c.cnt, 0).asc(), User.id)
        )
        receive = (await db.execute(stmt)).scalars().first()
    except Exception:
        logger.exception("database error while fetching customer support")
        raise HTTPException(status_code=400, detail="database error")
    if not receive:
        logger.info("Message send failed: support not found.")
        raise HTTPException(status_code=404, detail="no active support found")
    filename = None
    if not message and not pics:
        logger.info(f"Message send failed: empty message from user '{user_id}'.")
        raise HTTPException(status_code=400, detail="can not send empty messages")
    if pics:
        filename = await upload_photo_helper(
            pics, payload, get_supabase, settings.BUCKET1
        )
    logger.info(f"User '{user_id}' is sending a message to 'customer support'.")
    new_ticket = Ticket(
        user_id=user_id,
        subject=subject,
        store_id=store_id,
        assigned_to=receive,
    )
    db.add(new_ticket)
    await db.flush()
    new_message = Messaging(
        user_id=user_id,
        photo=filename,
        message=message,
        customer_id=user_id,
        support_id=receive,
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
    logger.info(f"Message successfully sent from '{user_id}' to customer support.")
    return StandardResponse(
        status="success", message="successfully sent to customer support", data=None
    )


async def ticket_thread(message, store_id, ticket_id, pics, db, payload, get_supabase):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Unauthorized attempt at text_customer endpoint")
        raise HTTPException(status_code=401, detail="not a valid user")
    filename = None
    if pics:
        filename = await upload_photo_helper(
            pics, payload, get_supabase, settings.BUCKET1
        )
    ticket = (
        await db.execute(
            select(Ticket)
            .where(
                Ticket.store_id == store_id,
                Ticket.id == ticket_id,
                or_(Ticket.assigned_to == user_id, Ticket.user_id == user_id),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not ticket:
        logger.warning(
            "user: %s, tried conversing on the wrong ticket, store_id: %s, ticket_id: %s",
            user_id,
            store_id,
            ticket_id,
        )
        raise HTTPException(status_code=404, detail="ticket not found")
    if ticket.status == TicketStatus.closed:
        logger.warning(
            "user: %s, tried conversing on a closed ticket, store_id: %s, ticket_id: %s",
            user_id,
            store_id,
            ticket_id,
        )
        raise HTTPException(status_code=400, detail="ticket already closed")
    if not message and not pics:
        logger.info("Message send failed: empty message from user '%s'", user_id)
        raise HTTPException(status_code=400, detail="can not send empty messages")
    receiver = ticket.assigned_to if user_id == ticket.user_id else ticket.user_id
    logger.info(
        "User '%s' is sending a message to '%s', ticket_id: %s",
        user_id,
        receiver,
        ticket.id,
    )
    new_message = Messaging(
        user_id=user_id,
        ticket_id=ticket.id,
        photo=filename,
        support_id=ticket.assigned_to,
        customer_id=ticket.user_id,
        message=message,
        time_of_chat=datetime.now(timezone.utc),
    )
    if ticket.assigned_to == user_id:
        ticket.status = TicketStatus.in_progress
    try:
        ticket.updated_at = datetime.now(timezone.utc)
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
    return StandardResponse(
        status="success", message="message sent successfully", data=None
    )


async def customer_support_messages(
    store_id, ticket_id, view, page, limit, db, payload, get_supabase
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Unauthorized attempt at the customer_view_messages endpoint")
        raise HTTPException(status_code=401, detail="not a valid user")
    offset = (page - 1) * limit
    view = view.lower().strip()
    if view not in {"customer_view", "support_view"}:
        raise HTTPException(status_code=400, detail="invalid view type")
    cache_key = f"mailbox:{user_id}:{ticket_id}:{view}:{page}:{limit}"
    message_cache = await cache(cache_key)
    if message_cache:
        logger.info(
            f"cache hit for ticket_id: {ticket_id}, page: {page} at customer_support_messages endpoint"
        )
        return StandardResponse(**message_cache)
    conversation_key = func.concat(
        func.least(Messaging.customer_id, Messaging.support_id),
        ":",
        func.greatest(Messaging.support_id, Messaging.customer_id),
    )
    role_filter = (
        Messaging.customer_id == user_id
        if view == "customer_view"
        else Messaging.support_id == user_id
    )
    base_filter = (
        role_filter,
        or_(
            and_(
                Messaging.ticket_id == ticket_id,
                Messaging.user_id == user_id,
                Messaging.sender_deleted.is_(False),
            ),
            and_(
                Messaging.ticket_id == ticket_id,
                Messaging.user_id != user_id,
                Messaging.receiver_deleted.is_(False),
            ),
        ),
    )
    stmt = (
        select(Messaging, conversation_key.label("conversation_id"))
        .join(Ticket, Messaging.ticket_id == Ticket.id)
        .options(
            selectinload(Messaging.user),
            selectinload(Messaging.ticket).selectinload(Ticket.store),
        )
        .where(*base_filter, Ticket.store_id == store_id)
        .order_by(Messaging.time_of_chat.desc())
    )
    total = (
        await db.execute(select(func.count(Messaging.id)).where(*base_filter))
    ).scalar() or 0
    logger.info(f"Total messages found with customer support: {total}")
    view_result = (await db.execute(stmt.offset(offset).limit(limit))).all()
    if not view_result:
        logger.info(
            "user: %s, search for customer support messages returned null", user_id
        )
        response = StandardResponse(status="success", message="no messages", data={})
        await cached(cache_key, response, ttl=7)
        return response
    if view == "customer_view":
        msg_ids_to_mark = [
            m.id
            for m, _ in view_result
            if m.customer_id == user_id and m.user_id != user_id and not m.seen
        ]
    elif view == "support_view":
        msg_ids_to_mark = [
            m.id
            for m, _ in view_result
            if m.support_id == user_id and m.user_id != user_id and not m.seen
        ]
    if msg_ids_to_mark:
        await db.execute(
            update(Messaging)
            .where(Messaging.id.in_(msg_ids_to_mark), Messaging.seen.is_(False))
            .values(seen=True, delivered=True)
        )
        await db.commit()
    photo = {}
    photos = [m.photo for m, _ in view_result]
    if photos:
        photo = (
            await create_signed_urls(
                photos, 7200, "customer_support_messages", get_supabase
            )
            or {}
        )
    customer_ids = [m.customer_id for m, _ in view_result]
    support_ids = [m.support_id for m, _ in view_result if m.customer_id]
    total_ids = list(set(customer_ids + support_ids))
    user_obj = (
        (await db.execute(select(User).where(User.id.in_(total_ids)))).scalars().all()
    )
    user_map = {u.id: u for u in user_obj}
    conversations = {}
    for msg, conv_id in view_result:
        support_obj = user_map.get(msg.support_id)
        customer_obj = user_map.get(msg.customer_id)
        chat_data = Chat.model_validate(msg)
        if chat_data.photo:
            chat_data.photo = photo.get(chat_data.photo)
        sender = "customer_support" if msg.user_id == msg.support_id else "customer"
        chat_data.sender = sender
        chat_data.ticket_status = msg.ticket.status if msg.ticket else None
        chat_data.customer_photo = (
            get_public_url(msg.user.profile_picture)
            if msg.user and msg.user.profile_picture
            else None
        )
        chat_data.store_photo = (
            msg.ticket.store.store_photo if msg.ticket and msg.ticket.store else None
        )
        chat_data.customer_support = (
            s := support_obj
        ) and f"{s.first_name} {s.surname}"
        chat_data.customer = (c := customer_obj) and f"{c.first_name} {c.surname}"
        conversations.setdefault(conv_id, []).append(chat_data)
    conversation_list = []
    for conv_id, msg_list in conversations.items():
        parent = msg_list[0]
        conversation_list.append(
            {
                "conversation_id": conv_id,
                "store_photo": getattr(parent, "store_photo", None),
                "customer_photo": getattr(parent, "customer_photo", None),
                "customer_support": getattr(parent, "customer_support", None),
                "customer": getattr(parent, "customer", None),
                "ticket_id": getattr(parent, "ticket_id", None),
                "ticket_status": getattr(parent, "ticket_status", None),
                "messages": [
                    m.model_dump(
                        exclude_none=True,
                        exclude_defaults=True,
                        exclude={
                            "customer_support",
                            "customer",
                            "ticket_id",
                            "ticket_status",
                            "store_photo",
                            "customer_photo",
                        },
                    )
                    for m in msg_list
                ],
            }
        )
    data = {
        "conversations": conversation_list,
        "pagination": PaginatedResponse(page=page, limit=limit, total=total),
    }
    logger.info(
        f"Fetched messages between '{user_id}' and customer support (page={page})."
    )
    full_response = StandardResponse(
        status="success", message="your messages", data=data
    )
    await cached(cache_key, full_response, ttl=3)
    return full_response


async def customer_support_conversations(views, page, limit, db, payload, get_supabase):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning(
            "Unauthorized access attempt at customer_support_conversations endpoint"
        )
        raise HTTPException(status_code=401, detail="not a valid user")
    offset = (page - 1) * limit
    views = views.lower().strip()
    if views not in {"customer_view", "support_view"}:
        raise HTTPException(status_code=400, detail="invalid view type")
    cache_key = f"conversations:{user_id}:{views}:{page}:{limit}"
    message_cache = await cache(cache_key)
    if message_cache:
        logger.info(
            f"cache hit for page: {page} at customer_support_conversations endpoint"
        )
        return StandardResponse(**message_cache)
    conversation_key = func.concat(
        func.least(Messaging.customer_id, Messaging.support_id),
        ":",
        func.greatest(Messaging.customer_id, Messaging.support_id),
    )
    filters = (
        Messaging.customer_id == user_id
        if views == "customer_view"
        else Messaging.support_id == user_id
    )
    base_filter = (
        filters,
        or_(
            and_(
                Messaging.user_id == user_id,
                Messaging.sender_deleted.is_(False),
            ),
            and_(Messaging.user_id != user_id, Messaging.receiver_deleted.is_(False)),
        ),
    )
    unread_subq = (
        select(
            conversation_key.label("unread_conv_id"),
            func.count(Messaging.id).label("unread_count"),
        )
        .where(*base_filter, Messaging.seen.is_(False), Messaging.user_id != user_id)
        .group_by(conversation_key)
        .subquery()
    )
    subq = (
        select(
            conversation_key.label("conversation_id"),
            func.max(Messaging.time_of_chat).label("latest_time"),
            func.max(Messaging.id).label("latest_id"),
        )
        .where(*base_filter)
        .group_by(conversation_key)
        .subquery()
    )
    stmt = (
        select(Messaging, subq.c.conversation_id, unread_subq.c.unread_count)
        .join(
            subq,
            and_(
                Messaging.time_of_chat == subq.c.latest_time,
                conversation_key == subq.c.conversation_id,
                Messaging.id == subq.c.latest_id,
            ),
        )
        .outerjoin(unread_subq, unread_subq.c.unread_conv_id == subq.c.conversation_id)
        .options(
            selectinload(Messaging.user),
            selectinload(Messaging.ticket).selectinload(Ticket.store),
        )
        .order_by(subq.c.latest_time.desc())
    )
    total = (await db.execute(select(func.count()).select_from(subq))).scalar() or 0
    logger.info(f"Total conversations found for user '{user_id}': {total}")
    view_result = (await db.execute(stmt.offset(offset).limit(limit))).all()
    if not view_result:
        logger.info(
            "user: %s, search for customer support conversations returned null", user_id
        )
        response = StandardResponse(status="success", message="no messages", data={})
        await cached(cache_key, response, ttl=10)
        return response
    if views == "customer_view":
        msg_ids_to_mark = [
            m.id
            for m, _, _ in view_result
            if m.customer_id == user_id and m.user_id != user_id and not m.delivered
        ]
    elif views == "support_view":
        msg_ids_to_mark = [
            m.id
            for m, _, _ in view_result
            if m.support_id == user_id and m.user_id != user_id and not m.delivered
        ]
    if msg_ids_to_mark:
        await db.execute(
            update(Messaging)
            .where(Messaging.id.in_(msg_ids_to_mark), Messaging.delivered.is_(False))
            .values(delivered=True)
        )
        await db.commit()
    other_ids = []
    cus_ids = [m.customer_id for m, _, _ in view_result]
    other_ids.extend(cus_ids)
    sup_ids = [m.support_id for m, _, _ in view_result if m.customer_id]
    other_ids.extend(sup_ids)
    other = await db.execute(select(User).where(User.id.in_(other_ids)))
    id_map = {c.id: c for c in other.scalars().all()}
    message_pic = {}
    photos = [msg.photo for msg, _, _ in view_result]
    if photos:
        message_pic = (
            await create_signed_urls(
                photos, 7200, "customer_support_convo", get_supabase
            )
            or {}
        )
    conversations = {}
    for msg, conv_id, unread_count in view_result:
        chat_data = Chat.model_validate(msg)
        chat_data.unread_count = unread_count or 0
        if chat_data.photo:
            chat_data.photo = message_pic.get(chat_data.photo)
        customer_obj = id_map.get(msg.customer_id)
        support_obj = id_map.get(msg.support_id)
        sender = "customer" if msg.user_id == msg.customer_id else "customer_support"
        chat_data.sender = sender
        chat_data.customer_support = (
            f"{support_obj.first_name} {support_obj.surname}" if support_obj else None
        )
        chat_data.ticket_status = msg.ticket.status if msg.ticket else None
        chat_data.customer = (c := customer_obj) and f"{c.first_name} {c.surname}"
        chat_data.store_photo = (
            get_public_url(msg.ticket.store.store_photo)
            if msg.ticket and msg.ticket.store
            else None
        )
        chat_data.customer_photo = get_public_url(
            customer_obj.profile_picture if customer_obj else None
        )
        conversations[conv_id] = chat_data
    conversations_list = [
        {
            "conversation_id": conv_id,
            "store_photo": getattr(msgs, "store_photo", None),
            "customer_photo": getattr(msgs, "customer_photo", None),
            "customer_support": getattr(msgs, "customer_support", None),
            "customer": getattr(msgs, "customer", None),
            "ticket_id": getattr(msgs, "ticket_id", None),
            "ticket_status": getattr(msgs, "ticket_status", None),
            "unread_count": getattr(msgs, "unread_count", None),
            "last_message": {
                k: v
                for k, v in msgs.model_dump(
                    exclude_none=True, exclude_defaults=True
                ).items()
                if k
                not in [
                    "customer_support",
                    "customer",
                    "unread_count",
                    "ticket_id",
                    "ticket_status",
                    "store_photo",
                    "customer_photo",
                ]
            },
        }
        for conv_id, msgs in conversations.items()
    ]
    data = {
        "conversations": conversations_list,
        "pagination": PaginatedResponse(page=page, limit=limit, total=total),
    }
    logger.info(f"Fetched conversations for user '{user_id}' (page={page}).")
    full_response = StandardResponse(
        status="success", message="your messages", data=data
    )
    await cached(cache_key, full_response, ttl=5)
    return full_response


async def mark_as_resolved(store_id, ticket_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Unauthorized access attempt at the mark_as_resolved endpoint")
        raise HTTPException(status_code=401, detail="not a valid user")
    try:
        ticket = (
            await db.execute(
                select(Ticket)
                .where(
                    Ticket.store_id == store_id,
                    Ticket.id == ticket_id,
                    Ticket.user_id == user_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if not ticket:
            logger.warning(
                "user: %s, tried accessing a ticket that does not match his credentials",
                user_id,
            )
            raise HTTPException(status_code=404, detail="ticket not found")
        if ticket.status == TicketStatus.closed:
            logger.warning(
                "user: %s, tried closing a ticket, already closed, store_id: %s, ticket_id: %s",
                user_id,
                store_id,
                ticket_id,
            )
            return StandardResponse(
                status="success", message="ticket already resolved", data=None
            )
        ticket.status = TicketStatus.closed
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error at mark_as_resolved endpoint")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(f"Failed to update ticket status for ticket '{ticket_id}'.")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"ticket '{ticket_id}' closed by user '{user_id}'.")
    return StandardResponse(status="success", message="ticket status closed", data=None)


async def close_ticket(store_id, ticket_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Unauthorized access attempt at the close_ticket endpoint")
        raise HTTPException(status_code=401, detail="not a valid user")
    try:
        ticket = (
            await db.execute(
                select(Ticket)
                .where(
                    Ticket.store_id == store_id,
                    Ticket.id == ticket_id,
                    Ticket.assigned_to == user_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if not ticket:
            logger.warning(
                "user: %s, tried accessing a ticket that does not match his credentials",
                user_id,
            )
            raise HTTPException(status_code=404, detail="ticket not found")
        if ticket.status == TicketStatus.closed:
            logger.warning(
                "user: %s, tried closing a ticket, already closed, store_id: %s, ticket_id: %s",
                user_id,
                store_id,
                ticket_id,
            )
            return StandardResponse(
                status="success", message="ticket already resolved", data=None
            )
        if ticket.status == TicketStatus.open:
            logger.warning(
                "user: %s, tried closing a ticket, not attended to, store_id: %s, ticket_id: %s",
                user_id,
                store_id,
                ticket_id,
            )
            raise HTTPException(
                status_code=400,
                detail="ticket cannot be closed yet, attend to the customer first",
            )
        if ticket.updated_at > datetime.now(timezone.utc) - timedelta(days=2):
            logger.warning(
                "user: %s, tried closing a ticket, too earkly, store_id: %s, ticket_id: %s",
                user_id,
                store_id,
                ticket_id,
            )
            raise HTTPException(status_code=400, detail="ticket cannot be closed yet")
        ticket.status = TicketStatus.closed
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error at close_ticket endpoint")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(f"Failed to update ticket status for ticket '{ticket_id}'.")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"ticket '{ticket_id}' closed by user '{user_id}'.")
    return StandardResponse(
        status="success", message="ticket closed due to inactivity", data=None
    )


async def remove_message(
    store_id,
    ticket_id,
    message_id,
    db,
    payload,
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Unauthorized access attempt at the remove_message endpoint")
        raise HTTPException(status_code=401, detail="not a valid user")
    try:
        message = (
            await db.execute(
                select(Messaging)
                .join(Ticket, Messaging.ticket_id == Ticket.id)
                .options(contains_eager(Messaging.ticket))
                .where(
                    Ticket.store_id == store_id,
                    Ticket.id == ticket_id,
                    Messaging.id == message_id,
                    Ticket.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if not message:
            logger.warning(
                "user: %s, tried deleting a non existent message of store_id: %s, ticket_id: %s,",
                user_id,
                store_id,
                ticket_id,
            )
            raise HTTPException(status_code=400, detail="message not found")
        is_sender = message.user_id == user_id
        is_receiver = message.customer_id == user_id
        if message.ticket.status != TicketStatus.closed:
            logger.warning(
                "user: %s, tried deleting messages from a ticket not closed yet, store_id: %s, ticket_id: %s",
                user_id,
                store_id,
                ticket_id,
            )
            raise HTTPException(
                status_code=400,
                detail="you can only delete messages from a closed ticket",
            )
        if is_sender:
            message.sender_deleted = True
        elif not is_sender and is_receiver:
            message.receiver_deleted = True
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error at remove_message endpoint")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            f"Failed to delete message ID '{message_id}' by user '{user_id}'."
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"Message ID '{message_id}' deleted by user '{user_id}'.")
    return StandardResponse(
        status="success",
        message=f"message ID '{message_id}' successfully deleted",
        data=None,
    )


async def clear_conversation(
    agent,
    store_id,
    ticket_id,
    db,
    payload,
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Unauthorized access attempt at the clear_conversation")
        raise HTTPException(status_code=401, detail="not a valid user")
    if agent not in ["customer", "support"]:
        raise HTTPException(
            status_code=409, detail="agent must be either 'customer' or 'support'"
        )
    ticket_filter = (
        and_(
            Ticket.user_id == user_id,
        )
        if agent == "customer"
        else and_(Ticket.assigned_to == user_id, Ticket.status == TicketStatus.closed)
    )
    role_filter = (
        Messaging.customer_id == user_id
        if agent == "customer"
        else Messaging.support_id == user_id
    )
    try:
        ticket_check = (
            await db.execute(
                select(Ticket)
                .where(
                    Ticket.store_id == store_id, Ticket.id == ticket_id, ticket_filter
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if not ticket_check:
            logger.warning(
                "user: %s, tried clearing the messages of a ticket not validated with ticket_id: %s",
                user_id,
                ticket_id,
            )
            raise HTTPException(status_code=409, detail="invalid request")
        clear = await db.execute(
            update(Messaging)
            .where(
                Messaging.ticket_id == ticket_id,
                or_(Messaging.user_id == user_id, role_filter),
            )
            .values(
                sender_deleted=case(
                    (Messaging.user_id == user_id, True), else_=Messaging.sender_deleted
                ),
                receiver_deleted=case(
                    (
                        and_(role_filter, Messaging.user_id != user_id),
                        True,
                    ),
                    else_=Messaging.receiver_deleted,
                ),
            )
            .returning(Messaging.id)
        )
        if not clear.scalar():
            logger.info(f"No messages found with ticket '{ticket_id}'")
            raise HTTPException(status_code=404, detail="no messages found to delete")
        if agent == "customer" and ticket_check.status != TicketStatus.closed:
            ticket_check.status = TicketStatus.closed
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database error at clear_conversation endpoint")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(f"Failed to clear conversation with ticket '{ticket_id}'")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"All messages with ticket '{ticket_id}' deleted by user '{user_id}'.")
    return StandardResponse(
        status="success", message="conversation successfully cleared", data=None
    )
