from fastapi import HTTPException
from app.logs.logger import get_logger
from sqlalchemy import select
from app.models import User, Membership
from sqlalchemy.orm import selectinload
from app.api.v1.schemas import StandardResponse, PaginatedMetadata, UserResponse

logger = get_logger("profiles")


async def view_profile(db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at the view_profile endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    profile = (
        await db.execute(
            select(User, Membership)
            .join(Membership, User.id == Membership.user_id)
            .options(selectinload(Membership.store))
            .where(User.id == user_id)
        )
    ).first()
    if not profile:
        logger.warning("user: %s, has no user profile in the database", user_id)
        raise HTTPException(status_code=404, detail="profile not found")
    user, members = profile
    membership = {mem.store.store_name: mem.membership_type for mem in members}
    userres = UserResponse.model_validate(user)
    userres.membership = membership
    return StandardResponse(status="success", message="profile", data=userres)
