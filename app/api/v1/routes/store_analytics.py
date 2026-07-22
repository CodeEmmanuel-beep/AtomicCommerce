from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db
from app.auth.verify_jwt import verify_token
from app.api.v1.schemas import StandardResponse
from fastapi import Depends, APIRouter, Query
from app.services import store_analytics_service

router = APIRouter(prefix="/store_analytics", tags=["Store_Analytics"])


@router.get(
    "/store_public_dashboard/{slug}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def store_dashboard(slug: str, db: AsyncSession = Depends(get_db)):
    return await store_analytics_service.view_store_data(slug=slug, db=db)


@router.get(
    "/store_entire_performance/{slug}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def view_store_entire_performance(
    slug: str, db: AsyncSession = Depends(get_db), payload: dict = Depends(verify_token)
):
    return await store_analytics_service.view_overall_performance(
        slug=slug, db=db, payload=payload
    )


@router.get(
    "/store_performance_in_current_month/{slug}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def view_store_monthly_performance(
    slug: str, db: AsyncSession = Depends(get_db), payload: dict = Depends(verify_token)
):
    return await store_analytics_service.view_current_performance(
        slug=slug, db=db, payload=payload
    )


@router.get(
    "/select_product_statistics",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def product_statistics(
    slug: str,
    product_id: int,
    statistics: str = Query("product_sales", enum=["product_ratings", "product_sales"]),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_analytics_service.select_products_stats(
        slug=slug, product_id=product_id, stats=statistics, db=db, payload=payload
    )


@router.get(
    "/product_statistics",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def get_products_statistics(
    slug: str,
    ranking: str = Query("top_product", enum=["least_product", "top_product"]),
    time_frame: str = Query(
        "1 week", enum=["1 month", "3 months", "6 months", "1 year", "total", "1 week"]
    ),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_analytics_service.products_stats(
        slug=slug, ranking=ranking, time_frame=time_frame, db=db, payload=payload
    )


@router.get(
    "/inventory_statistics",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def get_inventory_statistics(
    slug: str,
    stock_range: str = Query(
        "ten_below",
        enum=[
            "thirty_below",
            "five_below",
            "twenty_below",
            "fifty_below",
            "out_of_stock",
            "above_fifty",
            "ten_below",
        ],
    ),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await store_analytics_service.inventory_stats(
        slug=slug, stock_range=stock_range, db=db, payload=payload
    )
