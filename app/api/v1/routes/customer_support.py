from fastapi import Depends, APIRouter, File, UploadFile, Query, Request
from app.services import customer_support_service
from app.api.v1.schemas import StandardResponse, SupportCustomerEnum
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db
from supabase import AsyncClient
from app.utils.supabase_url import _supabase
from typing import Annotated

router = APIRouter(prefix="/customer_service", tags=["Customer Service"])

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]

SupabaseDep = Annotated[AsyncClient, Depends(_supabase)]


@router.post(
    "/message_support",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def send_message(
    subject: str,
    request: Request,
    db: DatabaseDep,
    get_supabase: SupabaseDep,
    store_id: int | None = None,
    message: str | None = None,
    picture: UploadFile = File(None),
):
    return await customer_support_service.text_support(
        subject=subject,
        request=request,
        message=message,
        pics=picture,
        store_id=store_id,
        db=db,
        get_supabase=get_supabase,
    )


@router.post(
    "/customer_support_thread",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def customer_support_chat(
    ticket_id: int,
    request: Request,
    db: DatabaseDep,
    get_supabase: SupabaseDep,
    store_id: int | None = None,
    message: str | None = None,
    photo: UploadFile = File(None),
):
    return await customer_support_service.ticket_thread(
        ticket_id=ticket_id,
        store_id=store_id,
        request=request,
        message=message,
        pics=photo,
        db=db,
        get_supabase=get_supabase,
    )


@router.get(
    "/view_ticket_messages",
    response_model=StandardResponse,
    response_model_exclude_defaults=True,
    response_model_exclude_none=True,
)
async def get_ticket_messages(
    ticket_id: int,
    request: Request,
    db: DatabaseDep,
    get_supabase: SupabaseDep,
    store_id: int | None = None,
    view: SupportCustomerEnum = Query(SupportCustomerEnum.customer_view),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await customer_support_service.customer_support_messages(
        store_id=store_id,
        ticket_id=ticket_id,
        request=request,
        view=view.value,
        page=page,
        limit=limit,
        db=db,
        get_supabase=get_supabase,
    )


@router.get(
    "/view_tickets_conversations",
    response_model=StandardResponse,
    response_model_exclude_defaults=True,
    response_model_exclude_none=True,
)
async def get_tickets_conversations(
    request: Request,
    db: DatabaseDep,
    get_supabase: SupabaseDep,
    store_id: int | None = None,
    views: SupportCustomerEnum = Query(SupportCustomerEnum.customer_view),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await customer_support_service.customer_support_conversations(
        views=views.value,
        page=page,
        store_id=store_id,
        request=request,
        limit=limit,
        db=db,
        get_supabase=get_supabase,
    )


@router.put(
    "/customer_resolve_ticket",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def customer_close_ticket(
    ticket_id: int, request: Request, db: DatabaseDep, store_id: int | None = None
):
    return await customer_support_service.mark_as_resolved(
        store_id=store_id, request=request, ticket_id=ticket_id, db=db
    )


@router.put(
    "/support_resolve_ticket",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def support_close_ticket(
    ticket_id: int, request: Request, db: DatabaseDep, store_id: int | None = None
):
    return await customer_support_service.close_ticket(
        store_id=store_id, request=request, ticket_id=ticket_id, db=db
    )


@router.delete(
    "/delete_message",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_one_message(
    ticket_id: int,
    message_id: int,
    request: Request,
    db: DatabaseDep,
    store_id: int | None = None,
):
    return await customer_support_service.remove_message(
        store_id=store_id,
        ticket_id=ticket_id,
        request=request,
        message_id=message_id,
        db=db,
    )


@router.delete(
    "/delete_conversation",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_one_conversation(
    ticket_id: int,
    request: Request,
    db: DatabaseDep,
    store_id: int | None = None,
    agent: SupportCustomerEnum = Query(SupportCustomerEnum.customer_view),
):
    return await customer_support_service.clear_conversation(
        store_id=store_id,
        request=request,
        ticket_id=ticket_id,
        agent=agent.value,
        db=db,
    )
