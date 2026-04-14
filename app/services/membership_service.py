from app.logs.logger import get_logger
from fastapi import HTTPException
from app.models import Membership, Store, store_owners, store_staffs, Subscription
from sqlalchemy.exc import IntegrityError
from app.api.v1.schemas import MembershipResponse, StandardResponse

from app.utils.helper import view_selected_members
from sqlalchemy import select, func, or_, exists, and_
from sqlalchemy.orm import selectinload
from app.utils.redis import (
    cache,
    cached,
    member_invalidation,
    member_global_invalidation,
)
import asyncio
from app.database.config import settings

logger = get_logger("membership")


async def make_member(
    store_id, membership_type, activate, activation_type, db, payload
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized user tried to access make_member endpoint")
        raise HTTPException(
            status_code=401, detail="you need to register to apply for membership"
        )
    existing = (
        await db.execute(
            select(Membership)
            .where(Membership.user_id == user_id, Membership.store_id == store_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing:
        if existing.is_deleted:
            logger.warning(f"Deleted user {user_id} tried to re-register.")
            raise HTTPException(
                status_code=403,
                detail="this ID has a deleted membership. Contact support to reactivate.",
            )
        raise HTTPException(status_code=400, detail="already a member of this store.")
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
                "Standard": settings.Standard_Price,
                "Regular": settings.Regular_Price,
                "Premium": settings.Premium_Price,
            }
            sub_table.plan_price = price_map[membership_type]
            sub_table.price_id = None
        if activation_type == "subscription":
            price_map = {
                "Standard": settings.Standard,
                "Regular": settings.Regular,
                "Premium": settings.Premium,
            }
            sub_table.price_id = price_map[membership_type]
            sub_table.plan_price = None
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
    await member_global_invalidation()
    return {"message": "membership created"}


async def update(store_id, membership_type, activate, activation_type, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized user tried to assess make_member endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = (
        select(Membership)
        .where(Membership.user_id == user_id, Membership.store_id == store_id)
        .with_for_update()
    )
    change = (await db.execute(stmt)).scalar_one_or_none()
    if not change:
        logger.warning(
            f"user: {user_id} tried updating their membership without being a member"
        )
        raise HTTPException(status_code=404, detail="not a member")
    sub = (
        await db.execute(
            select(Subscription)
            .where(Subscription.membership_id == change.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if sub:
        logger.info("existing subscription found for user: %s", user_id)
        return {
            "status": "success",
            "message": "existing subscription found. Use the 'Update Plan' portal to manage it.",
        }
    change.membership_type = membership_type
    if activate == "yes":
        sub_table = Subscription(membership_id=change.id, plan_name=membership_type)
        if activation_type == "one_time":
            price_map = {
                "Standard": settings.Standard_Price,
                "Regular": settings.Regular_Price,
                "Premium": settings.Premium_Price,
            }
            sub_table.plan_price = price_map[membership_type]
            sub_table.price_id = None
        if activation_type == "subscription":
            price_map = {
                "Standard": settings.Standard,
                "Regular": settings.Regular,
                "Premium": settings.Premium,
            }
            sub_table.price_id = price_map[membership_type]
            sub_table.plan_price = None
        db.add(sub_table)
    try:
        await db.commit()
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
    await member_global_invalidation()
    return {"message": "membership type updated"}


async def view_membership(store_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt to access view_member endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    cache_key = f"membership:{store_id}:{user_id}"
    cached_member = await cache(cache_key)
    if cached_member:
        logger.info("cached hit at view_member endpoint user %s", user_id)
        return StandardResponse(**cached_member)
    stmt = (
        select(Membership)
        .options(selectinload(Membership.user))
        .where(
            Membership.user_id == user_id,
            Membership.store_id == store_id,
            ~Membership.is_deleted,
            ~Membership.is_pause,
        )
    )
    member = (await db.execute(stmt)).scalar_one_or_none()
    if not member:
        logger.warning(
            "unauthorized attempt at view_member endpoint, user %s , is not a member of store: %s",
            user_id,
            store_id,
        )
        raise HTTPException(status_code=404, detail="not a member of this store")
    member_data = MembershipResponse.model_validate(member)
    full_response = StandardResponse(
        status="success", message="membership information", data=member_data
    )
    await cached(cache_key, full_response, ttl=18000)
    logger.info("member's data cached successfully member_id: %s", member.id)
    return full_response


async def view_memberships(db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt to access view_member endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    cache_key = f"membership_list:{user_id}"
    cached_member = await cache(cache_key)
    if cached_member:
        logger.info("cached hit at view_member endpoint user %s", user_id)
        return StandardResponse(**cached_member)
    stmt = (
        select(Membership)
        .options(selectinload(Membership.stores))
        .where(
            Membership.user_id == user_id,
            ~Membership.is_deleted,
            ~Membership.is_pause,
        )
    )
    members = (await db.execute(stmt)).scalars().all()
    if not members:
        logger.warning(
            "unauthorized attempt at view_member endpoint, user %s , is not a member of any store",
            user_id,
        )
        raise HTTPException(status_code=404, detail="not a member of any store")
    store_map = {mem.stores.slug: mem.stores.store_name for mem in members}
    full_response = StandardResponse(
        status="success",
        message="stores where you are have a membership card",
        data=store_map,
    )
    await cached(cache_key, full_response, ttl=1800)
    logger.info("Cached %s memberships for user %s", len(members), user_id)
    return full_response


async def view_active_members(store_id, page, limit, db, payload):
    return await view_selected_members(
        store_id,
        Membership.is_active,
        ~Membership.is_deleted,
        "active",
        page,
        limit,
        db,
        payload,
    )


async def view_inactive_members(store_id, page, limit, db, payload):
    return await view_selected_members(
        store_id,
        ~Membership.is_active,
        ~Membership.is_deleted,
        "inactive",
        page,
        limit,
        db,
        payload,
    )


async def view_paused_members(store_id, page, limit, db, payload):
    return await view_selected_members(
        store_id,
        Membership.is_pause,
        ~Membership.is_deleted,
        "paused",
        page,
        limit,
        db,
        payload,
    )


async def view_deleted_members(store_id, page, limit, db, payload):
    return await view_selected_members(
        store_id,
        ~Membership.is_active,
        Membership.is_deleted,
        "deleted",
        page,
        limit,
        db,
        payload,
    )


async def pause_membership(db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt at pause membership endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    stmt = select(Membership).where(Membership.user_id == user_id)
    pause = (await db.execute(stmt)).scalar_one_or_none()
    if not pause:
        logger.warning(
            f"user: {user_id}, tried accessing pause_membership endpoint before registering as a member"
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
    await member_global_invalidation()
    return {"message": "membership paused"}


async def reactivate_membership(db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt to access reactivate membership endpoint")
        raise HTTPException(status_code=401, detail="not authorized")
    stmt = select(Membership).where(Membership.user_id == user_id)
    activate = (await db.execute(stmt)).scalar_one_or_none()
    if not activate:
        logger.warning(
            f"user: {user_id}, tried accessing reactivate_membership endpoint before registering as a member"
        )
        raise HTTPException(status_code=404, detail="not a member")
    today = func.now()
    if not activate.is_pause:
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


async def restore_membership(store_id, membership_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt to access restore_membership endpoint")
        raise HTTPException(status_code=401, detail="not authorized")
    store_cte = (
        select(Store)
        .where(Store.id == store_id)
        .where(
            or_(
                exists().where(
                    store_owners.c.users_id == user_id,
                    store_owners.c.stores_id == store_id,
                ),
                exists().where(
                    store_staffs.c.users_id == user_id,
                    store_staffs.c.stores_id == store_id,
                ),
            )
        )
    ).cte("portal_access")
    membership_stmt = (
        select(Membership)
        .join(store_cte, Membership.store_id == store_cte.c.id)
        .where(Membership.id == membership_id)
    )
    restore = (await db.execute(membership_stmt)).scalar_one_or_none()
    if not restore:
        logger.warning(
            f"user: {user_id},entered invalid credentials at the restore_membership endpoint"
        )
        raise HTTPException(status_code=404, detail="no member to restore")
    if not restore.is_deleted:
        return {"message": "membership is not deleted"}
    restore.is_deleted = False
    try:
        await db.commit()
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
    logger.info("membership restored for membership_id: %s", membership_id)
    await member_global_invalidation()
    return {"message": "membership restored"}


async def delete_member(store_id, membership_id, db, payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("unauthorized attempt to access delete_member endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    store_cte = (
        select(Store)
        .join(Membership, Store.id == Membership.store_id)
        .where(Store.id == store_id)
        .where(
            or_(
                exists().where(Membership.user_id == user_id),
                exists().where(
                    store_owners.c.users_id == user_id,
                    store_owners.c.stores_id == store_id,
                ),
                exists().where(
                    store_staffs.c.users_id == user_id,
                    store_staffs.c.stores_id == store_id,
                ),
            )
        )
    ).cte("portal_access")
    membership_stmt = (
        select(Membership)
        .join(store_cte, Membership.store_id == store_cte.c.id)
        .where(Membership.id == membership_id)
    )
    member = (await db.execute(membership_stmt)).scalar_one_or_none()
    if not member:
        logger.warning(
            f"user: {user_id}, entered invalid credentials at delete_member endpoint"
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
    await member_global_invalidation()
    return {"message": "membership deleted"}
