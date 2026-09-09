from fastapi import APIRouter, Request, Query, BackgroundTasks, Depends
from app.services import product_reply_service
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.schemas import (
    Reply,
    StandardResponse,
    PaginatedMetadata,
    ReplyResponse,
)
from app.database.get import get_db
from typing import Annotated

router = APIRouter(prefix="/product_replies", tags=["Product Reply"])

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/create_product_reply",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def post_product_reply(
    request: Request, reply: Reply, background_task: BackgroundTasks, db: DatabaseDep
):
    return await product_reply_service.reply(
        reply=reply, background_task=background_task, db=db, request=request
    )


@router.get(
    "/view_product_replies/{product_id}/{review_id}",
    response_model=StandardResponse[PaginatedMetadata[ReplyResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def product_reply_list(
    product_id: int,
    review_id: int,
    db: DatabaseDep,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await product_reply_service.view_replies(
        product_id=product_id,
        review_id=review_id,
        db=db,
        page=page,
        limit=limit,
    )


@router.put(
    "/edit_product_reply",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def update_product_reply(
    request: Request, reply: Reply, background_task: BackgroundTasks, db: DatabaseDep
):
    return await product_reply_service.update(
        reply=reply, background_task=background_task, db=db, request=request
    )


@router.delete(
    "/product_reply_delete/{reply_id}/{review_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_product_reply(
    request: Request,
    reply_id: int,
    review_id: int,
    background_task: BackgroundTasks,
    db: DatabaseDep,
):
    return await product_reply_service.delete_reply(
        reply_id=reply_id,
        review_id=review_id,
        background_task=background_task,
        db=db,
        request=request,
    )
