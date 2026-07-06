from fastapi import APIRouter, Depends, Query
from app.auth.verify_jwt import verify_token
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db
from app.api.v1.schemas import NotificationResponse, PaginatedMetadata, StandardResponse
from typing import List
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/notice")
async def notification_message(payload: dict = Depends(verify_token)):
    return await notification_service.notification_stream(payload=payload)


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
    return await notification_service.retrieve_notifications(db=db, payload=payload)


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
    return await notification_service.notifications_list(
        page=page, limit=limit, db=db, payload=payload
    )
