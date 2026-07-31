from app.auth.auth_jwt import (
    verify_password,
    create_access_token,
    create_refresh_token,
    hashed_password,
)
from sqlalchemy.exc import IntegrityError
from app.auth.decode_jwt import decode_token
from fastapi import HTTPException, status
from werkzeug.utils import secure_filename
from sqlalchemy import select, func
from app.models import User
from email_validator import validate_email, EmailNotValidError
import uuid
from app.utils.redis import redis_client
from app.api.v1.schemas import StandardResponse
from app.logs.logger import get_logger
from dateutil.relativedelta import relativedelta
from datetime import timedelta, datetime, timezone
from app.database.config import settings
import time
from fastapi.responses import JSONResponse
from app.utils.helper import file_generator
from app.utils.helper import unique_id, user_jti, jwt_exp, user_role
from app.utils.supabase_url import cleaned_up

logger = get_logger("auth")

FORBIDDEN_WORDS = {"user", "admin", "system", "root", "moderator"}


async def reg(
    registration,
    db,
):
    min_chars = 4
    if len(registration.username) < min_chars:
        raise HTTPException(
            status_code=400, detail="username should be atleast 4 characters"
        )
    user_str = registration.username.strip()
    if "".join(user_str.split()).lower() in FORBIDDEN_WORDS:
        raise HTTPException(
            status_code=400, detail="your username is restricted, choose another"
        )
    if " " in user_str:
        raise HTTPException(
            status_code=400, detail="username should be only one word, no spaces"
        )
    user_exists = (
        await db.execute(
            select(User).where(
                func.lower(func.trim(User.username))
                == registration.username.strip().lower()
            )
        )
    ).scalar_one_or_none()
    try:
        validate_email(registration.email)
    except EmailNotValidError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if registration.password != registration.confirm_password:
        raise HTTPException(
            status_code=400, detail="confirm password does not match password"
        )
    if user_exists:
        raise HTTPException(
            status_code=400, detail="username is already in use by another user"
        )
    email_exists = (
        await db.execute(select(User).where(User.email == registration.email))
    ).scalar_one_or_none()
    if email_exists:
        raise HTTPException(
            status_code=400, detail="email is already in use by another user"
        )
    try:
        password = hashed_password(registration.password)
        logger.info("Starting registration for user: %s", registration.username)
        new_user = User(
            first_name=registration.first_name.strip(),
            surname=registration.surname.strip(),
            role="user",
            username=registration.username.strip().lower(),
            email=registration.email.strip(),
            nationality=registration.nationality.strip(),
            address=registration.address.strip() if registration.address else None,
            password=password,
        )
        db.add(new_user)
        await db.commit()
    except IntegrityError:
        logger.error("could not register user %s", registration.username)
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("could not register user %s", registration.username)
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("user: %s, successfully registered", registration.username)
    return StandardResponse(
        status="success",
        message=f"Registeration Successful {registration.username}, login to continue",
        data=None,
    )


async def upload_profile_picture(request, profile_picture, db, get_supabase):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("Unauthorized attempt at the upload_profile_picture function")
        raise HTTPException(status_code=401, detail="not a valid user")
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if not user:
        logger.warning(
            "user: %s, tried uploading profile picture in an unauthorized row"
        )
        raise HTTPException(status_code=404, detail="user not found")
    filename = None
    old_filename = user.profile_picture if user.profile_picture else None
    await db.rollback()
    try:
        allowed_files = ["image/png", "image/jpeg", "image/webp"]
        if profile_picture.content_type not in allowed_files:
            logger.warning(
                "user tried uploading an invalid file type: %s",
                profile_picture.content_type,
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid file type. Only JPG, PNG, WEBP allowed.",
            )
        logger.info("Starting file upload for user: %s", user_id)
        file_byte = await file_generator(profile_picture, "user_id")
        filename = f"{uuid.uuid4()}_{secure_filename(profile_picture.filename)}"
        client = await get_supabase.storage.from_(settings.BUCKET).upload(
            filename,
            file_byte,
            {"content-type": profile_picture.content_type},
        )
        if hasattr(client, "error"):
            logger.error("error uploading profile picture %s", client)
            raise HTTPException(status_code=500, detail="error uploading image")
        result = await db.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
        locked_user = result.scalar_one_or_none()
        if not locked_user:
            raise HTTPException(
                status_code=404, detail="User record vanished during asset upload."
            )
        locked_user.profile_picture = filename
        await db.commit()
        if old_filename:
            await cleaned_up(
                get_supabase,
                old_filename,
                context_1="error removing orphaned profile photo",
                context_2="successfully removed orphaned profile photo",
            )
    except HTTPException:
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned profile photo",
                context_2="successfully removed orphaned profile photo",
            )
        raise
    except Exception:
        await db.rollback()
        logger.exception("foundational error saving profile picture to database")
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned profile photo",
                context_2="successfully removed orphaned profile photo",
            )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("profile picture uploaded successfully")
    return StandardResponse(
        status="success", message="profile picture uploaded successfully", data=None
    )


async def logins(login, response, db):
    user = (
        await db.execute(select(User).where(User.username == login.username.strip()))
    ).scalar_one_or_none()
    if not user or not verify_password(login.password, user.password):
        raise HTTPException(status_code=400, detail="invalid username or password")
    now = datetime.now(timezone.utc)
    user_id = user.id
    has_changed = False
    need_redis_uncache = False
    if not user.is_active and not user.is_banned:
        three_months_ago = now - relativedelta(months=3)
        if user.deactivation_time and user.deactivation_time < three_months_ago:
            logger.warning("Permanently deactivated user %s attempted login", user_id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="this account has been permanently deactivated",
            )
        else:
            user.is_active = True
            user.deactivation_time = None
            has_changed = True
    if user.is_banned:
        if user.indefinite_ban:
            logger.warning("blocked user: %s, tried logging in", user_id)
            raise HTTPException(
                status_code=401,
                detail="this account is permanently suspended, if you need clarifications contact support",
            )
        ban_begin = user.ban_date or now
        ban_period = None
        try:
            ban_value = int(user.ban_period)
            if user.ban_unit == "days":
                ban_period = ban_begin + relativedelta(days=ban_value)
            else:
                ban_period = ban_begin + relativedelta(months=ban_value)
        except (ValueError, TypeError):
            logger.error(
                "Invalid ban_period value '%s' for user %s",
                user.ban_period,
                user_id,
            )
            ban_period = now + timedelta(days=1)
        if ban_period and now < ban_period:
            lift_date_str = ban_period.strftime("%Y-%m-%d")
            logger.warning("suspended user: %s, tried logging in", user_id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"this account is suspended until {lift_date_str}",
            )
        else:
            user.is_banned = False
            user.is_active = True
            user.ban_unit = None
            user.ban_period = 0
            need_redis_uncache = True
            has_changed = True
    token_expires = timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)
    if has_changed:
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception(
                "Failed to update user state on login for user %s", user_id
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="login failed due to database update error",
            )
    if need_redis_uncache:
        try:
            await redis_client.delete(f"banned_client:{user_id}")
        except Exception:
            logger.exception("could not clear redis ban cache for user: %s", user_id)
    access_token = create_access_token(
        data={
            "jti": str(uuid.uuid4()),
            "sub": user.username,
            "user_id": user_id,
            "role": user.role,
        },
        expire_delta=token_expires,
    )
    refresh_token = create_refresh_token(
        data={
            "jti": str(uuid.uuid4()),
            "sub": user.username,
            "user_id": user_id,
            "role": user.role,
        }
    )
    response.set_cookie(
        key="refresh",
        value=refresh_token,
        secure=True,
        samesite="lax",
        httponly=True,
        max_age=60 * 60 * 24 * 7,
    )
    logger.info("User '%s' logged in successfully", login.username)
    data = {"access_token": access_token, "token_type": "Bearer"}
    return StandardResponse(status="success", message="login successful", data=data)


async def create_role(id_number, request, assigned_role, db):
    user_id = unique_id(request)
    role = user_role(request)
    if not user_id:
        logger.warning("unauthorized access at create_role endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    if role != "Owner":
        logger.warning("user: %s, tried to create_role without authorization", user_id)
        raise HTTPException(status_code=403, detail="you are not the owner")
    stmt = select(User).where(User.id == id_number)
    admin = (await db.execute(stmt)).scalar_one_or_none()
    if not admin:
        logger.warning(
            "user: %s, inputed a wrong user_id, while trying to create role", user_id
        )
        raise HTTPException(status_code=404, detail="user not found")
    if user_id == id_number:
        logger.error("owner attempted to change their own role")
        raise HTTPException(status_code=400, detail="you cannot redesignate yourself")
    if admin.role == assigned_role:
        logger.warning(
            "owner tried assigning same role to the same user twice in a role"
        )
        raise HTTPException(
            status_code=400,
            detail="role already assigned to user, click on a new role if you want to redesignate user",
        )
    admin.role = assigned_role
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.exception("database error occured while creating role")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error occured while creating role")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("User: %s, successfully assigned a new role'", id_number)
    return StandardResponse(
        status="success",
        message=f"User '{id_number}' assigned role: {assigned_role}",
        data=None,
    )


async def refresh_token(request, response):
    access_user_id = unique_id(request)
    token = request.cookies.get("refresh")
    if not token:
        raise HTTPException(status_code=401, detail="Refresh token missing")
    payload = decode_token(token)
    if not payload or payload.get("type") != "refresh_token":
        response.delete_cookie("refresh")
        raise HTTPException(status_code=401, detail="invalid refresh token")
    username = payload.get("sub")
    user_id = payload.get("user_id")
    role = payload.get("role")
    old_jti = payload.get("jti")
    old_exp = payload.get("exp")
    if access_user_id and user_id and access_user_id != user_id:
        logger.warning("session conflict at refresh token endpoint")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Session conflict: A different user logged in on another tab.",
        )
    try:
        async with redis_client.pipeline(transaction=False) as pipe:
            pipe.exists(f"blacklist:{old_jti}")
            pipe.exists(f"banned_client:{user_id}")
            is_blacklisted, is_banned = await pipe.execute()
        if is_banned:
            logger.warning("banned user: %s, tried tried refreshing token", user_id)
            response.delete_cookie("refresh")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="User account is banned"
            )
        if is_blacklisted:
            logger.warning("blacklisted user: %s, tried refreshing token", user_id)
            response.delete_cookie("refresh")
            raise HTTPException(
                status_code=401,
                detail="user logged out",
            )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Redis unavailable during refresh")
        raise HTTPException(
            status_code=503,
            detail="Authentication service unavailable",
        )
    access_jti = str(uuid.uuid4())
    refresh_jti = str(uuid.uuid4())
    new_access = create_access_token(
        data={
            "sub": username,
            "jti": access_jti,
            "user_id": user_id,
            "role": role,
        },
    )
    new_token = create_refresh_token(
        data={
            "sub": username,
            "user_id": user_id,
            "jti": refresh_jti,
            "role": role,
        }
    )
    current_time = int(time.time())
    if old_exp and old_exp > current_time:
        try:
            await redis_client.set(
                f"blacklist:{old_jti}", "true", ex=old_exp - current_time
            )
        except Exception:
            logger.exception("Redis unavailable during blacklisting of refresh token")
            raise HTTPException(
                status_code=503,
                detail="Authentication service unavailable",
            )
    response.set_cookie(
        key="refresh",
        value=new_token,
        httponly=True,
        samesite="lax",
        secure=True,
        max_age=60 * 60 * 24 * 7,
    )
    logger.info("Refresh token successful for user_id: %s", user_id)
    data = {"access_token": new_access, "token_type": "Bearer"}
    return StandardResponse(status="success", message="refresh token", data=data)


async def logout(request, response):
    user_id = unique_id(request)
    jti = user_jti(request)
    exp = jwt_exp(request)
    if not jti or not exp:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "Invalid token payload for logout."},
        )
    current_time = int(time.time())
    refresh = request.cookies.get("refresh")
    try:
        async with redis_client.pipeline(transaction=False) as pipe:
            ttl = exp - current_time
            if ttl > 0:
                pipe.set(f"blacklist:{jti}", "true", ex=ttl)
            if refresh:
                payload = decode_token(refresh)
                refresh_jti = payload.get("jti")
                refresh_exp = payload.get("exp")
                if refresh_exp and refresh_jti:
                    refresh_ttl = refresh_exp - current_time
                    if refresh_ttl > 0:
                        pipe.set(f"blacklist:{refresh_jti}", "true", ex=refresh_ttl)
            await pipe.execute()
    except Exception:
        logger.exception("Redis unavailable during logout")
        raise HTTPException(
            status_code=503,
            detail="Authentication service unavailable",
        )
    response.delete_cookie("refresh")
    logger.info("User '%s' logged out successfully", user_id)
    return StandardResponse(status="success", message="logged out", data=None)
