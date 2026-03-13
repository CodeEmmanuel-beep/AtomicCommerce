from app.database.async_config import AsyncSessionLocal


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
