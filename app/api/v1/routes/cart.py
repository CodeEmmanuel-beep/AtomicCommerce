from app.api.v1.models import (
    CartItems,
    CartResponse,
    PaginatedMetadata,
    StandardResponse,
)
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.services import cart_service
from app.auth.verify_jwt import verify_token
from app.database.get import get_db


router = APIRouter(prefix="/shopping", tags=["Cart"])


@router.post("/cart")
async def create_cart(
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await cart_service.create_cart(db=db, payload=payload)


@router.post("/cart_items")
async def shopping(
    cart: CartItems,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await cart_service.shopping(cart=cart, db=db, payload=payload)


@router.get(
    "/get_carts",
    response_model=StandardResponse[PaginatedMetadata[CartResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def retrieve_all(
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await cart_service.retrieve_all(
        db=db, payload=payload, page=page, limit=limit
    )


@router.get(
    "/get_cart",
    response_model=StandardResponse,
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def retrieve(
    cart_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await cart_service.retrieve_cart(
        cart_id=cart_id, db=db, payload=payload, page=page, limit=limit
    )


@router.put("/edit_quantity")
async def change_quanity(
    cart_id: int,
    cartitem_id: int,
    new_quntity,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await cart_service.edit_quantity(
        cart_id=cart_id,
        cartitem_id=cartitem_id,
        new_quantity=new_quntity,
        db=db,
        payload=payload,
    )


@router.delete("/delete_cartitem")
async def delete_one(
    cart_id: int,
    cartitem_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await cart_service.delete_one(
        cart_id=cart_id, cartitem_id=cartitem_id, db=db, payload=payload
    )


@router.delete("/delete_cart")
async def delete_all(
    cart_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await cart_service.delete(cart_id=cart_id, db=db, payload=payload)
