from fastapi import HTTPException
from app.logs.logger import get_logger
from sqlalchemy import select, exists
from app.models import User
from app.utils.supabase_url import get_public_url
from app.api.v1.schemas import (
    StandardResponse,
    UserResponse,
    PaginatedMetadata,
    CursorPaginatedResponse,
    SuperUserResponse,
)
from dateutil.relativedelta import relativedelta
from email_validator import validate_email, EmailNotValidError
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone, date
import time
from app.utils.helper import unique_id, user_role, user_jti, jwt_exp
from app.utils.redis import (
    redis_client,
    cache,
    cached,
    cache_version,
    profile_invalidation,
    profile_global_invalidation,
)

logger = get_logger("profiles")

now = datetime.now(timezone.utc)
today = date.today()


async def view_profile(request, db):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized attempt at the view_profile endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    cache_key = f"profile:{user_id}"
    profile_cache = await cache(cache_key)
    if profile_cache:
        logger.info("cache hit at view_profile function for user: %s", user_id)
        return StandardResponse(**profile_cache)
    profile = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if not profile:
        logger.warning("user: %s, has no user profile in the database", user_id)
        raise HTTPException(status_code=404, detail="profile not found")
    age = today.year - profile.date_of_birth.year
    if (today.month, today.day) < (
        profile.date_of_birth.month,
        profile.date_of_birth.day,
    ):
        age -= 1
    user_res = UserResponse.model_validate(profile)
    user_res.profile_picture = (
        get_public_url(profile.profile_picture) if profile.profile_picture else None
    )
    user_res.age = int(age)
    response = StandardResponse(status="success", message="profile", data=user_res)
    await cached(cache_key, response, ttl=3600)
    logger.info("user %s profile successfully rendered", user_id)
    return response


async def view_profiles(request, state, db, limit, cursor_id):
    user_id = unique_id(request)
    role = user_role(request)
    if not user_id:
        logger.warning("unauthorized attempt at the view_profiles endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    if role not in ("Admin", "Owner"):
        logger.warning(
            "user: %s, tried to view all profiles without admin powers", user_id
        )
        raise HTTPException(status_code=403, detail="not authorized")
    state_filter = {
        None: None,
        "is_banned": (User.is_banned.is_(True),),
        "not_active": (User.is_active.is_(False), User.is_banned.is_(False)),
        "new_users": (User.created_at >= now - relativedelta(months=1),),
    }[state]
    version = await cache_version("profile_keys")
    cache_key = f"profiles:v{version}:{state}:{cursor_id}:{limit}"
    profile_cache = await cache(cache_key)
    if profile_cache:
        logger.info(
            "cache hit at general_profile endpoint for state: %s, cursor_id: %s, limit: %s",
            state,
            cursor_id,
            limit,
        )
        return StandardResponse(**profile_cache)
    query = select(User).order_by(User.id.asc())
    if state_filter is not None:
        query = query.where(*state_filter)
    if cursor_id is not None:
        query = query.where(User.id > cursor_id)
    query = query.limit(limit + 1)
    profiles = (await db.execute(query)).scalars().all()
    if not profiles:
        logger.warning("user: %s, has no user profiles in the database", user_id)
    has_more = len(profiles) > limit
    if has_more:
        profiles = profiles[:limit]
    next_cursor = profiles[-1].id if profiles else None
    user_res_list = []
    for profile in profiles:
        age = today.year - profile.date_of_birth.year
        if (today.month, today.day) < (
            profile.date_of_birth.month,
            profile.date_of_birth.day,
        ):
            age -= 1
        user_res = SuperUserResponse.model_validate(profile)
        user_res.profile_picture = (
            get_public_url(profile.profile_picture) if profile.profile_picture else None
        )
        user_res.age = int(age)
        user_res_list.append(user_res)
    data = PaginatedMetadata[SuperUserResponse](
        items=user_res_list,
        cursor_pagination=CursorPaginatedResponse(
            next_cursor=next_cursor, limit=limit, has_more=has_more
        ),
    )
    full_response = StandardResponse(status="success", message="profiles", data=data)
    await cached(cache_key, full_response, ttl=7200)
    logger.info(
        "user %s successfully queried general_profile endpoint with cursor_id: %s",
        user_id,
        cursor_id,
    )
    return full_response


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
        await profile_invalidation(user_id)
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
    jti = user_jti(request)
    exp = jwt_exp(request)
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
        data.is_active = False
        data.deactivation_time = now
        response.delete_cookie("refresh")
        await db.commit()
        await profile_global_invalidation()
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
    current_time = int(time.time())
    r_time = exp - current_time
    try:
        await redis_client.set(f"blacklist:{jti}", 1, ex=r_time)
    except Exception:
        logger.exception(
            "failed tto set blacklist in deactivate_profile function for user: %s",
            user_id,
        )
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
        await profile_global_invalidation()
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
