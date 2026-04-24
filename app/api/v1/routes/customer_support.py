from fastapi import Depends, APIRouter, File, UploadFile, Query
from app.services import customer_support_service
from app.api.v1.schemas import Chat, StandardResponse, PaginatedMetadata
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db
from app.auth.verify_jwt import verify_token
from app.utils.supabase_url import _supabase

router = APIRouter(prefix="/customer_service", tags=["Customer Service"])


@router.post("/message_support")
async def send_message(
    subject: str,
    message: str,
    picure: UploadFile = File(None),
    store_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
    get_supabase=Depends(_supabase),
):
    return await customer_support_service.text_support(
        subject=subject,
        message=message,
        pics=picure,
        store_id=store_id,
        db=db,
        payload=payload,
        get_supabase=get_supabase,
    )


@router.post("/customer_support_thread")
async def customer_support_chat(
    ticket_id: int,
    message: str,
    photo: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
    get_supabase=Depends(_supabase),
):
    return await customer_support_service.ticket_thread(
        ticket_id=ticket_id,
        message=message,
        pics=photo,
        db=db,
        payload=payload,
        get_supabase=get_supabase,
    )


@router.get(
    "/view_ticket_messages",
    response_model=StandardResponse[PaginatedMetadata[Chat]],
    response_model_exclude_defaults=True,
    response_model_exclude_none=True,
)
async def get_ticket_messages(
    ticket_id: int,
    view: str = Query("customer_view", enum=["support_view", "customer_view"]),
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await customer_support_service.customer_support_messages(
        ticket_id=ticket_id, view=view, page=page, limit=limit, db=db, payload=payload
    )


@router.get(
    "/view_tickets_conversations",
    response_model=StandardResponse[PaginatedMetadata[Chat]],
    response_model_exclude_defaults=True,
    response_model_exclude_none=True,
)
async def get_tickets_conversations(
    views: str = Query("customer_view", enum=["support_view", "customer_view"]),
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await customer_support_service.customer_support_conversations(
        views=views, page=page, limit=limit, db=db, payload=payload
    )


@router.put("/customer_resolve_ticket")
async def customer_close_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await customer_support_service.mark_as_resolved(
        ticket_id=ticket_id, db=db, payload=payload
    )


@router.put("/support_resolve_ticket")
async def support_close_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await customer_support_service.close_ticket(
        ticket_id=ticket_id, db=db, payload=payload
    )


@router.delete("/delete_message")
async def delete_one_message(
    ticket_id: int,
    message_id: int,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await customer_support_service.remove_message(
        ticket_id=ticket_id, message_id=message_id, db=db, payload=payload
    )


@router.delete("/delete_conversation")
async def delete_one_conversation(
    ticket_id: int,
    agent: str = Query("customer_view", enum=["support_view", "customer_view"]),
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(verify_token),
):
    return await customer_support_service.clear_conversation(
        ticket_id=ticket_id, agent=agent, db=db, payload=payload
    )
