from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class AppVersionCreate(BaseModel):
    """Схема для создания записи о версиях приложения"""
    android_version: Optional[str] = Field(None, description="Версия Android приложения")
    ios_version: Optional[str] = Field(None, description="Версия iOS приложения")
    ios_link: Optional[str] = Field(None, description="Ссылка на iOS приложение")
    android_link: Optional[str] = Field(None, description="Ссылка на Android приложение")


class AppVersionResponse(BaseModel):
    """Схема ответа для версий приложения"""
    id: str
    android_version: Optional[str] = None
    ios_version: Optional[str] = None
    ios_link: Optional[str] = None
    android_link: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

