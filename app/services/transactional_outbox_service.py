from app.models import (
    OutboxEvent,
    OutboxStatus,
    RoleEnum,
)
from app.api.v1.schemas import (
    OutboxResponse,
    PaginatedMetadata,
    StandardResponse,
    CursorPaginatedResponse,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select, or_, update, and_
from app.database.get import AsyncSessionLocal
from fastapi import HTTPException
import uuid
from datetime import datetime, timedelta, timezone
from app.utils.helper import unique_id, user_role
from app.logs.logger import get_logger

logger = get_logger("outbox")


async def retrieve_outbox_events(cursor_id, limit, event_type, db, request):
    user_id = unique_id(request)
    role = user_role(request)
    if not user_id:
        logger.warning(
            "user tried accessing retrieve_outbox_events endpoint without authentication"
        )
        raise HTTPException(status_code=401, detail="not authenticated")
    if role not in (RoleEnum.Owner, RoleEnum.Admin):
        logger.warning(
            "user %s tried accessing retrieve_outbox_events endpoint without proper authorization",
            user_id,
        )
        raise HTTPException(status_code=403, detail="not authorized")
    stmt = select(OutboxEvent).order_by(OutboxEvent.id.asc()).limit(limit + 1)
    if cursor_id is not None:
        stmt = stmt.where(OutboxEvent.id > cursor_id)
    if event_type is not None:
        stmt = stmt.where(OutboxEvent.event_type == event_type)
    outbox = (await db.execute(stmt)).scalars().all()
    if not outbox:
        logger.info("search for outbox events returned null")
    has_more = False
    if len(outbox) > limit:
        has_more = True
    outbox = outbox[:limit]
    next_cursor_id = outbox[-1].id if outbox else None
    data = PaginatedMetadata[OutboxResponse](
        items=[OutboxResponse.model_validate(out) for out in outbox],
        cursor_pagination=CursorPaginatedResponse(
            next_cursor=next_cursor_id, has_more=has_more, limit=limit
        ),
    )
    logger.info("search for outbox events returned results")
    message = f"outbox events for {event_type}" if event_type else "outbox events"
    return StandardResponse(status="success", message=message, data=data)


async def retrieve_outbox_event(event_id, db, request):
    user_id = unique_id(request)
    role = user_role(request)
    if not user_id:
        logger.warning(
            "user tried accessing retrieve_outbox_events endpoint without authentication"
        )
        raise HTTPException(status_code=401, detail="not authenticated")
    if role not in (RoleEnum.Owner, RoleEnum.Admin):
        logger.warning(
            "user %s tried accessing retrieve_outbox_events endpoint without proper authorization",
            user_id,
        )
        raise HTTPException(status_code=403, detail="not authorized")
    stmt = select(OutboxEvent).where(OutboxEvent.id == event_id)
    outbox = (await db.execute(stmt)).scalar_one_or_none()
    if not outbox:
        logger.info("search for outbox event with id %s returned zero result", event_id)
        raise HTTPException(status_code=404, detail="outbox event not found")
    data = OutboxResponse.model_validate(outbox)
    logger.info("search for outbox event with id %s returned result", event_id)
    return StandardResponse(status="success", message="outbox event", data=data)


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
                        OutboxEvent.status == OutboxStatus.processing,
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
