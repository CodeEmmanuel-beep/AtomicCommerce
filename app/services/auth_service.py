from app.auth.auth_jwt import (
    verify_password,
    create_access_token,
    create_refresh_token,
    hashed_password,
)
from sqlalchemy.exc import IntegrityError
from app.auth.verify_jwt import decode_token
from fastapi import HTTPException
from werkzeug.utils import secure_filename
from sqlalchemy import select
from app.models import User
from email_validator import validate_email, EmailNotValidError
import uuid
from app.logs.logger import get_logger
from datetime import timedelta
from app.database.config import settings

logger = get_logger("auth")


async def reg(
    name,
    username,
    email,
    nationality,
    address,
    password,
    confirm_password,
    profile_picture,
    db,
    get_supabase,
):
    min_chars = 4
    if len(username) < min_chars:
        raise HTTPException(status_code=400, detail="input atleast 4 characters")
    user_exists = (
        await db.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    try:
        validate_email(email)
    except EmailNotValidError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if password != confirm_password:
        raise HTTPException(
            status_code=400, detail="confirm password does not match password"
        )
    if user_exists:
        raise HTTPException(
            status_code=400, detail="username is already in use by another user"
        )
    email_exists = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if email_exists:
        raise HTTPException(
            status_code=400, detail="email is already in use by another user"
        )
    filename = None
    if profile_picture is not None:
        try:
            filename = f"{uuid.uuid4()}_{secure_filename(profile_picture.filename)}"
            file_byte = await profile_picture.read()
            client = await get_supabase.storage.from_(settings.BUCKET).upload(
                filename, file_byte, {"content-type": profile_picture.content_type}
            )
            if hasattr(client, "error"):
                logger.error("error uploading profile picture %s", client)
                raise HTTPException(status_code=500, detail="error uploading image")
        except Exception:
            logger.exception("error saving profile picture")
        profile_picture = filename
    else:
        profile_picture = None
    password = hashed_password(password)
    new_user = User(
        profile_picture=profile_picture,
        name=name.strip(),
        role="user",
        username=username.strip(),
        email=email.strip(),
        nationality=nationality.strip(),
        address=address.strip(),
        password=password,
    )
    try:
        db.add(new_user)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        logger.error("could not register user %s", username)
        if filename:
            clean_up = await get_supabase.storage.from_(settings.BUCKET).remove(
                [filename]
            )
            if hasattr(clean_up, "error"):
                logger.error("error removing orphaned profile picture %s", clean_up)
            else:
                logger.info("Orphaned profile picture successfully removed")
        raise HTTPException(status_code=500, detail="database error")
    except Exception:
        logger.exception("could not register user %s", username)
        if filename:
            clean_up = await get_supabase.storage.from_(settings.BUCKET).remove(
                [filename]
            )
            if hasattr(clean_up, "error"):
                logger.error("error removing orphaned profile picture %s", clean_up)
            else:
                logger.info("Orphaned profile picture successfully removed")
        raise HTTPException(status_code=500, detail="internal server error")
    return {f"Registeration Successful {username}, login to continue"}


async def logins(login, response, db):
    user = (
        await db.execute(select(User).where(User.username == login.username.strip()))
    ).scalar_one_or_none()
    if not user or not verify_password(login.password, user.password):
        raise HTTPException(status_code=400, detail="invalid username or password")
    token_expires = timedelta(minutes=60)
    access_token = create_access_token(
        data={
            "name": user.name,
            "sub": user.username,
            "user_id": user.id,
            "nationality": user.nationality,
            "role": user.role,
        },
        expire_delta=token_expires,
    )
    refresh_token = create_refresh_token(
        data={
            "name": user.name,
            "sub": user.username,
            "user_id": user.id,
            "nationality": user.nationality,
            "role": user.role,
        }
    )
    response.set_cookie(
        key="refresh", value=refresh_token, secure=True, samesite="lax", httponly=True
    )
    return {"access_token": access_token, "token_type": "Bearer"}


async def create_role(username, role, db, payload):
    user_id = payload.get("user_id")
    owner_username = payload.get("sub")
    if not user_id:
        logger.warning("unauthorized access at create_role endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    stmt = select(User).where(User.id == user_id, User.role == "Owner")
    owner = (await db.execute(stmt)).scalar_one_or_none()
    if not owner:
        logger.warning("user: %s, tried to create_role without authorization", user_id)
        raise HTTPException(status_code=403, detail="you are not the owner")
    stmt = select(User).where(User.username == username)
    admin = (await db.execute(stmt)).scalar_one_or_none()
    if not admin:
        logger.error(
            "user: %s, inputed a wrong username, while trying to create role", user_id
        )
        raise HTTPException(status_code=404, detail="user not found")
    if owner_username == username:
        logger.error("owner attempted to change their own role")
        raise HTTPException(status_code=400, detail="you cannot redesignate yourself")
    if admin.role == role:
        logger.error("owner tried assigning same role to the same user twice in a role")
        raise HTTPException(
            status_code=400,
            detail="role already assigned to user, click on a new role if you want to redesignate user",
        )
    admin.role = role
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
    logger.info("%s, successfully assigned a new role'", username)
    return {"status": "success", "message": f"{username} assigned role {role}"}


async def refresh_token(request, response):
    token = request.cookies.get("refresh")
    if not token:
        raise HTTPException(status_code=400, detail="Refresh token missing")
    payload = decode_token(token)
    if not payload or payload.get("type") != "refresh_token":
        raise HTTPException(status_code=400, detail="invalid refresh token")
    username = payload.get("sub")
    name = payload.get("name")
    user_id = payload.get("user_id")
    nationality = payload.get("nationality")
    role = payload.get("role")
    expire = timedelta(days=7)
    new_access = create_access_token(
        data={
            "sub": username,
            "name": name,
            "user_id": user_id,
            "nationality": nationality,
            "role": role,
        },
    )
    new_token = create_refresh_token(
        data={
            "sub": username,
            "name": name,
            "user_id": user_id,
            "nationality": nationality,
            "role": role,
        },
        expire_delta=expire,
    )
    response.set_cookie(
        key="refresh", value=new_token, httponly=True, samesite="lax", secure=True
    )
    return {"access_token": new_access, "token_type": "Bearer"}
