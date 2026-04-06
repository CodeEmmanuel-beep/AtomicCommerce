from app.models import React, Review, Reply, ReactionType
from app.logs.logger import get_logger
from fastapi import HTTPException, status
from datetime import timezone, datetime
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

logger = get_logger("react")


async def react_type(
    reaction_type,
    reply_id,
    review_id,
    db,
    payload,
):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Unauthorized reaction attempt")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    try:
        reaction_enum = ReactionType(reaction_type)
    except ValueError:
        logger.warning(f"Invalid reaction type '{reaction_type}' by user {user_id}")
        raise HTTPException(status_code=400, detail="invalid reaction type")
    if (reply_id is None and review_id is None) or (
        reply_id is not None and review_id is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="must reaction to either review or reply",
        )
    if review_id:
        target = await db.get(Review, review_id)
        if not target:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="must react on an existing review",
            )
    if reply_id:
        target = await db.get(Reply, reply_id)
        if not target:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="must react on an existing reply",
            )
    prefix = "product" if target.product else "store"
    suffix = (
        "review_reaction_count"
        if isinstance(target, Review)
        else "reply_reaction_count"
    )
    field_name = f"{prefix}_{suffix}"
    if review_id:
        stmt = select(React).where(
            React.user_id == user_id, React.review_id == review_id
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            if existing.type == reaction_enum:
                existing_id = existing.id
                try:
                    await db.delete(existing)
                    await db.flush()
                    value = getattr(target, field_name) or 0
                    setattr(target, field_name, max(value - 1, 0))
                    db.add(target)
                    await db.commit()
                except IntegrityError:
                    await db.rollback()
                    logger.error(
                        f"User {user_id} failed to remove reaction {existing_id}"
                    )
                    raise HTTPException(status_code=400, detail="database error")
                except Exception:
                    await db.rollback()
                    logger.exception(
                        f"User {user_id} failed to remove reaction {existing_id}"
                    )
                    raise HTTPException(status_code=500, detail="internal server error")
                logger.info(f"User {user_id} removed reaction {existing_id}")
                return {"message": "Reaction removed", "reaction": existing.type}
            existing.type = reaction_enum
            existing.time_of_reaction = datetime.now(timezone.utc)
            try:
                await db.commit()
                await db.refresh(existing)
            except IntegrityError:
                await db.rollback()
                logger.error(f"User {user_id} failed to update reaction {existing.id}")
                raise HTTPException(status_code=400, detail="database error")
            except Exception:
                await db.rollback()
                logger.exception(
                    f"User {user_id} failed to update reaction {existing.id}"
                )
                raise HTTPException(status_code=500, detail="internal server error")
            logger.info(f"User {user_id} updated reaction {existing.id}")
            return {"message": "Reaction updated", "reaction": existing.type}
    if reply_id:
        stmt = select(React).where(React.user_id == user_id, React.reply_id == reply_id)
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            if existing.type == reaction_enum:
                existing_id = existing.id
                try:
                    await db.delete(existing)
                    await db.flush()
                    value = getattr(target, field_name) or 0
                    setattr(target, field_name, max(value - 1, 0))
                    db.add(target)
                    await db.commit()
                except IntegrityError:
                    await db.rollback()
                    logger.error(
                        f"User {user_id} failed to remove reaction {existing_id}"
                    )
                    raise HTTPException(status_code=400, detail="database error")
                except Exception:
                    await db.rollback()
                    logger.exception(
                        f"User {user_id} failed to remove reaction {existing_id}"
                    )
                    raise HTTPException(status_code=500, detail="internal server error")
                logger.info(f"User {user_id} removed reaction {existing_id}")
                return {"message": "Reaction removed", "reaction": existing.type}
            existing.type = reaction_enum
            existing.time_of_reaction = datetime.now(timezone.utc)
            try:
                await db.commit()
                await db.refresh(existing)
            except IntegrityError:
                await db.rollback()
                logger.error(f"User {user_id} failed to update reaction {existing.id}")
                raise HTTPException(status_code=500, detail="Database Error")
            except Exception:
                await db.rollback()
                logger.exception(
                    f"User {user_id} failed to update reaction {existing.id}"
                )
                raise HTTPException(status_code=500, detail="internal server error")
            logger.info(f"User {user_id} updated reaction {existing.id}")
            return {"message": "Reaction updated", "reaction": existing.type}
    new_react = React(
        user_id=user_id,
        type=reaction_enum,
        reply_id=reply_id,
        review_id=review_id,
        time_of_reaction=datetime.now(timezone.utc),
    )
    try:
        db.add(new_react)
        value = getattr(target, field_name) or 0
        setattr(target, field_name, value + 1)
        db.add(target)
        await db.commit()
        await db.refresh(new_react)
    except IntegrityError:
        await db.rollback()
        logger.error(f"User {user_id} failed to add new reaction")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(f"User {user_id} failed to add new reaction")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"User {user_id} added new reaction {new_react.id}")
    return {"message": "Reaction added", "reaction": new_react.type}
