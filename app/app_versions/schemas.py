from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class AppVersionCreate(BaseModel):
    """Схема для создания записи о версиях приложения"""
    android_version: Optional[str] = Field(None, description="Версия Android приложения")
    ios_version: Optional[str] = Field(None, description="Версия iOS приложения")
    ios_link: Optional[str] = Field(None, description="Ссылка на iOS приложение")
    android_link: Optional[str] = Field(None, description="Ссылка на Android приложение")
    ai_is_worked: Optional[bool] = Field(None, description="Работает ли AI")


class AppVersionResponse(BaseModel):
    """Схема ответа для версий приложения"""
    id: str
    android_version: Optional[str] = None
    ios_version: Optional[str] = None
    ios_link: Optional[str] = None
    android_link: Optional[str] = None
    ai_is_worked: Optional[bool] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CheckVersionRequest(BaseModel):
    """Схема запроса для проверки версии приложения"""
    platform: str = Field(..., description="Платформа устройства: ios, android, web")
    app_version: Optional[str] = Field(None, description="Текущая версия приложения на устройстве")


class CheckVersionResponse(BaseModel):
    """Схема ответа для проверки версии приложения"""
    needs_update: bool = Field(..., description="Требуется ли обновление")
    current_version: Optional[str] = Field(None, description="Текущая версия на устройстве")
    latest_version: Optional[str] = Field(None, description="Последняя доступная версия")
    update_link: Optional[str] = Field(None, description="Ссылка для обновления приложения")
    message: Optional[str] = Field(None, description="Сообщение для пользователя")

