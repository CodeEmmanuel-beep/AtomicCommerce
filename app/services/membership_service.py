from app.logs.logger import get_logger
from fastapi import HTTPException, Response, status
from app.models import (
    Membership,
    Store,
    store_owners,
    store_staffs,
    Subscription,
    SubscriptionStatus,
    SubscriptionPlan,
)
from sqlalchemy.exc import IntegrityError
from app.api.v1.schemas import (
    MembershipResponse,
    StandardResponse,
    SubscriptionResponse,
    MembershipRes,
    PaginatedMetadata,
    CursorPaginatedResponse,
)
from datetime import datetime, timezone
from sqlalchemy import select, or_, exists
from sqlalchemy.orm import selectinload, contains_eager
from app.utils.redis import (
    cache,
    cache_version,
    cached,
    member_global_invalidation,
)
from app.utils.helper import store_auth, unique_id
from app.database.config import settings

logger = get_logger("membership")


async def make_member(
    store_id, background_task, membership_type, activation_type, db, request
):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized user tried to access make_member endpoint")
        raise HTTPException(
            status_code=401, detail="you need to register to apply for membership"
        )
    store_exists = (
        await db.execute(
            select(exists().where(Store.id == store_id, Store.is_deleted.is_(False)))
        )
    ).scalar()
    if not store_exists:
        logger.warning(
            "user: %s, tried being a member of a non existent store", user_id
        )
        raise HTTPException(status_code=404, detail="store not found")
    existing = (
        await db.execute(
            select(Membership).where(
                Membership.user_id == user_id, Membership.store_id == store_id
            )
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
    try:
        member = Membership(
            user_id=user_id,
            store_id=store_id,
            membership_type=membership_type,
        )
        db.add(member)
        await db.flush()
        logger.info("successfully added member: %s, to store: %s", member.id, store_id)
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
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        logger.error(
            f"database error occured while adding user:'{user_id}' as a member {e}"
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(f"error occured while adding user:'{user_id}' as a member")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(
        f"member crerated with user_id: '{user_id}' and membership_type: '{membership_type}'"
    )
    background_task.add_task(member_global_invalidation, store_id)
    return StandardResponse(status="success", message="membership created", data=None)


async def update(
    store_id, membership_type, background_task, activation_type, db, request
):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized user tried to assess make_member endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    try:
        stmt = (
            select(Membership, Subscription)
            .outerjoin(Subscription, Membership.id == Subscription.membership_id)
            .where(
                Membership.user_id == user_id,
                Membership.store_id == store_id,
                Membership.is_deleted.is_(False),
            )
            .with_for_update(of=Membership)
        )
        row = (await db.execute(stmt)).fetchone()
        member, subscribe = row or (None, None)
        price_map = None
        plan_map = None
        if not member:
            logger.warning(
                f"user: {user_id} tried updating their membership without being a member"
            )
            raise HTTPException(
                status_code=404,
                detail="not a member, contact support if you think this is a mistake",
            )
        if not subscribe:
            subscribe = Subscription(
                membership_id=member.id, status=SubscriptionStatus.inactive
            )
            db.add(subscribe)
        if subscribe.status != SubscriptionStatus.inactive:
            logger.info("existing subscription found for user: %s", user_id)
            return StandardResponse(
                status="success",
                message="existing subscription found. Use the 'Update Plan' portal to manage it.",
                data=None,
            )
        if activation_type == "one_time":
            price_map = {
                "Standard": settings.Standard_Price,
                "Regular": settings.Regular_Price,
                "Premium": settings.Premium_Price,
            }
            target_price = price_map[membership_type]
            target_plan = None
        if activation_type == "subscription":
            plan_map = {
                "Standard": settings.Standard,
                "Regular": settings.Regular,
                "Premium": settings.Premium,
            }
            target_plan = plan_map[membership_type]
            target_price = None
        same_type = subscribe.plan_name == membership_type
        same_price = subscribe.price_id == target_plan
        same_plan = subscribe.plan_price == target_price
        if same_type and same_price and same_plan:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        member.membership_type = SubscriptionPlan[membership_type]
        subscribe.plan_name = membership_type
        subscribe.price_id = target_plan
        subscribe.plan_price = target_price
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
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
    background_task.add_task(member_global_invalidation, store_id)
    return StandardResponse(
        status="success", message="membership type updated", data=None
    )


async def view_membership(store_id, db, request):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized attempt to access view_member endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    version = await cache_version(f"store_member_key:{store_id}")
    cache_key = f"membership:v{version}:{user_id}:{store_id}"
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
            Membership.is_deleted.is_(False),
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


async def view_subscription(member_id, db, request):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized attempt to access view_subscription endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    cache_key = f"subscription:{member_id}:{user_id}"
    cached_member = await cache(cache_key)
    if cached_member:
        logger.info("cached hit at view_subscription endpoint user %s", user_id)
        return StandardResponse(**cached_member)
    stmt = (
        select(Subscription)
        .join(Membership, Membership.id == Subscription.membership_id)
        .options(contains_eager(Subscription.membership))
        .where(
            Membership.user_id == user_id,
            Subscription.membership_id == member_id,
            Membership.is_deleted.is_(False),
        )
    )
    subscription = (await db.execute(stmt)).scalar_one_or_none()
    if not subscription:
        logger.warning(
            "query attempt at view_subscription endpoint returned null, user %s",
            user_id,
        )
        raise HTTPException(status_code=404, detail="subscription not found")
    subscription_data = SubscriptionResponse.model_validate(subscription)
    full_response = StandardResponse(
        status="success", message="subscription information", data=subscription_data
    )
    await cached(cache_key, full_response, ttl=300)
    logger.info("subscription data cached successfully")
    return full_response


async def view_member_subscription(store_id, member_id, db, request):
    user_id = await store_auth(request=request, store_id=store_id, db=db)
    if not user_id:
        logger.warning(
            "Unauthorized or forbidden access attempt to view_subscription endpoint"
        )
        raise HTTPException(status_code=403, detail="Access denied for this store")
    version = await cache_version(f"store_subscriptions:{store_id}")
    cache_key = f"subscription:v{version}:{member_id}:{user_id}"
    cached_member = await cache(cache_key)
    if cached_member:
        logger.info("cached hit at view_subscription endpoint user %s", user_id)
        return StandardResponse(**cached_member)
    stmt = (
        select(Subscription)
        .join(Membership, Membership.id == Subscription.membership_id)
        .options(contains_eager(Subscription.membership))
        .where(
            Membership.store_id == store_id,
            Subscription.membership_id == member_id,
            Membership.is_deleted.is_(False),
        )
    )
    subscription = (await db.execute(stmt)).scalar_one_or_none()
    if not subscription:
        logger.warning(
            "query attempt at view_subscription endpoint returned null, user %s",
            user_id,
        )
        raise HTTPException(status_code=404, detail="subscription not found")
    subscription_data = SubscriptionResponse.model_validate(subscription)
    full_response = StandardResponse(
        status="success", message="subscription information", data=subscription_data
    )
    await cached(cache_key, full_response, ttl=60)
    logger.info("subscription data cached successfully")
    return full_response


async def view_members_subscriptions(cursor_id, store_id, db, limit, request):
    user_id = await store_auth(store_id=store_id, db=db, request=request)
    if not user_id:
        logger.warning("unauthorized attempt to access view_subscription endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    version = await cache_version(f"store_subscriptions:{store_id}")
    cache_key = f"subscription:v{version}:{user_id}:{store_id}:{cursor_id}:{limit}"
    cached_member = await cache(cache_key)
    if cached_member:
        logger.info("cached hit at view_subscription endpoint user %s", user_id)
        return StandardResponse(**cached_member)
    stmt = (
        select(Subscription)
        .join(Membership, Membership.id == Subscription.membership_id)
        .options(contains_eager(Subscription.membership))
        .where(
            Membership.store_id == store_id,
            Membership.is_deleted.is_(False),
        )
        .order_by(Subscription.id.asc())
    )
    if cursor_id is not None:
        stmt = stmt.where(Subscription.id > cursor_id)
    subscription = (await db.execute(stmt.limit(limit + 1))).scalars().all()
    has_more = len(subscription) > limit
    if has_more:
        subscription = subscription[:limit]
    next_cursor = subscription[-1].id if subscription else None
    subscription_data = PaginatedMetadata[SubscriptionResponse](
        items=[SubscriptionResponse.model_validate(sub) for sub in subscription],
        cursor_pagination=CursorPaginatedResponse(
            next_cursor=next_cursor, limit=limit, has_more=has_more
        ),
    )
    full_response = StandardResponse(
        status="success", message="subscription information", data=subscription_data
    )
    await cached(cache_key, full_response, ttl=300)
    logger.info("subscription data cached successfully")
    return full_response


async def view_memberships(db, request):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized attempt to access view_member endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    cache_key = f"membership:{user_id}:v"
    cached_member = await cache(cache_key)
    if cached_member:
        logger.info("cached hit at view_member endpoint user %s", user_id)
        return StandardResponse(**cached_member)
    stmt = (
        select(Membership)
        .options(selectinload(Membership.store))
        .where(
            Membership.user_id == user_id,
            Membership.is_deleted.is_(False),
        )
    )
    members = (await db.execute(stmt)).scalars().all()
    if not members:
        logger.warning(
            "unauthorized attempt at view_member endpoint, user %s , is not a member of any store",
            user_id,
        )
        raise HTTPException(status_code=404, detail="not a member of any store")
    store_map = [
        {
            "id": i + 1,
            "store name": mem.store.store_name,
            "membership_type": mem.membership_type,
        }
        for i, mem in enumerate(members)
    ]
    full_response = StandardResponse(
        status="success",
        message="stores where you are a member",
        data=store_map,
    )
    await cached(cache_key, full_response, ttl=360)
    logger.info("Cached %s memberships for user %s", len(members), user_id)
    return full_response


async def view_selected_members(store_id, member_status, cursor_id, limit, db, request):
    if member_status not in [
        "active_members",
        "inactive_members",
        "deleted_members",
    ]:
        raise HTTPException(
            status_code=400,
            detail="member_status should be either 'active_members','inactive_members', or 'deleted_members'",
        )
    user_id = await store_auth(store_id, db, request)
    version = await cache_version(f"store_member_key:{store_id}")
    cache_key = f"membership:v{version}:{member_status}:{store_id}:{cursor_id}:{limit}"
    cached_member = await cache(cache_key)
    if cached_member:
        logger.info("cached hit at view_selected_members endpoint user %s", user_id)
        return StandardResponse(**cached_member)
    base_filter = {
        "active_members": (
            Membership.is_active.is_(True),
            Membership.is_deleted.is_(False),
        ),
        "inactive_members": (
            Membership.is_active.is_(False),
            Membership.is_deleted.is_(False),
        ),
        "deleted_members": (
            Membership.is_active.is_(False),
            Membership.is_deleted.is_(True),
        ),
    }[member_status]
    store_membership = (
        select(Membership)
        .options(selectinload(Membership.user))
        .where(Membership.store_id == store_id, *base_filter)
        .order_by(Membership.id.asc())
    )
    if cursor_id is not None:
        store_membership = store_membership.where(Membership.id > cursor_id)
    member = (await db.execute(store_membership.limit(limit + 1))).scalars().all()
    has_more = len(member) > limit
    if has_more:
        member = member[:limit]
    next_cursor = member[-1].id if member else None
    data = PaginatedMetadata[MembershipRes](
        items=[MembershipRes.model_validate(mem) for mem in member],
        cursor_pagination=CursorPaginatedResponse(
            next_cursor=next_cursor, limit=limit, has_more=has_more
        ),
    )
    response = StandardResponse(status="success", message=f"{member_status}", data=data)
    await cached(cache_key, response, ttl=18000)
    logger.info("%s data cached successfully for admin: %s", member_status, user_id)
    return response


async def restore_membership(store_id, membership_id, db, request):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized attempt to access restore_membership endpoint")
        raise HTTPException(status_code=401, detail="not authorized")
    try:
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
            .with_for_update(of=Membership)
        )
        restore = (await db.execute(membership_stmt)).scalar_one_or_none()
        if not restore:
            logger.warning(
                f"user: {user_id},entered invalid credentials at the restore_membership endpoint"
            )
            raise HTTPException(status_code=404, detail="no member to restore")
        if not restore.is_deleted:
            return StandardResponse(
                status="success", message="membership is not deleted", data=None
            )
        restore.is_deleted = False
        restore.reactivation_date = datetime.now(timezone.utc)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
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
    await member_global_invalidation(store_id)
    return StandardResponse(status="success", message="membership restored", data=None)


async def delete_member(store_id, membership_id, background_task, db, request):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized attempt to access delete_member endpoint")
        raise HTTPException(status_code=401, detail="not a registered user")
    if membership_id:
        await store_auth(store_id, db, request)
        base_filter = Membership.id == membership_id
    else:
        base_filter = Membership.user_id == user_id
        target_user = user_id
    try:
        membership_stmt = (
            select(Membership)
            .where(Membership.store_id == store_id)
            .where(base_filter)
            .with_for_update()
        )
        member = (await db.execute(membership_stmt)).scalar_one_or_none()
        if not member:
            logger.warning(
                f"user: {user_id}, entered invalid credentials at delete_member endpoint"
            )
            raise HTTPException(status_code=404, detail="not a member")
        if member.is_deleted:
            return StandardResponse(
                status="success", message="membership is already deleted", data=None
            )
        member.is_deleted = True
        member.is_active = False
        member.delete_date = datetime.now(timezone.utc)
        if membership_id:
            target_user = member.user_id
        target_member = member.id
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error(
            "database error occured while deleting membership user affected: %s",
            target_user,
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            "error occured while deleting membership user affected: %s", target_user
        )
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info("membership: %s deleted", target_member)
    background_task.add_task(member_global_invalidation, store_id)
    return StandardResponse(status="success", message="membership deleted", data=None)
