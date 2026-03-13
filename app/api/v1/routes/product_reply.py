from fastapi import APIRouter, Depends, Query
from app.services import product_reply_service
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.models import (
    ReplyRes,
    StandardResponse,
    PaginatedMetadata,
    ReplyResponse,
)
from app.auth.verify_jwt import verify_token
from app.database.get import get_db

router = APIRouter(prefix="/replies", tags=["Product_Reply"])


@router.post("/create_reply")
async def post_reply(
    reply: ReplyRes,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await product_reply_service.reply(reply=reply, db=db, payload=payload)


@router.get(
    "/view_replies/{product_id}/{review_id}",
    response_model=StandardResponse[PaginatedMetadata[ReplyResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def reply_list(
    product_id: int,
    review_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await product_reply_service.view_replies(
        product_id=product_id,
        review_id=review_id,
        db=db,
        payload=payload,
        page=page,
        limit=limit,
    )


@router.put("/edit_reply")
async def update_reply(
    reply: ReplyRes,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await product_reply_service.update(reply=reply, db=db, payload=payload)


@router.delete("/delete_reply")
async def delete_one(
    reply: ReplyRes,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await product_reply_service.delete_reply(reply=reply, db=db, payload=payload)
