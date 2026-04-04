from app.api.v1.models import (
    OrderResponse,
    PaginatedMetadata,
    StandardResponse,
)
from fastapi import APIRouter, Depends, Query, BackgroundTasks
from app.services import order_service
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.verify_jwt import verify_token
from app.database.get import get_db


router = APIRouter(prefix="/shopping", tags=["Order"])


@router.post("/orders")
async def create_orders(
    store_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await order_service.create_orders(store_id=store_id, db=db, payload=payload)


@router.post("/order_items")
async def create_orderitems(
    store_id: int,
    cart_id: int,
    order_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await order_service.create_order_items(
        store_id=store_id,
        cart_id=cart_id,
        order_id=order_id,
        background_tasks=background_tasks,
        db=db,
        payload=payload,
    )


@router.get(
    "/view_orders",
    response_model=StandardResponse[PaginatedMetadata[OrderResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_orders(
    store_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await order_service.view_orders(
        store_id=store_id, db=db, payload=payload, page=page, limit=limit
    )


@router.get(
    "/view_an_order",
    response_model=StandardResponse[PaginatedMetadata[OrderResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_order(
    store_id: int,
    order_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await order_service.view_order(
        store_id=store_id,
        order_id=order_id,
        db=db,
        payload=payload,
        page=page,
        limit=limit,
    )


@router.put("/cancel_order")
async def cancel(
    order_id: int,
    store_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await order_service.cancel_order(
        store_id=store_id, order_id=order_id, db=db, payload=payload
    )


@router.delete("/delete_order")
async def delete_order(
    order_id: int,
    store_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await order_service.delete_order(
        store_id=store_id, order_id=order_id, db=db, payload=payload
    )
