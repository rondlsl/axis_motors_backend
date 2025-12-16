from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from app.schemas.base import SidMixin, SidField


class SupportChatBase(BaseModel):
    user_name: str = Field(
        ..., 
        description="ФИО клиента",
        example="Иван Иванов"
    )
    user_phone: str = Field(
        ..., 
        description="Номер телефона клиента",
        example="+77001234567"
    )
    message_text: str = Field(
        ..., 
        description="Первое сообщение от клиента",
        example="У меня проблема с арендой автомобиля"
    )


class SupportChatCreate(SupportChatBase):
    user_telegram_id: int = Field(
        ..., 
        description="ID пользователя в Telegram",
        example=860991388
    )
    user_telegram_username: Optional[str] = Field(
        None, 
        description="Username в Telegram",
        example="ivan_user"
    )


class SupportChatResponse(SidMixin):
    id: str = Field(..., example="NTNdkwMISUyHK00ntA4Ssw")
    user_name: str = Field(..., example="Иван Иванов")
    user_phone: str = Field(..., example="+77001234567")
    user_telegram_id: int = Field(..., example=860991388)
    user_telegram_username: Optional[str] = Field(None, example="ivan_user")
    azv_user_id: Optional[str] = Field(None, example="aqgP9ItsRXKNIWYtXGyRhA")
    status: str = Field(..., example="new")
    assigned_to: Optional[str] = Field(None, example="aqgP9ItsRXKNIWYtXGyRhA")
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime]
    message_count: int = Field(..., example=5)
    is_active: bool = Field(..., example=True)

    class Config:
        from_attributes = True


class SupportMessageBase(BaseModel):
    message_text: str = Field(
        ..., 
        description="Текст сообщения",
        example="Здравствуйте! Мы работаем над вашей проблемой..."
    )


class SupportMessageCreate(SupportMessageBase):
    chat_id: str = Field(
        ..., 
        description="ID чата поддержки",
        example="NTNdkwMISUyHK00ntA4Ssw"
    )
    sender_type: str = Field(
        ..., 
        description="Тип отправителя: client, support, system",
        example="support"
    )
    media_type: Optional[str] = Field(
        None,
        description="Тип медиа: photo, document, video, audio, voice",
        example="photo"
    )
    media_url: Optional[str] = Field(
        None,
        description="URL или путь к медиа файлу",
        example="uploads/support/photo_123.jpg"
    )
    media_file_name: Optional[str] = Field(
        None,
        description="Имя файла",
        example="photo.jpg"
    )
    media_file_size: Optional[int] = Field(
        None,
        description="Размер файла в байтах",
        example=102400
    )


class SupportMessageReply(SupportMessageBase):
    """Схема для ответов поддержки"""
    chat_id: str = Field(
        ..., 
        description="ID чата поддержки",
        example="NTNdkwMISUyHK00ntA4Ssw"
    )


class SupportMessageResponse(SidMixin):
    id: str
    chat_id: str
    sender_type: str
    sender_user_id: Optional[str] = None
    message_text: str
    telegram_message_id: Optional[int]
    is_from_bot: bool
    is_read: bool
    media_type: Optional[str] = None
    media_url: Optional[str] = None
    media_file_name: Optional[str] = None
    media_file_size: Optional[int] = None
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
    assigned_to: str = Field(
        ..., 
        description="ID сотрудника поддержки",
        example="aqgP9ItsRXKNIWYtXGyRhA"
    )


class SupportChatStatusUpdate(BaseModel):
    status: str = Field(
        ..., 
        description="Новый статус: new, in_progress, resolved, closed",
        example="in_progress"
    )


class SupportStatsResponse(BaseModel):
    total_chats: int
    new_chats: int
    in_progress_chats: int
    resolved_chats: int
    closed_chats: int
    avg_response_time_minutes: Optional[float]
    chats_per_support_staff: dict
