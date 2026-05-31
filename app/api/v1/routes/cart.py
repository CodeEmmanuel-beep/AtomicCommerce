from app.api.v1.schemas import (
    StandardResponse,
)
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.services import cart_service
from app.auth.verify_jwt import verify_token
from app.database.get import get_db

router = APIRouter(prefix="/cart", tags=["Cart"])


@router.post("/add_to_cart")
async def add_cartitem(
    store_id: int,
    product_id: int,
    quantity: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await cart_service.add_item_to_cart(
        store_id=store_id,
        product_id=product_id,
        quantity=quantity,
        db=db,
        payload=payload,
    )


@router.get(
    "/fetch_cart",
    response_model=StandardResponse,
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def get_cart(
    store_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await cart_service.retrieve_cart(
        store_id=store_id,
        db=db,
        payload=payload,
        page=page,
        limit=limit,
    )


@router.put("/edit_quantity")
async def change_quanity(
    store_id: int,
    cart_id: int,
    cartitem_id: int,
    new_quntity: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await cart_service.edit_quantity(
        cart_id=cart_id,
        store_id=store_id,
        cartitem_id=cartitem_id,
        new_quantity=new_quntity,
        db=db,
        payload=payload,
    )


@router.put("/update_cart/{store_id}/{cart_id}")
async def update__cart(
    store_id: int,
    cart_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await cart_service.update_cart(
        cart_id=cart_id, store_id=store_id, db=db, payload=payload
    )


@router.delete("/delete_cartitem")
async def delete_one(
    store_id: int,
    cart_id: int,
    cartitem_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await cart_service.delete_one(
        cart_id=cart_id,
        store_id=store_id,
        cartitem_id=cartitem_id,
        db=db,
        payload=payload,
    )


@router.delete("/delete_cart/{store_id}/{cart_id}")
async def delete_cart(
    store_id: int,
    cart_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await cart_service.delete_all(
        cart_id=cart_id, store_id=store_id, db=db, payload=payload
    )
