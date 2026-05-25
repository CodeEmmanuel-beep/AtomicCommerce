from sse_starlette.sse import EventSourceResponse
from fastapi import APIRouter, Depends, HTTPException, Query
from app.auth.verify_jwt import verify_token
from app.utils.redis import notifications_stream
from app.models import Notification, User
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db
from app.logs.logger import get_logger
from app.api.v1.schemas import (
    NotificationResponse,
    PaginatedMetadata,
    StandardResponse,
    PaginatedResponse,
)
from typing import List
from app.utils.redis import cache, cached, notification_invalidation
from sqlalchemy import select, func, update

router = APIRouter(prefix="/notifications", tags=["Notifications"])

logger = get_logger("notifications")


@router.get("/notice")
async def notification_message(payload: dict = Depends(verify_token)):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at notice endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    await notification_invalidation(user_id)
    try:
        return EventSourceResponse(notifications_stream(user_id))
    except Exception:
        logger.exception("SSE stream failed for user %s", user_id)
        raise HTTPException(status_code=500, detail="stream error")


@router.get(
    "/notifications_list",
    response_model=StandardResponse[List[NotificationResponse]],
    response_model_exclude_defaults=True,
    response_model_exclude_none=True,
)
async def get_notifications(
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at get_notifications endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    notification_key = f"notification:{user_id}"
    cached_data = await cache(notification_key)
    if cached_data:
        logger.info(f"Cache hit at the get_notification endpoint for user {user_id}")
        return StandardResponse(**cached_data)
    notifier = (
        await db.execute(
            select(Notification, User)
            .join(User, Notification.from_user == User.id)
            .where(Notification.notified_user == user_id)
            .order_by(Notification.created_at.desc())
            .limit(30)
        )
    ).all()
    if not notifier:
        logger.error("user %s, attempt to fetch notifications returned null", user_id)
        return StandardResponse(
            status="success", message="no notification found", data=None
        )
    items = []
    for notify, sender in notifier:
        data = NotificationResponse.model_validate(notify)
        data.notification = (
            f"{notify.notification} {sender.first_name} {sender.surname}"
            if sender.is_active
            else f"{notify.notification}" "deleted user"
        )
        items.append(data)
    await db.execute(
        update(Notification)
        .where(Notification.notified_user == user_id)
        .values(is_read=True)
    )
    await db.commit()
    full_data = StandardResponse(status="success", message="notifications", data=items)
    await cached(notification_key, full_data, ttl=60)
    logger.info(f"notification data cached for user {user_id}")
    return full_data


@router.get(
    "/notifications_data",
    response_model=StandardResponse[PaginatedMetadata[NotificationResponse]],
    response_model_exclude_defaults=True,
    response_model_exclude_none=True,
)
async def notifications_history(
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at get_notifications endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    offset = (page - 1) * limit
    notification_key = f"notification:{user_id}:{page}:{limit}"
    cached_data = await cache(notification_key)
    if cached_data:
        logger.info(f"Cache hit at the get_notification endpoint for user {user_id}")
        return StandardResponse(**cached_data)
    notifier = (
        await db.execute(
            select(Notification, User)
            .join(User, Notification.from_user == User.id)
            .where(Notification.notified_user == user_id)
            .order_by(Notification.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    if not notifier:
        logger.error("user %s, attempt to fetch notifications returned null", user_id)
        return StandardResponse(
            status="success", message="no notification found", data=None
        )
    total = (
        await db.execute(
            select(func.count(Notification.id)).where(
                Notification.notified_user == user_id, User.is_active
            )
        )
    ).scalar() or 0
    logger.info("total number of notifications for user %s is %s", user_id, total)
    items = []
    for notify, sender in notifier:
        data = NotificationResponse.model_validate(notify)
        data.notification = (
            f"{notify.notification} {sender.first_name} {sender.surname}"
            if sender.is_active
            else f"{notify.notification}" "deleted user"
        )
        items.append(data)
    await db.execute(
        update(Notification)
        .where(Notification.notified_user == user_id)
        .values(is_read=True)
    )
    await db.commit()
    data = PaginatedMetadata[NotificationResponse](
        items=items,
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    full_data = StandardResponse(status="success", message="notifications", data=data)
    await cached(notification_key, full_data, ttl=60)
    logger.info(f"notification data cached for user {user_id}")
    return full_data
