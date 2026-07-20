from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, BackgroundTasks, Query
from app.database.get import get_db
from app.api.v1.schemas import (
    ReactionType,
    ReactResponse,
    StandardResponse,
    PaginatedMetadata,
)
from app.auth.verify_jwt import verify_token
from app.services import reactions_service

router = APIRouter(prefix="/reactions", tags=["Reactions"])


@router.post("/react")
async def react_type(
    reaction_type: ReactionType,
    background_task: BackgroundTasks,
    reply_id: int | None = None,
    review_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await reactions_service.react_type(
        reaction_type=reaction_type,
        background_task=background_task,
        reply_id=reply_id,
        review_id=review_id,
        db=db,
        payload=payload,
    )


@router.get(
    "reactions_list",
    response_model=StandardResponse[PaginatedMetadata[ReactResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def get_reactions(
    review_id: int | None = None,
    reply_id: int | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await reactions_service.view_reactions(
        review_id=review_id,
        reply_id=reply_id,
        page=page,
        limit=limit,
        db=db,
        payload=payload,
    )
