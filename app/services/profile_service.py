from fastapi import HTTPException
from app.logs.logger import get_logger
from sqlalchemy import select, or_, and_
from app.models import User, Membership
from app.utils.supabase_url import get_public_url, cleaned_up
from sqlalchemy.orm import selectinload
from app.api.v1.schemas import StandardResponse, UserResponse
from app.utils.helper import file_generator
from email_validator import validate_email, EmailNotValidError
from app.database.config import settings
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
import uuid

logger = get_logger("profiles")


async def view_profile(db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at the view_profile endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    profile = (
        (
            await db.execute(
                select(User, Membership)
                .outerjoin(Membership, User.id == Membership.user_id)
                .options(selectinload(Membership.store), selectinload(User.membership))
                .where(User.id == user_id)
            )
        )
        .unique()
        .all()
    )
    if not profile:
        logger.warning("user: %s, has no user profile in the database", user_id)
        raise HTTPException(status_code=404, detail="profile not found")
    user = profile[0][0]
    members = [pro[1] for pro in profile if pro[1] is not None]
    membership = {mem.store.store_name: mem.membership_type for mem in members}
    userres = UserResponse.model_validate(user)
    userres.profile_picture = (
        get_public_url(user.profile_picture) if user.profile_picture else None
    )
    userres.membership = [membership]
    return StandardResponse(status="success", message="profile", data=userres)


async def edit_profile(
    first_name,
    middle_name,
    surname,
    email,
    nationality,
    address,
    profile_picture,
    db,
    get_supabase,
    payload,
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at the edit_profile endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    user_exists = (
        await db.execute(select(User).where(User.id == user_id).with_for_update())
    ).scalar_one_or_none()
    try:
        validate_email(email)
    except EmailNotValidError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not user_exists:
        logger.warning("user: %s, do not have a profile in database", user_id)
        raise HTTPException(status_code=404, detail="profile not found")
    email_exists = (
        await db.execute(select(User).where(User.email == email, User.id != user_id))
    ).scalar_one_or_none()
    if email_exists:
        raise HTTPException(
            status_code=400, detail="email is already in use by another user"
        )
    filename = None
    old_filename = None
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
            old_filename = user_exists.profile_picture
            user_exists.profile_picture = filename
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
                    raise
                raise HTTPException(status_code=500, detail="error saving photo")
    logger.info("Starting registration for user: %s", user_id)
    fields = {
        "first_name": first_name,
        "middle_name": middle_name,
        "surname": surname,
        "email": email,
        "nationality": nationality,
        "address": address,
    }
    for attr, field in fields.items():
        setattr(user_exists, attr, field)
    try:
        await db.commit()
        if old_filename:
            await cleaned_up(
                get_supabase,
                old_filename,
                context_1="error removing old profile photo",
                context_2="successfully old profile photo",
            )
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        logger.error("could not edit profile for user %s", user_id)
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned profile photo",
                context_2="successfully removed orphaned profile photo",
            )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        logger.exception("could not edit profile for user %s", user_id)
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned profile photo",
                context_2="successfully removed orphaned profile photo",
            )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("user: %s, successfully edited his profile", user_id)
    return {"status": "success", "message": "profile successfully edited"}


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
        return {"status": "success", "message": "user already deactivated"}
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
    return {
        "status": "success",
        "message": "deleted profile",
        "data": {
            "id": profile_id,
            "user_id": user_id,
            "deleted": "Yes",
        },
    }
