from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Request, BackgroundTasks, Query, Depends
from app.database.get import get_db
from app.api.v1.schemas import (
    ReactionType,
    ReactResponse,
    StandardResponse,
    PaginatedMetadata,
)
from typing import Annotated
from app.services import reactions_service

router = APIRouter(prefix="/reactions", tags=["Reactions"])

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]


@router.post("/react")
async def react_type(
    request: Request,
    reaction_type: ReactionType,
    background_task: BackgroundTasks,
    db: DatabaseDep,
    reply_id: int | None = None,
    review_id: int | None = None,
):
    return await reactions_service.react_type(
        reaction_type=reaction_type,
        background_task=background_task,
        reply_id=reply_id,
        review_id=review_id,
        db=db,
        request=request,
    )


@router.get(
    "/reactions_list",
    response_model=StandardResponse[PaginatedMetadata[ReactResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def get_reactions(
    request: Request,
    db: DatabaseDep,
    review_id: int | None = None,
    reply_id: int | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await reactions_service.view_reactions(
        review_id=review_id,
        reply_id=reply_id,
        page=page,
        limit=limit,
        db=db,
        request=request,
    )
