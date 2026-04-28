from fastapi import HTTPException
from app.logs.logger import get_logger
from sqlalchemy import select
from app.models import User, Membership
from sqlalchemy.orm import selectinload

logger = get_logger("profiles")


async def view_profile(db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at the view_profile endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    profile = (
        await db.execute(
            select(User)
            .options(selectinload(User.membership))
            .where(User.id == user_id)
        )
    ).scalar_one_or_none()
    if not profile:
        logger.warning("user: %s, has no user profile in the database", user_id)
        raise HTTPException(status_code=404, detail="profile not found")
