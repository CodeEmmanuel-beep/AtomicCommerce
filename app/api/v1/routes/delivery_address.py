from fastapi import APIRouter, BackgroundTasks, Request, Query, Depends
from app.database.get import get_db
from app.services import delivery_address_service
from app.api.v1.schemas import (
    AddressDetails,
    AddressResponse,
    PaginatedMetadata,
    StandardResponse,
)
from typing import Annotated
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/delivery_address", tags=["Delivery Address"])

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/add_delivery_address",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def create_address(
    store_id: int,
    order_id: int,
    request: Request,
    db: DatabaseDep,
    delivery_address: AddressDetails,
    background_task: BackgroundTasks,
):
    return await delivery_address_service.delivery_address(
        store_id=store_id,
        request=request,
        order_id=order_id,
        delivery_address=delivery_address,
        background_task=background_task,
        db=db,
    )


@router.get(
    "/delivery_address_list/{store_id}",
    response_model=StandardResponse[PaginatedMetadata[AddressResponse]],
    response_model_exclude_defaults=True,
    response_model_exclude_none=True,
)
async def get_delivery_address(
    store_id: int,
    request: Request,
    db: DatabaseDep,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await delivery_address_service.view_delivery_address(
        store_id=store_id, request=request, page=page, limit=limit, db=db
    )


@router.put(
    "/select_delivery_address/{store_id}/{order_id}/{address_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def pick_delivery_address(
    store_id: int,
    order_id: int,
    address_id: int,
    request: Request,
    background_task: BackgroundTasks,
    db: DatabaseDep,
):
    return await delivery_address_service.choose_order_address(
        store_id=store_id,
        order_id=order_id,
        address_id=address_id,
        request=request,
        db=db,
        background_task=background_task,
    )


@router.delete(
    "/delete_delivery_address/{store_id}/{address_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_address(
    store_id: int,
    address_id: int,
    request: Request,
    background_task: BackgroundTasks,
    db: DatabaseDep,
):
    return await delivery_address_service.remove_delivery_address(
        store_id=store_id,
        address_id=address_id,
        request=request,
        background_task=background_task,
        db=db,
    )
