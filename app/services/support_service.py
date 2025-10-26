from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func
from typing import List, Optional, Tuple
from uuid import UUID
from datetime import datetime, timedelta

from app.models.support_chat_model import SupportChat, SupportChatStatus
from app.models.support_message_model import SupportMessage, SupportMessageSenderType
from app.models.user_model import User, UserRole
from app.schemas.support_schemas import (
    SupportChatCreate, SupportMessageCreate, SupportChatResponse,
    SupportMessageResponse, SupportChatWithMessages, SupportStatsResponse
)


class SupportService:
    def __init__(self, db: Session):
        self.db = db

    def create_chat(self, chat_data: SupportChatCreate) -> SupportChat:
        """Создать новый чат поддержки"""
        
        phone_for_search = chat_data.user_phone.replace("+", "")
        azv_user = self.db.query(User).filter(
            User.phone_number == phone_for_search
        ).first()
        
        # Создаем чат
        chat = SupportChat(
            user_telegram_id=chat_data.user_telegram_id,
            user_telegram_username=chat_data.user_telegram_username,
            user_name=chat_data.user_name,
            user_phone=chat_data.user_phone,
            azv_user_id=azv_user.id if azv_user else None,
            status=SupportChatStatus.NEW
        )
        
        self.db.add(chat)
        self.db.flush()  # Получаем ID чата
        
        # Создаем первое сообщение
        first_message = SupportMessage(
            chat_id=chat.id,
            sender_type=SupportMessageSenderType.CLIENT,
            message_text=chat_data.message_text,
            is_from_bot=True
        )
        
        self.db.add(first_message)
        self.db.commit()
        
        return chat

    def get_chat_by_id(self, chat_id: UUID) -> Optional[SupportChat]:
        """Получить чат по ID"""
        return self.db.query(SupportChat).filter(SupportChat.id == chat_id).first()

    def get_chat_by_telegram_id(self, telegram_id: int) -> Optional[SupportChat]:
        """Получить активный чат по Telegram ID пользователя"""
        return self.db.query(SupportChat).filter(
            and_(
                SupportChat.user_telegram_id == telegram_id,
                SupportChat.status.in_([
                    SupportChatStatus.NEW,
                    SupportChatStatus.IN_PROGRESS,
                    SupportChatStatus.RESOLVED
                ])
            )
        ).first()

    def add_message(self, message_data: SupportMessageCreate, sender_user_id: Optional[UUID] = None) -> SupportMessage:
        """Добавить сообщение в чат"""
        
        message = SupportMessage(
            chat_id=message_data.chat_id,
            sender_type=message_data.sender_type,
            sender_user_id=sender_user_id,
            message_text=message_data.message_text,
            is_from_bot=True
        )
        
        self.db.add(message)
        
        # Обновляем время последнего обновления чата
        chat = self.get_chat_by_id(message_data.chat_id)
        if chat:
            chat.updated_at = datetime.utcnow()
        
        self.db.commit()
        return message

    def assign_chat(self, chat_id: UUID, support_user_id: UUID) -> bool:
        """Назначить чат сотруднику поддержки"""
        
        chat = self.get_chat_by_id(chat_id)
        if not chat or chat.status != SupportChatStatus.NEW:
            return False
        
        # Проверяем, что пользователь имеет роль SUPPORT
        support_user = self.db.query(User).filter(
            and_(
                User.id == support_user_id,
                User.role == UserRole.SUPPORT
            )
        ).first()
        
        if not support_user:
            return False
        
        chat.assigned_to = support_user_id
        chat.status = SupportChatStatus.IN_PROGRESS
        chat.updated_at = datetime.utcnow()
        
        self.db.commit()
        return True

    def update_chat_status(self, chat_id: UUID, status: str) -> bool:
        """Обновить статус чата"""
        
        chat = self.get_chat_by_id(chat_id)
        if not chat:
            return False
        
        chat.status = status
        chat.updated_at = datetime.utcnow()
        
        if status == SupportChatStatus.CLOSED:
            chat.closed_at = datetime.utcnow()
        
        self.db.commit()
        return True

    def get_chats_for_support(self, support_user_id: Optional[UUID] = None, 
                            status: Optional[str] = None, 
                            page: int = 1, per_page: int = 20) -> Tuple[List[SupportChat], int]:
        """Получить список чатов для поддержки"""
        
        query = self.db.query(SupportChat)
        
        # Фильтр по сотруднику
        if support_user_id:
            query = query.filter(SupportChat.assigned_to == support_user_id)
        
        # Фильтр по статусу
        if status:
            query = query.filter(SupportChat.status == status)
        
        # Сортировка по времени создания (новые сверху)
        query = query.order_by(desc(SupportChat.created_at))
        
        # Подсчет общего количества
        total = query.count()
        
        # Пагинация
        offset = (page - 1) * per_page
        chats = query.offset(offset).limit(per_page).all()
        
        return chats, total

    def get_support_stats(self) -> SupportStatsResponse:
        """Получить статистику поддержки"""
        
        # Общая статистика по статусам
        stats = self.db.query(
            SupportChat.status,
            func.count(SupportChat.id).label('count')
        ).group_by(SupportChat.status).all()
        
        stats_dict = {stat.status: stat.count for stat in stats}
        
        # Статистика по сотрудникам
        support_stats = self.db.query(
            User.first_name,
            func.count(SupportChat.id).label('chat_count')
        ).join(SupportChat, User.id == SupportChat.assigned_to).filter(
            User.role == UserRole.SUPPORT
        ).group_by(User.id, User.first_name).all()
        
        chats_per_support = {
            stat.first_name: stat.chat_count 
            for stat in support_stats
        }
        
        return SupportStatsResponse(
            total_chats=sum(stats_dict.values()),
            new_chats=stats_dict.get(SupportChatStatus.NEW, 0),
            in_progress_chats=stats_dict.get(SupportChatStatus.IN_PROGRESS, 0),
            resolved_chats=stats_dict.get(SupportChatStatus.RESOLVED, 0),
            closed_chats=stats_dict.get(SupportChatStatus.CLOSED, 0),
            avg_response_time_minutes=None,  # TODO: реализовать расчет
            chats_per_support_staff=chats_per_support
        )

    def get_support_staff(self) -> List[User]:
        """Получить список сотрудников поддержки"""
        return self.db.query(User).filter(User.role == UserRole.SUPPORT).all()
