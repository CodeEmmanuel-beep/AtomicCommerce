from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.models import (
    Reply,
    StandardResponse,
    PaginatedMetadata,
    ReplyResponse,
)
from app.auth.verify_jwt import verify_token
from app.database.get import get_db
from app.services import store_reply_service

router = APIRouter(prefix="/store_replies", tags=["Store_Reply"])


@router.post("/create_store_reply")
async def post_store_reply(
    reply: Reply,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_reply_service.reply(reply=reply, db=db, payload=payload)


@router.get(
    "/view_store_replies/{store_id}/{review_id}",
    response_model=StandardResponse[PaginatedMetadata[ReplyResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def store_reply_list(
    store_id: int,
    review_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await store_reply_service.view_replies(
        store_id=store_id,
        review_id=review_id,
        db=db,
        page=page,
        limit=limit,
    )


@router.put("/edit_store_reply")
async def update_store_reply(
    reply: Reply,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_reply_service.update(reply=reply, db=db, payload=payload)


@router.delete("/store_reply_delete")
async def delete_store_reply(
    reply: Reply,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_reply_service.delete_reply(reply=reply, db=db, payload=payload)
