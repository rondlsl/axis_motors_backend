from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class SupportChatBase(BaseModel):
    user_name: str = Field(..., description="ФИО клиента")
    user_phone: str = Field(..., description="Номер телефона клиента")
    message_text: str = Field(..., description="Первое сообщение от клиента")


class SupportChatCreate(SupportChatBase):
    user_telegram_id: int = Field(..., description="ID пользователя в Telegram")
    user_telegram_username: Optional[str] = Field(None, description="Username в Telegram")


class SupportChatResponse(BaseModel):
    id: UUID
    sid: str
    user_name: str
    user_phone: str
    user_telegram_id: int
    user_telegram_username: Optional[str]
    azv_user_id: Optional[UUID]
    status: str
    assigned_to: Optional[UUID]
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime]
    message_count: int
    is_active: bool

    class Config:
        from_attributes = True


class SupportMessageBase(BaseModel):
    message_text: str = Field(..., description="Текст сообщения")


class SupportMessageCreate(SupportMessageBase):
    chat_id: UUID = Field(..., description="ID чата поддержки")
    sender_type: str = Field(..., description="Тип отправителя: client, support, system")


class SupportMessageResponse(BaseModel):
    id: UUID
    sid: str
    chat_id: UUID
    sender_type: str
    sender_user_id: Optional[UUID]
    message_text: str
    telegram_message_id: Optional[int]
    is_from_bot: bool
    is_read: bool
    created_at: datetime
    sender_name: str

    class Config:
        from_attributes = True


class SupportChatWithMessages(SupportChatResponse):
    messages: List[SupportMessageResponse] = []


class SupportChatListResponse(BaseModel):
    chats: List[SupportChatResponse]
    total: int
    page: int
    per_page: int


class SupportChatAssignRequest(BaseModel):
    chat_id: UUID = Field(..., description="ID чата для назначения")
    assigned_to: UUID = Field(..., description="ID сотрудника поддержки")


class SupportChatStatusUpdate(BaseModel):
    chat_id: UUID = Field(..., description="ID чата")
    status: str = Field(..., description="Новый статус: new, in_progress, resolved, closed")


class SupportStatsResponse(BaseModel):
    total_chats: int
    new_chats: int
    in_progress_chats: int
    resolved_chats: int
    closed_chats: int
    avg_response_time_minutes: Optional[float]
    chats_per_support_staff: dict
