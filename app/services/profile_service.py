from fastapi import HTTPException
from app.logs.logger import get_logger
from sqlalchemy import select, exists
from app.models import User
from app.utils.supabase_url import get_public_url
from app.api.v1.schemas import StandardResponse, UserResponse
from email_validator import validate_email, EmailNotValidError
from sqlalchemy.exc import IntegrityError

logger = get_logger("profiles")


async def view_profile(db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at the view_profile endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    profile = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if not profile:
        logger.warning("user: %s, has no user profile in the database", user_id)
        raise HTTPException(status_code=404, detail="profile not found")
    user_res = UserResponse.model_validate(profile)
    user_res.profile_picture = (
        get_public_url(profile.profile_picture) if profile.profile_picture else None
    )
    return StandardResponse(status="success", message="profile", data=user_res)


async def edit_profile(
    profile,
    db,
    payload,
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at the edit_profile endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    if profile.email:
        try:
            validate_email(profile.email)
        except EmailNotValidError as e:
            raise HTTPException(status_code=400, detail=str(e))
    user_exists = (
        await db.execute(select(User).where(User.id == user_id).with_for_update())
    ).scalar_one_or_none()
    if not user_exists:
        logger.warning("user: %s, do not have a profile in database", user_id)
        raise HTTPException(status_code=404, detail="profile not found")
    if profile.email and profile.email != user_exists.email:
        email_exists = (
            await db.execute(
                select(exists().where(User.email == profile.email, User.id != user_id))
            )
        ).scalar()
        if email_exists:
            raise HTTPException(
                status_code=400, detail="email is already in use by another user"
            )
    logger.info("Starting update for user: %s", user_id)
    has_changed = False
    update_data = profile.model_dump(exclude_unset=True)
    fields = [
        "first_name",
        "middle_name",
        "surname",
        "email",
        "phone_number",
        "nationality",
        "address",
    ]
    nullable = ["middle_name", "address"]
    for field, new_value in update_data.items():
        if field in fields:
            current_value = getattr(user_exists, field, None)
            if new_value or field in nullable:
                if current_value != new_value:
                    setattr(user_exists, field, new_value)
                    has_changed = True
    if not has_changed:
        await db.rollback()
        return StandardResponse(
            status="success", message="no new changes detected", data=None
        )
    try:
        await db.commit()
    except IntegrityError:
        logger.error("could not edit profile for user, '%s'", user_id)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        logger.exception("could not edit profile for user %s", user_id)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("user: %s, successfully edited his profile", user_id)
    return StandardResponse(
        status="success", message="profile successfully edited", data=None
    )


delete_profile_log = get_logger("delete_profile")


async def delete_profile(userId, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        delete_profile_log.warning(
            "unauthorized attempt at the delete_profile endpoint"
        )
        raise HTTPException(status_code=403, detail="Unauthorized access.")
    access = userId if userId else user_id
    stmt = select(User).where(User.id == access).with_for_update()
    data = (await db.execute(stmt)).scalar_one_or_none()
    if not data:
        delete_profile_log.warning(
            f"{user_id}, tried deleting a nonexistent profile, profile id: {userId}"
        )
        raise HTTPException(status_code=404, detail="profile not found")
    if data.id != user_id:
        stmt = select(User).where(User.id == user_id, User.role.in_(["Admin", "Owner"]))
        admin = (await db.execute(stmt)).scalar_one_or_none()
        if not admin:
            delete_profile_log.warning(
                f"{user_id}, tried deleting a profile without admin powers, profile id: {userId}"
            )
            raise HTTPException(status_code=403, detail="not authorized")
        if data.role == "Owner":
            delete_profile_log.warning(
                "admin: %s, tried deleting Owner's profile", user_id
            )
            raise HTTPException(status_code=403, detail="FORBIDDEN")
        if data.role == "Admin" and admin.role != "Owner":
            delete_profile_log.warning(
                f"Admin {user_id} tried deleting another Admin {data.id}"
            )
            raise HTTPException(
                status_code=403, detail="Admins cannot delete other Admins."
            )
    if not data.is_active:
        return StandardResponse(
            status="success", message="user already deactivated", data=None
        )
    data.is_active = False
    profile_id = data.id
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        delete_profile_log.error(
            "database error occured while deleting profile: %s", profile_id
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        delete_profile_log.exception(
            "error occured while deleting profile: %s", profile_id
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("deleted profile %s", profile_id)
    return StandardResponse(
        status="success",
        message="deleted profile",
        data={
            "id": profile_id,
            "user_id": user_id,
            "deleted": "Yes",
        },
    )
