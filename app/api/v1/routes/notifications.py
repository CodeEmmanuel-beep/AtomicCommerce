from fastapi import APIRouter, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import async_db
from app.api.v1.schemas import NotificationResponse, PaginatedMetadata, StandardResponse
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/notice")
async def notification_message(request: Request):
    return await notification_service.notification_stream(request=request)


@router.get(
    "/notifications_list",
    response_model=StandardResponse[list[NotificationResponse]],
    response_model_exclude_defaults=True,
    response_model_exclude_none=True,
)
async def get_notifications(request: Request, db: AsyncSession = async_db):
    return await notification_service.retrieve_notifications(request=request, db=db)


@router.get(
    "/notifications_data",
    response_model=StandardResponse[PaginatedMetadata[NotificationResponse]],
    response_model_exclude_defaults=True,
    response_model_exclude_none=True,
)
async def notifications_history(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = async_db,
):
    return await notification_service.notifications_list(
        page=page, limit=limit, db=db, request=request
    )
