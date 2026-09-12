from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db
from app.api.v1.schemas import (
    StandardResponse,
    TimeFrameEnum,
    RankingEnum,
    ProductStatisticsEnum,
    StockRangeEnum,
)
from typing import Annotated
from fastapi import Request, APIRouter, Query, Depends
from app.services import store_analytics_service

router = APIRouter(prefix="/store_analytics", tags=["Store_Analytics"])

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]


@router.get(
    "/store_public_dashboard/{slug}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def store_dashboard(slug: str, db: DatabaseDep):
    return await store_analytics_service.view_store_data(slug=slug, db=db)


@router.get(
    "/store_entire_performance/{slug}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def view_store_entire_performance(request: Request, slug: str, db: DatabaseDep):
    return await store_analytics_service.view_overall_performance(
        slug=slug, db=db, request=request
    )


@router.get(
    "/store_performance_in_current_month/{slug}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def view_store_monthly_performance(request: Request, slug: str, db: DatabaseDep):
    return await store_analytics_service.view_current_performance(
        slug=slug, db=db, request=request
    )


@router.get(
    "/select_product_statistics",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def product_statistics(
    request: Request,
    slug: str,
    product_id: int,
    db: DatabaseDep,
    statistics: ProductStatisticsEnum = Query(ProductStatisticsEnum.product_sales),
):
    return await store_analytics_service.select_products_stats(
        slug=slug, product_id=product_id, stats=statistics.value, db=db, request=request
    )


@router.get(
    "/product_statistics",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def get_products_statistics(
    request: Request,
    slug: str,
    db: DatabaseDep,
    ranking: RankingEnum = Query(RankingEnum.top_product),
    time_frame: TimeFrameEnum = Query(TimeFrameEnum.one_week),
):
    return await store_analytics_service.products_stats(
        slug=slug,
        ranking=ranking.value,
        time_frame=time_frame.value,
        db=db,
        request=request,
    )


@router.get(
    "/inventory_statistics",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def get_inventory_statistics(
    request: Request,
    slug: str,
    db: DatabaseDep,
    stock_range: StockRangeEnum = Query(StockRangeEnum.ten_below),
):
    return await store_analytics_service.inventory_stats(
        slug=slug, stock_range=stock_range.value, db=db, request=request
    )
