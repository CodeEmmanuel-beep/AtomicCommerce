from fastapi import Request
from app.logs.logger import get_logger
from app.database.config import settings

logger = get_logger("supabase_urls")


def _supabase(request: Request):
    return request.app.state.supabase


def get_public_url(filename: str | None):
    if not filename:
        return None
    return (
        f"{settings.SUPABASE_URL}/storage/v1/object/public/{settings.BUCKET}/{filename}"
    )


def batch_get_urls(filenames: list[str] | None):
    if not filenames:
        return {}
    return {get_public_url(f) for f in filenames}


async def cleaned_up(get_supabase, file, context_1="str", context_2="str"):
    try:
        if isinstance(file, str):
            file = [file]
        logger.info("attempting cleanup for files: %s", file)
        response = await get_supabase.storage.from_(settings.BUCKET).remove(file)
        logger.info("supabase delete response: %s", response)
        if response:
            logger.info("%s %s", context_2, file)
        else:
            logger.error("%s %s", context_1, file)
    except Exception:
        logger.exception("CRITICAL STORAGE ERROR")
