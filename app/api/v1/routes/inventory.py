from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db
from app.api.v1.schemas import StandardResponse
from app.services import inventory_service
from app.auth.verify_jwt import verify_token

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.post(
    "/create_inventory",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def write_inventory(
    store_id: int,
    product_id: int,
    stock_quantity: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await inventory_service.create(
        store_id=store_id,
        product_id=product_id,
        stock_quantity=stock_quantity,
        db=db,
        payload=payload,
    )


@router.get(
    "/get_inventory", response_model=StandardResponse, response_model_exclude_none=True
)
async def read_inventory(
    store_id: int,
    inventory_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await inventory_service.read(
        store_id=store_id, inventory_id=inventory_id, db=db, payload=payload
    )


@router.get(
    "/store_inventory_list",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def read_store_inventory(
    store_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await inventory_service.read_all(
        store_id=store_id, page=page, limit=limit, db=db, payload=payload
    )


@router.put(
    "/update_inventory",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def edit_inventory(
    store_id: int,
    inventory_id: int,
    stock_quantity: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await inventory_service.update(
        store_id=store_id,
        inventory_id=inventory_id,
        stock_quantity=stock_quantity,
        db=db,
        payload=payload,
    )


@router.delete(
    "/delete_inventory",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_inventory(
    store_id: int,
    inventory_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await inventory_service.delete(
        store_id=store_id, inventory_id=inventory_id, db=db, payload=payload
    )
