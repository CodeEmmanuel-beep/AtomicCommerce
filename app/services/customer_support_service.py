from app.api.v1.models import (
    Chat,
    StandardResponse,
    PaginatedResponse,
)
from app.models_sql import Messaging, User
from fastapi import HTTPException
from datetime import timezone, datetime
from app.logs.logger import get_logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, or_, func, and_, update
import os, shutil, uuid
from werkzeug.utils import secure_filename

logger = get_logger("chat_support")


async def text_support(
    message,
    pics,
    db,
    payload,
):
    user_id = payload.get("user_id")
    username = payload.get("sub")
    if not user_id:
        logger.warning(f"Unauthorized access attempt by user: {username}")
        raise HTTPException(status_code=403, detail="not a valid user")
    try:
        stmt = select(User).where(User.role == "c_c", User.is_active == True)
        receive = (await db.execute(stmt)).scalars().all()
    except Exception as e:
        logger.error(f"Database error while fetching customer support: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    if not receive:
        logger.info(f"Message send failed: support support not found.")
        raise HTTPException(status_code=404, detail="no active support found")
    name = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    file_path = None
    file_url = None
    if pics is not None:
        try:
            filename = f"{uuid.uuid4()}_{secure_filename(pics.filename)}"
            file_path = os.path.join("images", filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(pics.file, buffer)
            file_url = f"/images/{filename}"
            pics = file_url
        except Exception as e:
            logger.exception("Image upload failed")
            raise HTTPException(status_code=500, detail="error uploading file")
    else:
        pics = None
    if not message and not pics:
        logger.info(f"Message send failed: empty message from user '{username}'.")
        raise HTTPException(status_code=400, detail="can not send empty messages")
    logger.info(f"User '{username}' is sending a message to 'customer support'.")
    support = receive[user_id % len(receive)]
    new_message = Messaging(
        user_id=user_id,
        customer_support=support.name,
        identifier=support.id,
        pics=pics,
        customer=name.name,
        message=message,
        time_of_chat=datetime.now(timezone.utc),
    )
    try:
        db.add(new_message)
        await db.commit()
        await db.refresh(new_message)
    except IntegrityError:
        await db.rollback()
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.error("Removed orphaned file from database:%s", file_path)
        logger.error(
            f"Message send failed due to database error for user '{username}'."
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"Message successfully sent from '{username}' to customer.")
    return {"success": f"message successfully sent to customer support"}


async def text_customer(
    message,
    customer_id,
    pics,
    db,
    payload,
):
    user_id = payload.get("user_id")
    username = payload.get("sub")
    if not user_id:
        logger.warning(f"Unauthorized access attempt by user: {username}")
        raise HTTPException(status_code=403, detail="not a valid user")
    restricted = (
        (await db.execute(select(User).where(User.id == user_id, User.role == "c_c")))
        .scalars()
        .all()
    )
    if not restricted:
        raise HTTPException(status_code=403, detail="restricted service")
    try:
        stmt = select(User).where(User.id == customer_id, User.is_active == True)
        receive = (await db.execute(stmt)).scalar_one_or_none()
    except Exception as e:
        logger.error(f"Database error while fetching customer '{customer_id}': {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    if not receive:
        logger.info(f"Message send failed: customer '{customer_id}' not found.")
        raise HTTPException(status_code=404, detail="user not found")
    name = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    file_path = None
    file_url = None
    if pics is not None:
        try:
            filename = f"{uuid.uuid4()}_{secure_filename(pics.filename)}"
            file_path = os.path.join("images", filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(pics.file, buffer)
            file_url = f"/images/{filename}"
            pics = file_url
        except Exception as e:
            logger.exception("File upload failed")
            raise HTTPException(status_code=500, detail="Error uploading image")
    else:
        pics = None
    if not message and not pics:
        logger.info(f"Message send failed: empty message from user '{username}'.")
        raise HTTPException(status_code=400, detail="can not send empty messages")
    logger.info(f"User '{username}' is sending a message to '{customer_id}'.")
    new_message = Messaging(
        user_id=user_id,
        customer=receive.name,
        customer_id=receive.id,
        customer_support=name.name,
        pics=pics,
        message=message,
        time_of_chat=datetime.now(timezone.utc),
    )
    try:
        db.add(new_message)
        await db.commit()
        await db.refresh(new_message)
    except IntegrityError:
        await db.rollback()
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.error("Removed orphaned file from database:%s", file_path)
        logger.error(
            f"Message send failed due to database error for user '{username}'."
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"Message successfully sent from '{username}' to '{customer_id}'.")
    return {"success": f"message successfully sent to {customer_id}"}


async def customer_view(
    page,
    limit,
    db,
    payload,
):
    user_id = payload.get("user_id")
    username = payload.get("sub")
    if not username:
        logger.warning(f"Unauthorized access attempt by user: {username}")
        raise HTTPException(status_code=403, detail="not a valid user")
    offset = (page - 1) * limit
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
                    Messaging.sender_deleted == False,
                ),
                and_(
                    Messaging.customer_id == user_id,
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
        f"Total messages found between '{username}' and customer support: {total}"
    )
    view = (await db.execute(stmt.offset(offset).limit(limit))).all()
    for msg, _ in view:
        if msg.receiver == username:
            msg.seen = True
    await db.commit()
    support_id = [msg.id for msg in view]
    support = (
        (await db.execute(select(User).where(User.id.in_(support_id)))).scalars().all()
    )
    support_map = {s.id: s for s in support}
    conversations = {}
    for msg, conv_id in view:
        chat_data = Chat.model_validate(msg)
        customer_support = support_map.get(msg.user_id)
        chat_data.customer_support = customer_support.name
        conversations.setdefault(conv_id, []).append(chat_data)
    data = {
        "conversations": conversations,
        "pagination": PaginatedResponse(page=page, limit=limit, total=total),
    }
    logger.info(
        f"Fetched messages between '{username}' and customer support (page={page})."
    )
    return StandardResponse(status="success", message="your messages", data=data)


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


async def clear_conversation(
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
