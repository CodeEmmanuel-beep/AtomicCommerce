from app.logs.logger import get_logger
from app.api.v1.models import (
    ReplyResponse,
    PaginatedMetadata,
    PaginatedResponse,
    StandardResponse,
)
from fastapi import HTTPException
from app.models_sql import Review, Reply, User
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError

logger = get_logger("product_reply")


async def reply(reply, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Review).where(
        Review.product_id == reply.product_id, Review.id == reply.review_id
    )
    rep = (await db.execute(stmt)).scalar_one_or_none()
    if not rep:
        raise HTTPException(status_code=494, detail="review not found")
    new_reply = Reply(
        user_id=user_id,
        product_id=reply.product_id,
        review_id=reply.review_id,
        reply_text=reply.reply_text,
    )
    try:
        db.add(new_reply)
        await db.commit()
        await db.refresh(new_reply)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=500, detail="internal server error")
    return {"messsage": "reply successfully posted"}


async def view_replies(product_id, review_id, page, limit, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="not a registered user")
    offset = (page - 1) * limit
    stmt = (
        select(Reply)
        .where(Reply.product_id == product_id, Reply.review_id == review_id)
        .order_by(
            or_(User.role == "Admin", User.role == "Owner").desc(), Reply.time_of_post
        )
    )
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery))
    ).scalar() or 0
    reply = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    if not reply:
        raise HTTPException(status_code=404, detail="no replies available")
    data = PaginatedMetadata[ReplyResponse](
        items=[ReplyResponse.model_validate(rep) for rep in reply],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    return StandardResponse(status="success", message="replies", data=data)


async def update(reply, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Reply).where(
        Reply.user_id == user_id,
        Reply.product_id == reply.product_id,
        Reply.id == reply.id,
    )
    replies = (await db.execute(stmt)).scalars().all()
    if not replies:
        raise HTTPException(status_code=404, detail="review not found")
    replies.reply_text = reply.reply_text
    try:
        replies.edited = True
        await db.commit()
        await db.refresh(replies)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=500, detail="internal server error")
    return {"message": "review edited successfully"}


async def delete_reply(reply, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Reply).where(
        Reply.user_id == user_id,
        Reply.product_id == reply.product_id,
        Reply.id == reply.id,
    )
    replies = (await db.execute(stmt)).scalar_one_or_none()
    if not replies:
        raise HTTPException(status_code=404, detail="revie not found")
    try:
        await db.delete(replies)
        await db.commit()
        await db.refresh(replies)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=500, detail="internal server error")
    return {"message": "deleted review"}
