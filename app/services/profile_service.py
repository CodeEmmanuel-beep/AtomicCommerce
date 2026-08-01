from fastapi import HTTPException
from app.logs.logger import get_logger
from sqlalchemy import select, exists
from app.models import User
from app.utils.supabase_url import get_public_url
from app.api.v1.schemas import StandardResponse, UserResponse
from email_validator import validate_email, EmailNotValidError
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone
from app.utils.helper import unique_id, user_role
from app.utils.redis import redis_client

logger = get_logger("profiles")


async def view_profile(request, db):
    user_id = unique_id(request)
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


async def edit_profile(request, profile, db):
    user_id = unique_id(request)
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
            if (new_value or field in nullable) and current_value != new_value:
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


async def deactivate_profile(request, response, db):
    user_id = unique_id(request)
    if not user_id:
        delete_profile_log.warning(
            "unauthorized attempt at the deactivate_profile endpoint"
        )
        raise HTTPException(status_code=403, detail="Unauthorized access.")
    try:
        stmt = select(User).where(User.id == user_id).with_for_update()
        data = (await db.execute(stmt)).scalar_one_or_none()
        if not data:
            delete_profile_log.warning(
                f"{user_id}, tried self-deactivating a nonexistent profile, profile id"
            )
            raise HTTPException(status_code=404, detail="profile not found")
        if not data.is_active:
            raise HTTPException(status_code=400, detail="user already deactivated")
        now = datetime.now(timezone.utc)
        data.is_active = False
        data.deactivation_time = now
        response.delete_cookie("refresh")
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        delete_profile_log.error(
            "database error occured while deactivating profile: %s", user_id
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        delete_profile_log.exception(
            "error occured while deactivating profile: %s", user_id
        )
        raise HTTPException(status_code=500, detail="internal server error")
    delete_profile_log.info("profile '%s' deactivated", user_id)
    return StandardResponse(
        status="success",
        message="profile deactivated",
        data={
            "user_id": user_id,
            "deleted": True,
        },
    )


async def ban_profile(
    userId, request, indefinite, ban_period, ban_unit, ban_reason, db
):
    user_id = unique_id(request)
    role = user_role(request)
    if not user_id:
        delete_profile_log.warning("unauthorized attempt at the ban_profile endpoint")
        raise HTTPException(status_code=403, detail="Unauthorized access.")
    if role not in ("Admin", "Owner"):
        delete_profile_log.warning(
            f"{user_id}, tried banning a profile without admin powers, profile id: {userId}"
        )
        raise HTTPException(status_code=403, detail="not authorized")
    if not ban_reason:
        raise HTTPException(status_code=400, detail="ban_reason is required")
    if ban_period:
        if ban_unit not in ("months", "days"):
            raise HTTPException(
                status_code=400, detail="ban unit is either months or days"
            )
        if ban_unit == "months" and not (1 <= ban_period <= 12):
            raise HTTPException(
                status_code=400, detail="months range should be between 1-12"
            )
        elif ban_unit == "days" and not (1 <= ban_period <= 31):
            raise HTTPException(
                status_code=400, detail="days range should be between 1-31"
            )
    elif indefinite != "Yes":
        raise HTTPException(
            status_code=400, detail="must provide ban_period or set indefinite ban"
        )
    profile_id = None
    try:
        stmt = select(User).where(User.id == userId).with_for_update()
        data = (await db.execute(stmt)).scalar_one_or_none()
        if not data:
            delete_profile_log.warning(
                f"{user_id}, tried banning a nonexistent profile, profile id: {userId}"
            )
            raise HTTPException(status_code=404, detail="profile not found")
        if data.role == "Owner":
            delete_profile_log.warning(
                "admin: %s, tried banning Owner's profile", user_id
            )
            raise HTTPException(status_code=403, detail="FORBIDDEN")
        if data.role == "Admin" and role != "Owner":
            delete_profile_log.warning(
                f"Admin {user_id} tried banning another Admin {data.id}"
            )
            raise HTTPException(
                status_code=403, detail="Admins cannot ban other Admins."
            )
        now = datetime.now(timezone.utc)
        if data.ban_count >= 5 or indefinite == "Yes":
            data.indefinite_ban = True
            data.is_banned = True
            data.ban_date = now
            data.ban_unit = None
            data.ban_period = 0
            data.is_active = False
            data.ban_reason = ban_reason
            data.ban_count += 1
        else:
            data.is_banned = True
            data.ban_date = now
            data.ban_unit = ban_unit
            data.ban_period = ban_period
            data.ban_reason = ban_reason
            data.is_active = False
            data.ban_count += 1
        profile_id = data.id
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        delete_profile_log.error(
            "database error occured while banning profile: %s, %s", profile_id, str(e)
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        delete_profile_log.exception(
            "error occured while banning profile: %s", profile_id
        )
        raise HTTPException(status_code=500, detail="internal server error")
    try:
        await redis_client.set(f"banned_client:{userId}", "true")
    except Exception:
        delete_profile_log.exception(
            "failed to cache ban in redis for user %s", profile_id
        )
    delete_profile_log.info("profile '%s' banned", profile_id)
    return StandardResponse(
        status="success",
        message="profile is banned",
        data={
            k: v
            for k, v in (
                {
                    "id": profile_id,
                    "user_id": user_id,
                    "indefinite": indefinite,
                    "ban_period": ban_period,
                    "ban_unit": ban_unit,
                    "ban_reason": ban_reason,
                    "deleted": True,
                }
            ).items()
            if v is not None
        },
    )
