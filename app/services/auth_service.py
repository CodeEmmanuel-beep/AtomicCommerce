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
from sqlalchemy import select, func
from app.models import User
from email_validator import validate_email, EmailNotValidError
import uuid
from app.logs.logger import get_logger
from datetime import timedelta
from app.database.config import settings
from app.utils.helper import file_generator
from app.utils.supabase_url import cleaned_up

logger = get_logger("auth")


async def reg(
    first_name,
    surname,
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
        await db.execute(
            select(User).where(
                func.lower(func.trim(User.username)) == username.strip().lower()
            )
        )
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
    if profile_picture:
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
            logger.info("Starting file upload for new user")
            file_byte = await file_generator(profile_picture, "not_registered")
            filename = f"{uuid.uuid4()}_{secure_filename(profile_picture.filename)}"
            client = await get_supabase.storage.from_(settings.BUCKET).upload(
                filename, file_byte, {"content-type": profile_picture.content_type}
            )
            if hasattr(client, "error"):
                logger.error("error uploading profile picture %s", client)
                raise HTTPException(status_code=500, detail="error uploading image")
        except Exception as e:
            await db.rollback()
            logger.exception("error saving profile picture")
            if filename:
                await cleaned_up(
                    get_supabase,
                    filename,
                    context_1="error removing orphaned profile photo",
                    context_2="successfully removed orphaned profile photo",
                )
                if isinstance(e, HTTPException):
                    raise e
                raise HTTPException(status_code=500, detail="error saving photo")
    password = hashed_password(password)
    logger.info("Starting registration for user: %s", username)
    new_user = User(
        profile_picture=filename,
        first_name=first_name.strip(),
        surname=surname.strip(),
        role="user",
        username=username.strip().lower(),
        email=email.strip(),
        nationality=nationality.strip(),
        address=address.strip() if address else None,
        password=password,
    )
    try:
        db.add(new_user)
        await db.commit()
    except IntegrityError:
        logger.error("could not register user %s", username)
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned profile photo",
                context_2="successfully removed orphaned profile photo",
            )
        raise HTTPException(status_code=400, detail="database error")
    except Exception as e:
        await db.rollback()
        logger.exception("could not register user %s", username)
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned profile photo",
                context_2="successfully removed orphaned profile photo",
            )
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("user: %s, successfully registered", username)
    return {f"Registeration Successful {username}, login to continue"}


async def logins(login, response, db):
    user = (
        await db.execute(
            select(User).where(User.username == login.username.strip(), User.is_active)
        )
    ).scalar_one_or_none()
    if not user or not verify_password(login.password, user.password):
        raise HTTPException(status_code=400, detail="invalid username or password")
    token_expires = timedelta(minutes=60)
    access_token = create_access_token(
        data={
            "name": user.surname,
            "sub": user.username,
            "user_id": user.id,
            "nationality": user.nationality,
            "role": user.role,
        },
        expire_delta=token_expires,
    )
    refresh_token = create_refresh_token(
        data={
            "name": user.surname,
            "sub": user.username,
            "user_id": user.id,
            "nationality": user.nationality,
            "role": user.role,
        }
    )
    response.set_cookie(
        key="refresh", value=refresh_token, secure=True, samesite="lax", httponly=True
    )
    logger.info(f"User {login.username} logged in successfully")
    return {
        "status": "success",
        "message": "login successful",
        "access_token": access_token,
        "token_type": "Bearer",
    }


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
    surname = payload.get("surname")
    user_id = payload.get("user_id")
    nationality = payload.get("nationality")
    role = payload.get("role")
    expire = timedelta(days=7)
    new_access = create_access_token(
        data={
            "sub": username,
            "surname": surname,
            "user_id": user_id,
            "nationality": nationality,
            "role": role,
        },
    )
    new_token = create_refresh_token(
        data={
            "sub": username,
            "surname": surname,
            "user_id": user_id,
            "nationality": nationality,
            "role": role,
        },
        expire_delta=expire,
    )
    response.set_cookie(
        key="refresh", value=new_token, httponly=True, samesite="lax", secure=True
    )
    logger.info(f"Refresh token successful for username: {username}")
    return {"access_token": new_access, "token_type": "Bearer"}


async def logout(response):
    response.delete_cookie("refresh")
    logger.info("User logged out successfully")
    return {"message": "logged out"}
