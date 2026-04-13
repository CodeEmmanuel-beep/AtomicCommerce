from app.logs.logger import get_logger
from fastapi import HTTPException, Query
from app.models import Membership, User, Subscription
from sqlalchemy.exc import IntegrityError
from app.api.v1.schemas import (
    MembershipResponse,
    MembershipRes,
    PaginatedMetadata,
    PaginatedResponse,
    StandardResponse,
)
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.utils.redis import (
    cache,
    cached,
    member_invalidation,
    cache_version,
    member_global_invalidation,
)
import asyncio
from app.database.config import settings

logger = get_logger("membership")


async def make_member(
    db,
    payload,
    membership_type: str = Query("Standard", enum=["Regular", "Premium", "Standard"]),
    activate: str = Query("yes", enum=["no", "yes"]),
    activation_type: str = Query("one_time", enum=["subscription", "one_time"]),
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized user tried to access make_member endpoint")
        raise HTTPException(
            status_code=401, detail="you need to register to apply for membership"
        )
    existing = (
        await db.execute(
            select(Membership).where(Membership.user_id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if existing:
        if existing.is_deleted:
            logger.warning(f"Deleted user {user_id} tried to re-register.")
            raise HTTPException(
                status_code=403,
                detail="This ID has a deleted membership. Contact support to reactivate.",
            )
        raise HTTPException(status_code=400, detail="Already an active member.")
    member = Membership(
        user_id=user_id,
        membership_type=membership_type,
    )
    db.add(member)
    if activate == "yes":
        await db.flush()
        sub_table = Subscription(membership_id=member.id, plan_name=membership_type)
        if activation_type == "one_time":
            price_map = {
                "Standard": settings.standard_price,
                "Regular": settings.regular_price,
                "Premium": settings.premium_price,
            }
            sub_table.plan_price = price_map[membership_type]
        if activation_type == "subscription":
            price_map = {
                "Standard": settings.Standard,
                "Regular": settings.Regular,
                "Premium": settings.Premium,
            }
            sub_table.price_id = price_map[membership_type]
        db.add(sub_table)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error(
            f"database error occured while adding user:'{user_id}' as a member"
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(f"error occured while adding user:'{user_id}' as a member")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(
        f"member crerated with user_id: '{user_id}' and membership_type: '{membership_type}'"
    )
    return {"message": "membership created"}


async def update(membership_type, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized user tried to assess make_member endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Membership).where(Membership.user_id == user_id)
    change = (await db.execute(stmt)).scalar_one_or_none()
    if not change:
        logger.warning(
            f"user: {user_id} tried updating their membership without being a member"
        )
        raise HTTPException(status_code=404, detail="not a member")
    change.membership_type = membership_type
    try:
        await db.commit()
        await db.refresh(change)
        await member_invalidation(user_id)
    except IntegrityError:
        await db.rollback()
        logger.error(
            f"database error occured while updating membership_type for user:'{user_id}'"
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            f"error occured while updating membership_type for user:'{user_id}'"
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(
        f"user: {user_id} successfully updated their membership_type to '{membership_type}'"
    )
    return {"message": "membership type updated"}


async def view_member(db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt to access view_member endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    cache_key = f"membership:{user_id}"
    cached_member = await cache(cache_key)
    if cached_member:
        logger.info("cached hit at view_member endpoint user %s", user_id)
        return StandardResponse(**cached_member)
    stmt = (
        select(Membership)
        .options(selectinload(Membership.user))
        .where(
            Membership.user_id == user_id,
            ~Membership.is_deleted,
            ~Membership.is_pause,
        )
    )
    member = (await db.execute(stmt)).scalar_one_or_none()
    if not member:
        logger.warning(
            "unauthorized attempt at view_member endpoint, user %s , is not a member",
            user_id,
        )
        raise HTTPException(status_code=404, detail="not a member")
    member_data = MembershipResponse.model_validate(member)
    full_response = StandardResponse(
        status="success", message="membership information", data=member_data
    )
    await cached(cache_key, full_response, ttl=18000)
    logger.info("member's data cached successfully member_id: %s", member.id)
    return full_response


async def view_active_members(page, limit, db, payload):
    user_id = payload.get("user_id")
    username = payload.get("sub")
    if not user_id:
        logger.warning("unauthorized attempt to access view_active_members endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    offset = (page - 1) * limit
    if page < 1 or limit < 1:
        raise HTTPException(
            status_code=400, detail="page number and limit must be greater than 0"
        )
    stmt = select(User).where(User.id == user_id)
    admin = (await db.execute(stmt)).scalar_one_or_none()
    if not admin or admin.role not in ["Admin", "Owner"]:
        logger.warning(
            f"user: '{user_id}' tried accessing view_active_members endpoint without authorization"
        )
        raise HTTPException(status_code=403, detail="restricted access")
    version = await cache_version("member_key")
    cache_key = f"membership:v{version}:active:{page}:{limit}"
    cached_member = await cache(cache_key)
    if cached_member:
        logger.info("cached hit at view_active_members endpoint user %s", user_id)
        return StandardResponse(**cached_member)
    stmt = (
        select(Membership)
        .options(
            selectinload(Membership.user),
        )
        .where(Membership.is_active, ~Membership.is_deleted)
    )
    total = (
        await db.execute(
            select(func.count())
            .select_from(Membership)
            .where(Membership.is_active, ~Membership.is_deleted)
        )
    ).scalar() or 0
    members = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    if not members:
        logger.info("active members search returned an empty list")
        return StandardResponse(
            status="success", message="no active member found", data=None
        )
    logger.info("total number of active members %s", total)
    data = PaginatedMetadata[MembershipRes](
        items=[MembershipRes.model_validate(mem) for mem in members],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    response = StandardResponse(
        status="success", message="membership information", data=data
    )
    await cached(cache_key, response, ttl=3600)
    logger.info("active members data cached successfully admin: %s", username)
    return response


async def view_inactive_members(page, limit, db, payload):
    user_id = payload.get("user_id")
    username = payload.get("sub")
    if not user_id:
        logger.warning("unauthorized attempt to access view_inactive_members endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    offset = (page - 1) * limit
    stmt = select(User).where(User.id == user_id)
    admin = (await db.execute(stmt)).scalar_one_or_none()
    if not admin or admin.role not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="restricted access")
    version = await cache_version("member_key")
    cache_key = f"membership:v{version}:inactive:{page}:{limit}"
    cached_member = await cache(cache_key)
    if cached_member:
        logger.info("cached hit at view_inactive_members endpoint user %s", user_id)
        return StandardResponse(**cached_member)
    stmt = (
        select(Membership)
        .options(
            selectinload(Membership.user),
        )
        .where(~Membership.is_active, ~Membership.is_deleted)
    )
    total = (
        await db.execute(
            select(func.count())
            .select_from(Membership)
            .where(~Membership.is_active, ~Membership.is_deleted)
        )
    ).scalar() or 0
    members = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    if not members:
        logger.info("inactive members search returned an empty list")
        return StandardResponse(
            status="success", message="no inactive member found", data=None
        )
    logger.info("total number of inactive members %s", total)
    data = PaginatedMetadata[MembershipRes](
        items=[MembershipRes.model_validate(mem) for mem in members],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    response = StandardResponse(
        status="success", message="membership information", data=data
    )
    await cached(cache_key, response, ttl=3600)
    logger.info("inactuve members data cached successfully admin: %s", username)
    return response


async def view_paused_members(page, limit, db, payload):
    user_id = payload.get("user_id")
    username = payload.get("sub")
    if not user_id:
        logger.warning("unauthorized attempt to access view_paused_members endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    offset = (page - 1) * limit
    stmt = select(User).where(User.id == user_id)
    admin = (await db.execute(stmt)).scalar_one_or_none()
    if not admin or admin.role not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="restricted access")
    version = await cache_version("member_key")
    cache_key = f"membership:v{version}:paused:{page}:{limit}"
    cached_member = await cache(cache_key)
    if cached_member:
        logger.info("cached hit at view_paused_members endpoint user %s", user_id)
        return StandardResponse(**cached_member)
    stmt = (
        select(Membership)
        .options(
            selectinload(Membership.user),
        )
        .where(Membership.is_pause, ~Membership.is_deleted)
    )
    total = (
        await db.execute(
            select(func.count())
            .select_from(Membership)
            .where(Membership.is_pause, ~Membership.is_deleted)
        )
    ).scalar() or 0
    members = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    if not members:
        logger.info("paused members search returned an empty list")
        return StandardResponse(
            status="success", message="no paused member found", data=None
        )
    logger.info("total number of paused members %s", total)
    data = PaginatedMetadata[MembershipRes](
        items=[MembershipRes.model_validate(mem) for mem in members],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    response = StandardResponse(
        status="success", message="membership information", data=data
    )
    await cached(cache_key, response, ttl=3600)
    logger.info("paused members data cached successfully admin: %s", username)
    return response


async def view_deleted_members(page, limit, db, payload):
    user_id = payload.get("user_id")
    username = payload.get("sub")
    if not user_id:
        logger.warning("unauthorized attempt to access view_deleted_members endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    offset = (page - 1) * limit
    stmt = select(User).where(User.id == user_id)
    admin = (await db.execute(stmt)).scalar_one_or_none()
    if not admin or admin.role not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="restricted access")
    version = await cache_version("member_key")
    cache_key = f"membership:v{version}:deleted:{page}:{limit}"
    cached_member = await cache(cache_key)
    if cached_member:
        logger.info("cached hit at view_deleted_members endpoint user %s", user_id)
        return StandardResponse(**cached_member)
    stmt = (
        select(Membership)
        .options(
            selectinload(Membership.user),
        )
        .where(Membership.is_deleted)
    )
    total = (
        await db.execute(
            select(func.count()).select_from(Membership).where(Membership.is_deleted)
        )
    ).scalar() or 0
    members = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    if not members:
        logger.info("deleted members search returned an empty list")
        return StandardResponse(
            status="success", message="no deleted member found", data=None
        )
    logger.info("total number of deleted members %s", total)
    data = PaginatedMetadata[MembershipRes](
        items=[MembershipRes.model_validate(mem) for mem in members],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    response = StandardResponse(
        status="success", message="membership information", data=data
    )
    await cached(cache_key, response, ttl=3600)
    logger.info("deleted members data cached successfully admin: %s", username)
    return response


async def pause_membership(db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt to access view_deleted_members endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Membership).where(Membership.user_id == user_id)
    pause = (await db.execute(stmt)).scalar_one_or_none()
    if not pause:
        logger.warning(
            f"user: {user_id}, tried tried accessing pause_membership endpoint before registering as a member"
        )
        raise HTTPException(status_code=409, detail="invalid request")
    today = func.now()
    if pause.is_pause:
        return {"message": "membership is already paused"}
    pause.is_pause = True
    pause.pause_date = today
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error(
            "database error occured while pausing membership user affected: %s", user_id
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            "error occured while pausing membership user affected: %s", user_id
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"user: {user_id} paused their membership")
    return {"message": "membership paused"}


async def reactivate_membership(db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt to access view_deleted_members endpoint")
        raise HTTPException(status_code=401, detail="not authorized")
    stmt = select(Membership).where(Membership.user_id == user_id)
    activate = (await db.execute(stmt)).scalar_one_or_none()
    if not activate:
        logger.warning(
            f"user: {user_id}, tried tried accessing reactivate_membership endpoint before registering as a member"
        )
        raise HTTPException(status_code=404, detail="not a member")
    today = func.now()
    if activate.is_pause:
        return {"message": "membership is not paused"}
    activate.is_pause = False
    activate.reactivation_date = today
    try:
        await db.commit()
        await asyncio.gather(member_invalidation(user_id), member_global_invalidation())
    except IntegrityError:
        await db.rollback()
        logger.error(
            "database error occured while reactivating membership user affected: %s",
            user_id,
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            "error occured while reactivating membership user affected: %s", user_id
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"user: {user_id} reactivated their membership")
    return {"message": "member reactivated"}


async def restore_membership(membership_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt to access view_deleted_members endpoint")
        raise HTTPException(status_code=401, detail="not authorized")
    stmt = select(User).where(User.id == user_id)
    admin = (await db.execute(stmt)).scalar_one_or_none()
    if not admin or admin.role not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="restricted access")
    stmt = select(Membership).where(Membership.id == membership_id)
    restore = (await db.execute(stmt)).scalar_one_or_none()
    if not restore:
        logger.warning(
            f"admin with user_id: {user_id}, inputed an invalid membership_id"
        )
        raise HTTPException(status_code=404, detail="not a member")
    if ~restore.is_deleted:
        return {"message": "membership is not deleted"}
    restore.is_deleted = False
    try:
        await db.commit()
        await member_global_invalidation()
    except IntegrityError:
        await db.rollback()
        logger.error(
            "database error occured while restoring membership member affected: %s",
            membership_id,
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            "error occured while restoring membership member affected: %s",
            membership_id,
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("admin restored membership for membership_id: %s", membership_id)
    return {"message": "membership restored"}


async def delete_member(db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt to access delete_member endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Membership).where(
        Membership.user_id == user_id,
    )
    member = (await db.execute(stmt)).scalar_one_or_none()
    if not member:
        logger.warning(
            f"user: {user_id}, tried tried accessing delete_membership endpoint before registering as a member"
        )
        raise HTTPException(status_code=404, detail="not a member")
    if member.is_deleted:
        return {"message": "membership is already deleted"}
    member.is_deleted = True
    member.is_active = False
    member.is_pause = False
    today = func.now()
    member.delete_date = today
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error(
            "database error occured while deleting membership user affected: %s",
            user_id,
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            "error occured while deleting membership user affected: %s", user_id
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"user: {user_id} deleted their membership")
    return {"message": "membership deleted"}
