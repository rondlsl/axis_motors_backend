from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.support_chat_model import SupportChatStatus
from app.services.support_service import SupportService
from app.schemas.support_schemas import (
    SupportChatCreate, SupportChatResponse, SupportMessageCreate,
    SupportMessageResponse, SupportChatWithMessages, SupportChatListResponse,
    SupportChatAssignRequest, SupportChatStatusUpdate, SupportStatsResponse
)

router = APIRouter(prefix="/api/support", tags=["Support"])


def get_support_service(db: Session = Depends(get_db)) -> SupportService:
    return SupportService(db)


def require_support_role(current_user: User = Depends(get_current_user)) -> User:
    """Проверка, что пользователь имеет роль SUPPORT или ADMIN"""
    if current_user.role not in [UserRole.SUPPORT, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Access denied. Support role required.")
    return current_user


def require_admin_role(current_user: User = Depends(get_current_user)) -> User:
    """Проверка, что пользователь имеет роль ADMIN"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied. Admin role required.")
    return current_user


@router.post("/chats", response_model=SupportChatResponse)
async def create_support_chat(
    chat_data: SupportChatCreate,
    support_service: SupportService = Depends(get_support_service)
):
    """Создать новый чат поддержки"""
    try:
        chat = support_service.create_chat(chat_data)
        return SupportChatResponse.from_orm(chat)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/chats", response_model=SupportChatListResponse)
async def get_support_chats(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    assigned_to: Optional[UUID] = Query(None),
    current_user: User = Depends(require_support_role),
    support_service: SupportService = Depends(get_support_service)
):
    """Получить список чатов поддержки"""
    
    # Если не админ, показываем только свои чаты
    if current_user.role == UserRole.SUPPORT:
        assigned_to = current_user.id
    
    chats, total = support_service.get_chats_for_support(
        support_user_id=assigned_to,
        status=status,
        page=page,
        per_page=per_page
    )
    
    return SupportChatListResponse(
        chats=[SupportChatResponse.from_orm(chat) for chat in chats],
        total=total,
        page=page,
        per_page=per_page
    )


@router.get("/chats/all", response_model=SupportChatListResponse)
async def get_all_support_chats(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    assigned_to: Optional[UUID] = Query(None),
    current_user: User = Depends(require_admin_role),
    support_service: SupportService = Depends(get_support_service)
):
    """Получить ВСЕ чаты поддержки (только для админов)"""
    
    chats, total = support_service.get_chats_for_support(
        support_user_id=assigned_to,
        status=status,
        page=page,
        per_page=per_page
    )
    
    return SupportChatListResponse(
        chats=[SupportChatResponse.from_orm(chat) for chat in chats],
        total=total,
        page=page,
        per_page=per_page
    )


@router.get("/chats/new", response_model=SupportChatListResponse)
async def get_new_support_chats(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_support_role),
    support_service: SupportService = Depends(get_support_service)
):
    """Получить только новые чаты (не назначенные)"""
    
    chats, total = support_service.get_chats_for_support(
        support_user_id=None,  # Не назначенные
        status=SupportChatStatus.NEW,
        page=page,
        per_page=per_page
    )
    
    return SupportChatListResponse(
        chats=[SupportChatResponse.from_orm(chat) for chat in chats],
        total=total,
        page=page,
        per_page=per_page
    )


@router.get("/chats/{chat_id}", response_model=SupportChatWithMessages)
async def get_support_chat(
    chat_id: UUID,
    current_user: User = Depends(require_support_role),
    support_service: SupportService = Depends(get_support_service)
):
    """Получить чат с сообщениями"""
    
    chat = support_service.get_chat_by_id(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # Проверяем права доступа
    if (current_user.role == UserRole.SUPPORT and 
        chat.assigned_to != current_user.id and 
        chat.status == SupportChatStatus.NEW):
        raise HTTPException(status_code=403, detail="Access denied")
    
    return SupportChatWithMessages.from_orm(chat)


@router.get("/chats/{chat_id}/messages", response_model=List[SupportMessageResponse])
async def get_chat_messages(
    chat_id: UUID,
    current_user: User = Depends(require_support_role),
    support_service: SupportService = Depends(get_support_service)
):
    """Получить сообщения конкретного чата"""
    
    chat = support_service.get_chat_by_id(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # Проверяем права доступа
    if (current_user.role == UserRole.SUPPORT and 
        chat.assigned_to != current_user.id and 
        chat.status == SupportChatStatus.NEW):
        raise HTTPException(status_code=403, detail="Access denied")
    
    messages = support_service.get_chat_messages(chat_id)
    return [SupportMessageResponse.from_orm(msg) for msg in messages]


@router.post("/chats/{chat_id}/take")
async def take_chat(
    chat_id: UUID,
    current_user: User = Depends(require_support_role),
    support_service: SupportService = Depends(get_support_service)
):
    """Взять чат в работу (назначить себе)"""
    
    success = support_service.assign_chat(chat_id, current_user.id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to take chat")
    
    return {"message": "Chat taken successfully"}


@router.post("/chats/{chat_id}/assign")
async def assign_chat(
    chat_id: UUID,
    assign_data: SupportChatAssignRequest,
    current_user: User = Depends(require_support_role),
    support_service: SupportService = Depends(get_support_service)
):
    """Назначить чат сотруднику поддержки"""
    
    # Только админы могут назначать чаты другим
    if (current_user.role == UserRole.SUPPORT and 
        assign_data.assigned_to != current_user.id):
        raise HTTPException(status_code=403, detail="Can only assign to yourself")
    
    success = support_service.assign_chat(chat_id, assign_data.assigned_to)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to assign chat")
    
    return {"message": "Chat assigned successfully"}


@router.put("/chats/{chat_id}/status")
async def update_chat_status(
    chat_id: UUID,
    status_data: SupportChatStatusUpdate,
    current_user: User = Depends(require_support_role),
    support_service: SupportService = Depends(get_support_service)
):
    """Обновить статус чата"""
    
    chat = support_service.get_chat_by_id(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # Проверяем права доступа
    if (current_user.role == UserRole.SUPPORT and 
        chat.assigned_to != current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    success = support_service.update_chat_status(chat_id, status_data.status)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update status")
    
    return {"message": "Status updated successfully"}


@router.post("/messages", response_model=SupportMessageResponse)
async def send_support_message(
    message_data: SupportMessageCreate,
    current_user: User = Depends(require_support_role),
    support_service: SupportService = Depends(get_support_service)
):
    """Отправить сообщение в чат поддержки"""
    
    chat = support_service.get_chat_by_id(message_data.chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # Проверяем права доступа
    if (current_user.role == UserRole.SUPPORT and 
        chat.assigned_to != current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    message = support_service.add_message(
        message_data, 
        sender_user_id=current_user.id if message_data.sender_type == "support" else None
    )
    
    return SupportMessageResponse.from_orm(message)


@router.get("/stats", response_model=SupportStatsResponse)
async def get_support_stats(
    current_user: User = Depends(require_support_role),
    support_service: SupportService = Depends(get_support_service)
):
    """Получить статистику поддержки"""
    return support_service.get_support_stats()


@router.get("/staff")
async def get_support_staff(
    current_user: User = Depends(require_support_role),
    support_service: SupportService = Depends(get_support_service)
):
    """Получить список сотрудников поддержки"""
    staff = support_service.get_support_staff()
    return [
        {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone_number": user.phone_number
        }
        for user in staff
    ]
