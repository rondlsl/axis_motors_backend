from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
import logging
import httpx

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.support_chat_model import SupportChatStatus
from app.support.deps import require_support_role, require_admin_role
from app.services.support_service import SupportService
from app.utils.short_id import safe_sid_to_uuid, uuid_to_sid
from app.utils.sid_converter import convert_uuid_response_to_sid
from app.schemas.support_schemas import (
    SupportChatCreate, SupportChatResponse, SupportMessageCreate,
    SupportMessageResponse, SupportChatWithMessages, SupportChatListResponse,
    SupportChatAssignRequest, SupportChatStatusUpdate, SupportStatsResponse,
    SupportMessageReply
)
from app.utils.telegram_logger import log_error_to_telegram
from app.utils.action_logger import log_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/support", tags=["Support"])


def get_support_service(db: Session = Depends(get_db)) -> SupportService:
    return SupportService(db)


@router.post("/chats", response_model=SupportChatResponse)
async def create_support_chat(
    chat_data: SupportChatCreate,
    support_service: SupportService = Depends(get_support_service)
):
    """Создать новый чат поддержки"""
    try:
        chat = support_service.create_chat(chat_data)
        return SupportChatResponse.from_orm_with_sid(chat)
    except Exception as e:
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=None,
                additional_context={
                    "action": "create_support_chat",
                    "telegram_id": chat_data.user_telegram_id,
                    "message": chat_data.message
                }
            )
        except:
            pass
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/chats", response_model=SupportChatListResponse)
async def get_support_chats(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    current_user: User = Depends(require_support_role),
    support_service: SupportService = Depends(get_support_service)
):
    """Получить список чатов поддержки"""
    
    # Если не админ, показываем только свои чаты
    if current_user.role == UserRole.SUPPORT:
        assigned_to = uuid_to_sid(current_user.id)
    
    assigned_to_uuid = None
    if assigned_to:
        try:
            assigned_to_uuid = safe_sid_to_uuid(assigned_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid assigned_to sid format")
    
    chats, total = support_service.get_chats_for_support(
        support_user_id=assigned_to_uuid,
        status=status,
        page=page,
        per_page=per_page
    )
    
    return SupportChatListResponse(
        chats=[SupportChatResponse.from_orm_with_sid(chat) for chat in chats],
        total=total,
        page=page,
        per_page=per_page
    )


@router.get("/chats/all", response_model=SupportChatListResponse)
async def get_all_support_chats(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    current_user: User = Depends(require_admin_role),
    support_service: SupportService = Depends(get_support_service)
):
    """Получить ВСЕ чаты поддержки (только для админов)"""
    
    assigned_to_uuid = None
    if assigned_to:
        try:
            assigned_to_uuid = safe_sid_to_uuid(assigned_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid assigned_to sid format")
    
    chats, total = support_service.get_chats_for_support(
        support_user_id=assigned_to_uuid,
        status=status,
        page=page,
        per_page=per_page
    )
    
    return SupportChatListResponse(
        chats=[SupportChatResponse.from_orm_with_sid(chat) for chat in chats],
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
        chats=[SupportChatResponse.from_orm_with_sid(chat) for chat in chats],
        total=total,
        page=page,
        per_page=per_page
    )


@router.get("/chats/{chat_id}", response_model=SupportChatWithMessages)
async def get_support_chat(
    chat_id: str,
    current_user: User = Depends(require_support_role),
    support_service: SupportService = Depends(get_support_service)
):
    """Получить чат с сообщениями"""
    
    chat = support_service.get_chat_by_sid(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # Проверяем права доступа
    if (current_user.role == UserRole.SUPPORT and 
        chat.assigned_to != current_user.id and 
        chat.status == SupportChatStatus.NEW):
        raise HTTPException(status_code=403, detail="Access denied")
    
    return SupportChatWithMessages.from_orm_with_sid(chat)


@router.get("/chats/{chat_id}/messages", response_model=List[SupportMessageResponse])
async def get_chat_messages(
    chat_id: str,
    current_user: User = Depends(require_support_role),
    support_service: SupportService = Depends(get_support_service)
):
    """Получить сообщения конкретного чата"""
    
    chat = support_service.get_chat_by_sid(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # Проверяем права доступа
    if (current_user.role == UserRole.SUPPORT and 
        chat.assigned_to != current_user.id and 
        chat.status == SupportChatStatus.NEW):
        raise HTTPException(status_code=403, detail="Access denied")
    
    messages = support_service.get_chat_messages(chat.id)
    
    # Помечаем все сообщения как прочитанные при просмотре
    support_service.mark_messages_as_read(chat.id, current_user.id)
    
    return [SupportMessageResponse.from_orm_with_sid(msg) for msg in messages]


@router.post("/chats/{chat_id}/take")
async def take_chat(
    chat_id: str,
    current_user: User = Depends(require_support_role),
    support_service: SupportService = Depends(get_support_service)
):
    """Взять чат в работу (назначить себе)"""
    
    success = support_service.assign_chat_by_sid(chat_id, uuid_to_sid(current_user.id))
    if not success:
        raise HTTPException(status_code=400, detail="Failed to take chat")
    
    return {"message": "Chat taken successfully"}


@router.post("/chats/{chat_id}/assign")
async def assign_chat(
    chat_id: str,
    assign_data: SupportChatAssignRequest,
    current_user: User = Depends(require_support_role),
    support_service: SupportService = Depends(get_support_service),
    db: Session = Depends(get_db)
):
    """Назначить чат сотруднику поддержки"""
    
    # Только админы могут назначать чаты другим
    if (current_user.role == UserRole.SUPPORT and 
        assign_data.assigned_to != uuid_to_sid(current_user.id)):
        raise HTTPException(status_code=403, detail="Can only assign to yourself")
    
    success = support_service.assign_chat_by_sid(chat_id, assign_data.assigned_to)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to assign chat")
    
    if current_user.role == UserRole.ADMIN:
        log_action(
            db,
            actor_id=current_user.id,
            action="admin_assign_support_chat",
            entity_type="support_chat",
            entity_id=None,  
            details={
                "chat_sid": chat_id,
                "assigned_to_sid": assign_data.assigned_to
            }
        )
        db.commit()

    return {"message": "Chat assigned successfully"}


@router.put("/chats/{chat_id}/status")
async def update_chat_status(
    chat_id: str,
    status_data: SupportChatStatusUpdate,
    current_user: User = Depends(require_support_role),
    support_service: SupportService = Depends(get_support_service)
):
    """Обновить статус чата"""
    
    chat = support_service.get_chat_by_sid(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # Проверяем права доступа
    if (current_user.role == UserRole.SUPPORT and 
        chat.assigned_to != current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Сохраняем старый статус для отправки уведомления
    old_status = chat.status
    new_status = status_data.status
    
    success = support_service.update_chat_status_by_sid(chat_id, status_data.status)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update status")
    
    # Отправляем уведомление клиенту, если статус изменился на resolved или closed
    if old_status != new_status and new_status in [SupportChatStatus.RESOLVED, SupportChatStatus.CLOSED]:
        await send_status_change_notification_to_client(
            chat.user_telegram_id, 
            new_status,
            chat.sid
        )
    
    return {"message": "Status updated successfully"}


@router.post("/messages", response_model=SupportMessageResponse)
async def send_support_message(
    message_data: SupportMessageReply,
    current_user: User = Depends(require_support_role),
    support_service: SupportService = Depends(get_support_service)
):
    """Отправить сообщение в чат поддержки"""
    
    chat = support_service.get_chat_by_sid(message_data.chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # Проверяем права доступа
    if (current_user.role == UserRole.SUPPORT and 
        chat.assigned_to != current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Создаем объект SupportMessageCreate с автоматическим sender_type = "support"
    message_create = SupportMessageCreate(
        chat_id=message_data.chat_id,
        sender_type="support",
        message_text=message_data.message_text
    )
    
    message = support_service.add_message(
        message_create, 
        sender_user_id=current_user.id
    )
    
    # Отправляем уведомление клиенту в Telegram
    await send_message_to_client(chat.user_telegram_id, message_data.message_text)
    
    return SupportMessageResponse.from_orm_with_sid(message)


async def send_message_to_client(telegram_id: int, message_text: str):
    """Отправить сообщение клиенту в Telegram (с разбивкой на части, если превышает лимит Telegram)"""
    try:
        from app.core.config import TELEGRAM_BOT_TOKEN_2
        import asyncio
        
        if not TELEGRAM_BOT_TOKEN_2:
            logger.warning("TELEGRAM_BOT_TOKEN_2 не установлен")
            return
        
        full_text = f"📞 Поддержка:\n\n{message_text}"
        MAX_MESSAGE_LENGTH = 4096
        
        if len(full_text) <= MAX_MESSAGE_LENGTH:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN_2}/sendMessage",
                    json={
                        "chat_id": telegram_id,
                        "text": full_text
                    }
                )
                response.raise_for_status()
                logger.info(f"Сообщение отправлено клиенту {telegram_id}")
        else:
            parts = []
            current_part = ""
            lines = full_text.split('\n')
            
            for line in lines:
                if len(line) > MAX_MESSAGE_LENGTH:
                    if current_part:
                        parts.append(current_part.strip())
                        current_part = ""
                    for i in range(0, len(line), MAX_MESSAGE_LENGTH):
                        parts.append(line[i:i + MAX_MESSAGE_LENGTH])
                elif len(current_part) + len(line) + 1 <= MAX_MESSAGE_LENGTH:
                    current_part += line + '\n' if current_part else line + '\n'
                else:
                    if current_part:
                        parts.append(current_part.strip())
                    current_part = line + '\n'
            
            if current_part:
                parts.append(current_part.strip())
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                for i, part in enumerate(parts):
                    part_text = part
                    if len(parts) > 1:
                        part_text = f"📞 Поддержка (часть {i + 1} из {len(parts)}):\n\n{part}"
                    
                    response = await client.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN_2}/sendMessage",
                        json={
                            "chat_id": telegram_id,
                            "text": part_text
                        }
                    )
                    response.raise_for_status()
                    
                    if i < len(parts) - 1:
                        await asyncio.sleep(0.1)
                
                logger.info(f"Сообщение отправлено клиенту {telegram_id} ({len(parts)} частей)")
            
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения клиенту: {e}")
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=None,
                additional_context={
                    "action": "send_message_to_client_telegram",
                    "telegram_id": telegram_id,
                    "message_length": len(message_text) if message_text else 0
                }
            )
        except:
            pass


async def send_status_change_notification_to_client(telegram_id: int, new_status: str, chat_id: str):
    """Отправить уведомление клиенту об изменении статуса обращения"""
    try:
        from app.core.config import TELEGRAM_BOT_TOKEN_2
        
        if not TELEGRAM_BOT_TOKEN_2:
            logger.warning("TELEGRAM_BOT_TOKEN_2 не установлен")
            return
        
        if not telegram_id:
            logger.warning(f"Telegram ID не найден для чата {chat_id}")
            return
            
        status_messages = {
            SupportChatStatus.RESOLVED: (
                "✅ **Ваше обращение решено!**\n\n"
                "Мы завершили работы по вашему обращению.\n\n"
                "Если у вас возникнут дополнительные вопросы, просто отправьте сообщение в этом чате."
            ),
            SupportChatStatus.CLOSED: (
                "🔒 **Обращение закрыто**\n\n"
                "Ваше обращение в поддержку было закрыто.\n\n"
                "Если вам понадобится помощь снова, создайте новое обращение через бота."
            )
        }
        
        message_text = status_messages.get(new_status)
        if not message_text:
            return
            
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN_2}/sendMessage",
                json={
                    "chat_id": telegram_id,
                    "text": message_text
                }
            )
            response.raise_for_status()
            logger.info(f"Уведомление о смене статуса отправлено клиенту {telegram_id}, статус: {new_status}")
            
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления о смене статуса клиенту: {e}")


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
            "id": uuid_to_sid(user.id),
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone_number": user.phone_number
        }
        for user in staff
    ]
