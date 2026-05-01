from sse_starlette.sse import EventSourceResponse
from fastapi import APIRouter, Depends
from app.auth.verify_jwt import verify_token
from app.utils.redis import notifications_stream

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/notice")
async def notification_message(payload: dict = Depends(verify_token)):
    user_id = payload.get("user_id")
    return EventSourceResponse(notifications_stream(user_id))
