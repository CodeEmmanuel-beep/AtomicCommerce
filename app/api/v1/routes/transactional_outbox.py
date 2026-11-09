from app.api.v1.schemas import OutboxResponse, PaginatedMetadata, StandardResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db
from fastapi import Request, APIRouter, Query, Depends
import uuid
from app.services.transactional_outbox_service import (
    retrieve_outbox_event,
    retrieve_outbox_events,
)

router = APIRouter(prefix="/Outbox", tags=["Outbox Events"])


@router.get(
    "/outbox_events",
    response_model=StandardResponse[PaginatedMetadata[OutboxResponse]],
    response_model_exclude_defaults=True,
    response_model_exclude_none=True,
)
async def get_outbox_events(
    request: Request,
    event_type: str | None = None,
    limit: int = Query(10, ge=1, le=100),
    cursor_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await retrieve_outbox_events(
        cursor_id=cursor_id, limit=limit, event_type=event_type, db=db, request=request
    )


@router.get(
    "/single_outbox_event",
    response_model=StandardResponse[OutboxResponse],
    response_model_exclude_defaults=True,
    response_model_exclude_none=True,
)
async def get_outbox_events(
    event_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    return await retrieve_outbox_event(event_id=event_id, db=db, request=request)
