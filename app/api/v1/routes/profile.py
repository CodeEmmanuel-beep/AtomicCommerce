from fastapi import APIRouter, Depends
from app.services import profile_service
from app.database.get import get_db
from app.auth.verify_jwt import verify_token
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/profile", tags=["Profile"])


@router.get("/personal_profile")
async def get_personal_profile(
    db: AsyncSession = Depends(get_db), payload: dict = Depends(verify_token)
):
    return await profile_service.view_profile(db, payload)
