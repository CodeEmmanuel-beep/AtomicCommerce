from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db
from app.auth.verify_jwt import verify_token
from fastapi import Depends, APIRouter
from app.services import store_analytics_service

router = APIRouter(prefix="/store_analytics", tags=["Store_Analytics"])


@router.get("/store_public_dashboard/{store_id}")
async def store_dashboard(slug: str, db: AsyncSession = Depends(get_db)):
    return await store_analytics_service.view_store_data(slug=slug, db=db)


@router.get("/store_extra_datails/{slug}")
async def view_store_extra_details(slug: str, db: AsyncSession = Depends(get_db)):
    return await store_analytics_service.view_store_details(slug=slug, db=db)


@router.get("/store_entire_performance/{slug}")
async def view_store_entire_performance(
    slug: str, db: AsyncSession = Depends(get_db), payload: dict = Depends(verify_token)
):
    return await store_analytics_service.view_overall_performance(
        slug=slug, db=db, payload=payload
    )


@router.get("/store_performance_in_current_month/{slug}")
async def view_store_monthly_performance(
    slug: str, db: AsyncSession = Depends(get_db), payload: dict = Depends(verify_token)
):
    return await store_analytics_service.view_current_performance(
        slug=slug, db=db, payload=payload
    )
