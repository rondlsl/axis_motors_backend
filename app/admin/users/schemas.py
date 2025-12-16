from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
from app.models.user_model import UserRole
from app.schemas.base import SidMixin


class UserProfileSchema(SidMixin):
    """Схема профиля пользователя"""
    id: str
    phone_number: str
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    role: str
    is_active: bool
    is_verified_email: bool
    is_citizen_kz: bool
    documents_verified: bool
    selfie_url: Optional[str] = None
    selfie_with_license_url: Optional[str] = None
    drivers_license_url: Optional[str] = None
    id_card_front_url: Optional[str] = None
    id_card_back_url: Optional[str] = None
    psych_neurology_certificate_url: Optional[str] = None
    narcology_certificate_url: Optional[str] = None
    pension_contributions_certificate_url: Optional[str] = None
    auto_class: List[str] = []
    digital_signature: Optional[str] = None
    rating: Optional[float] = None 


class UserCardSchema(SidMixin):
    """Полная схема карточки пользователя для админ-панели"""
    id: str
    phone_number: str
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    iin: Optional[str] = None
    passport_number: Optional[str] = None
    birth_date: Optional[datetime] = None
    drivers_license_expiry: Optional[datetime] = None
    id_card_expiry: Optional[datetime] = None
    locale: Optional[str] = None
    role: str
    is_active: bool
    is_verified_email: bool
    is_citizen_kz: bool
    documents_verified: bool
    selfie_url: Optional[str] = None
    selfie_with_license_url: Optional[str] = None
    drivers_license_url: Optional[str] = None
    id_card_front_url: Optional[str] = None
    id_card_back_url: Optional[str] = None
    psych_neurology_certificate_url: Optional[str] = None
    narcology_certificate_url: Optional[str] = None
    pension_contributions_certificate_url: Optional[str] = None
    auto_class: List[str] = []
    digital_signature: Optional[str] = None
    is_consent_to_data_processing: bool = False
    is_contract_read: bool = False
    is_user_agreement: bool = False
    wallet_balance: float = 0.0
    created_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None
    mvd_approved: bool = False
    is_blocked: bool = False
    admin_comment: Optional[str] = None
    
    # Дополнительная информация
    current_rental_car: Optional[Dict[str, Any]] = None
    owner_earnings_current_month: Optional[float] = None
    owner_earnings_total: Optional[float] = None
    rating: Optional[float] = None 


class UserListSchema(SidMixin):
    """Схема для списка пользователей"""
    id: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    phone_number: str
    iin: Optional[str] = None
    passport_number: Optional[str] = None
    role: str
    auto_class: List[str] = []
    digital_signature: Optional[str] = None
    is_consent_to_data_processing: bool = False
    is_contract_read: bool = False
    is_user_agreement: bool = False
    selfie_url: Optional[str] = None
    is_blocked: bool = False
    current_rental_car: Optional[Dict[str, Any]] = None
    rating: Optional[float] = None 


class UserMapPositionSchema(SidMixin):
    """Схема для позиций пользователей на карте"""
    id: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    digital_signature: Optional[str] = None
    selfie_url: Optional[str] = None
    last_rental_end_latitude: Optional[float] = None
    last_rental_end_longitude: Optional[float] = None
    last_activity_at: Optional[datetime] = None
    is_active_rental: bool = False


class UserCommentUpdateSchema(BaseModel):
    """Схема для обновления комментария пользователя"""
    admin_comment: Optional[str] = None


class UserRoleUpdateSchema(BaseModel):
    """Схема обновления роли пользователя"""
    role: UserRole = Field(..., description="Новая роль пользователя")


class UserSearchFiltersSchema(BaseModel):
    """Схема фильтров для поиска пользователей"""
    role: Optional[str] = None
    search_query: Optional[str] = None
    has_active_rental: Optional[bool] = None
    is_blocked: Optional[bool] = None
    mvd_approved: Optional[bool] = None


class GuarantorInfoSchema(SidMixin):
    """Схема информации о гаранте/клиенте"""
    id: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    phone_number: str
    iin: Optional[str] = None
    passport_number: Optional[str] = None
    selfie_url: Optional[str] = None


class TripSummarySchema(BaseModel):
    """Сводка по поездкам"""
    total_minutes: int = 0
    total_spent: float = 0.0
    total_trips: int = 0


class TripListItemSchema(SidMixin):
    """Элемент списка поездок"""
    id: str
    rental_type: str
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    duration_minutes: int = 0
    total_price: float = 0.0
    car_name: Optional[str] = None
    car_plate_number: Optional[str] = None


class TripDetailSchema(SidMixin):
    """Детальная информация о поездке"""
    id: str
    rental_type: str
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    duration_minutes: int = 0
    total_price: float = 0.0
    
    car_id: str
    car_name: str
    car_plate_number: str
    
    photos_before: List[str] = [] 
    photos_after: List[str] = [] 
    mechanic_photos_before: List[str] = [] 
    mechanic_photos_after: List[str] = [] 
    
    client_comment: Optional[str] = None
    mechanic_comment: Optional[str] = None
    
    client_rating: Optional[int] = None
    mechanic_rating: Optional[int] = None
    rating: Optional[float] = None  
    
    start_latitude: Optional[float] = None
    start_longitude: Optional[float] = None
    end_latitude: Optional[float] = None
    end_longitude: Optional[float] = None


class OwnerCarListItemSchema(SidMixin):
    """Элемент списка автомобилей владельца"""
    id: str
    name: str
    plate_number: str
    available_minutes: int = 0
    earnings_current_month: float = 0.0
    earnings_total: float = 0.0
    photos: Optional[List[str]] = None
    vin: Optional[str] = None
    color: Optional[str] = None


class UserEditSchema(BaseModel):
    """Схема для редактирования пользователя"""
    auto_class: Optional[List[str]] = None
    role: Optional[UserRole] = None


class UserBlockSchema(BaseModel):
    """Схема для блокировки пользователя"""
    is_blocked: bool
    block_reason: Optional[str] = None


class CompanyBonusSchema(BaseModel):
    """Схема для начисления бонуса от компании"""
    phone_number: str = Field(..., min_length=11, max_length=11, description="Номер телефона пользователя")
    title: str = Field(..., min_length=1, max_length=100, description="Заголовок бонуса")
    amount: float = Field(..., gt=0, description="Сумма бонуса (должна быть больше 0)")
    description: str = Field(..., min_length=1, max_length=500, description="Описание бонуса")


class SanctionPenaltySchema(BaseModel):
    """Схема для назначения санкции клиенту"""
    phone_number: str = Field(..., min_length=11, max_length=11, description="Номер телефона пользователя")
    amount: float = Field(..., gt=0, description="Сумма санкции (штраф)")
    description: str = Field(..., min_length=1, max_length=500, description="Описание санкции")
    rental_id: str = Field(..., description="SID аренды, к которой относится санкция")


class DeleteRentalsRequestSchema(BaseModel):
    """Схема для запроса удаления аренд"""
    rental_ids: List[str] = Field(..., description="Список ID аренд для удаления")