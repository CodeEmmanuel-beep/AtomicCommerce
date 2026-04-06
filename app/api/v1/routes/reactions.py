from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends
from app.database.get import get_db
from app.api.v1.schemas import ReactionType
from app.auth.verify_jwt import verify_token
from app.services import reactions_service

router = APIRouter(prefix="/react", tags=["Reactions"])


@router.post("/react")
async def react_type(
    reaction_type: ReactionType,
    reply_id: int | None = None,
    review_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await reactions_service.react_type(
        reaction_type=reaction_type,
        reply_id=reply_id,
        review_id=review_id,
        db=db,
        payload=payload,
    )
