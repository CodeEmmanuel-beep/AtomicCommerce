from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db
from app.services import inventory_service
from app.auth.verify_jwt import verify_token

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.post("/create_inventory")
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


@router.get("/get_inventory")
async def read_inventory(
    store_id: int,
    inventory_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await inventory_service.read(
        store_id=store_id, inventory_id=inventory_id, db=db, payload=payload
    )


@router.post("/update_inventory")
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


@router.delete("/delete_inventory")
async def delete_inventory(
    store_id: int,
    inventory_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await inventory_service.delete(
        store_id=store_id, inventory_id=inventory_id, db=db, payload=payload
    )
