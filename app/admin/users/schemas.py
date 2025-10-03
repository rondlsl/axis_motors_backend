from pydantic import BaseModel, Field
from typing import List, Optional
from app.models.user_model import UserRole


class UserProfileSchema(BaseModel):
    """Схема профиля пользователя"""
    id: int
    phone_number: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    is_active: bool
    documents_verified: bool
    selfie_url: Optional[str] = None
    selfie_with_license_url: Optional[str] = None
    drivers_license_url: Optional[str] = None
    id_card_front_url: Optional[str] = None
    id_card_back_url: Optional[str] = None
    auto_class: List[str] = []


class UserRoleUpdateSchema(BaseModel):
    """Схема обновления роли пользователя"""
    role: UserRole = Field(..., description="Новая роль пользователя")
