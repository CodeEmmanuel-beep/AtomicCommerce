from fastapi import APIRouter, BackgroundTasks, Depends, Query
from app.database.get import get_db
from app.services import delivery_address_service
from app.api.v1.schemas import (
    AddressDetails,
    AddressResponse,
    PaginatedMetadata,
    StandardResponse,
)
from app.auth.verify_jwt import verify_token
from sqlalchemy.ext.asyncio import AsyncSession


router = APIRouter(prefix="/delivery_address", tags=["Delivery Address"])


@router.post("/add_delivery_address")
async def create_address(
    store_id: int,
    order_id: int,
    delivery_address: AddressDetails,
    background_task: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await delivery_address_service.delivery_address(
        store_id=store_id,
        order_id=order_id,
        delivery_address=delivery_address,
        background_task=background_task,
        db=db,
        payload=payload,
    )


@router.get(
    "/delivery_address_list/{store_id}",
    response_model=StandardResponse[PaginatedMetadata[AddressResponse]],
    response_model_exclude_defaults=True,
    response_model_exclude_none=True,
)
async def get_delivery_address(
    store_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await delivery_address_service.view_delivery_address(
        store_id=store_id, page=page, limit=limit, db=db, payload=payload
    )


@router.put("/select_delivery_address/{store_id}/{order_id}")
async def pick_delivery_address(
    store_id: int,
    order_id: int,
    address_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await delivery_address_service.choose_order_address(
        store_id=store_id,
        order_id=order_id,
        address_id=address_id,
        db=db,
        payload=payload,
    )


@router.delete("/delete_delivery_address/{store_id}/{address_id}")
async def delete_address(
    store_id: int,
    address_id: int,
    background_task: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await delivery_address_service.remove_delivery_address(
        store_id=store_id,
        address_id=address_id,
        background_task=background_task,
        db=db,
        payload=payload,
    )
