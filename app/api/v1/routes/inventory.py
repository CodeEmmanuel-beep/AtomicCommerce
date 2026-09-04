from fastapi import APIRouter, Request, Query, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db
from app.api.v1.schemas import StandardResponse
from app.services import inventory_service
from typing import Annotated

router = APIRouter(prefix="/inventory", tags=["inventory"])

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/create_inventory",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def write_inventory(
    store_id: int,
    variant_id: int,
    request: Request,
    stock_quantity: int,
    background_tasks: BackgroundTasks,
    db: DatabaseDep,
):
    return await inventory_service.create(
        store_id=store_id,
        variant_id=variant_id,
        stock_quantity=stock_quantity,
        db=db,
        background_task=background_tasks,
        request=request,
    )


@router.get(
    "/get_inventory", response_model=StandardResponse, response_model_exclude_none=True
)
async def read_inventory(
    store_id: int,
    inventory_id: int,
    request: Request,
    db: DatabaseDep,
):
    return await inventory_service.read(
        store_id=store_id, inventory_id=inventory_id, db=db, request=request
    )


@router.get(
    "/product_inventory_list",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def read_product_inventory(
    store_id: int,
    product_id: int,
    request: Request,
    db: DatabaseDep,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await inventory_service.read_prod_inventory(
        store_id=store_id,
        product_id=product_id,
        page=page,
        limit=limit,
        db=db,
        request=request,
    )


@router.get(
    "/store_inventory_list",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def read_store_inventory(
    store_id: int,
    request: Request,
    db: DatabaseDep,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await inventory_service.read_all(
        store_id=store_id, page=page, limit=limit, db=db, request=request
    )


@router.put(
    "/update_inventory",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def edit_inventory(
    store_id: int,
    inventory_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    stock_quantity: int,
    db: DatabaseDep,
):
    return await inventory_service.update(
        store_id=store_id,
        inventory_id=inventory_id,
        stock_quantity=stock_quantity,
        db=db,
        background_task=background_tasks,
        request=request,
    )
