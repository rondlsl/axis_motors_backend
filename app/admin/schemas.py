from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from app.models.car_model import CarStatus


class CarFilterSchema(BaseModel):
    """Схема для фильтрации автомобилей"""
    status: Optional[CarStatus] = None
    search_query: Optional[str] = Field(None, description="Поиск по госномеру и марке авто")
    owner_id: Optional[int] = None
    auto_class: Optional[str] = None


class CarListItemSchema(BaseModel):
    """Схема для отображения автомобиля в списке"""
    id: int
    name: str
    plate_number: str
    status: str
    status_display: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    fuel_level: Optional[float] = None
    mileage: Optional[int] = None
    auto_class: str
    body_type: str
    year: Optional[int] = None
    owner_name: Optional[str] = None
    current_renter_name: Optional[str] = None
    photos: Optional[List[str]] = None
    
    class Config:
        from_attributes = True


class CarMapItemSchema(BaseModel):
    """Схема для отображения автомобиля на карте"""
    id: int
    name: str
    plate_number: str
    status: str
    status_display: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    fuel_level: Optional[float] = None
    course: Optional[int] = None
    photos: Optional[List[str]] = None
    current_renter: Optional[Dict[str, Any]] = None
    
    class Config:
        from_attributes = True


class CarStatusUpdateSchema(BaseModel):
    """Схема для обновления статуса автомобиля"""
    status: CarStatus
    reason: Optional[str] = Field(None, description="Причина изменения статуса")


class CarListResponseSchema(BaseModel):
    """Схема ответа для списка автомобилей"""
    cars: List[CarListItemSchema]
    total_count: int
    filtered_count: int


class CarMapResponseSchema(BaseModel):
    """Схема ответа для карты автомобилей"""
    cars: List[CarMapItemSchema]
    total_count: int


class CarSearchResponseSchema(BaseModel):
    """Схема ответа для поиска автомобилей"""
    cars: List[CarListItemSchema]
    search_query: str
    results_count: int


class CarStatisticsSchema(BaseModel):
    """Схема статистики по автомобилям"""
    total_cars: int
    cars_by_status: Dict[str, int]
    cars_by_class: Dict[str, int]
    cars_by_body_type: Dict[str, int]
    active_rentals: int
    available_cars: int
    service_cars: int


class CarDetailSchema(BaseModel):
    """Схема детальной информации об автомобиле"""
    id: int
    name: str
    plate_number: str
    engine_volume: Optional[float] = None
    year: Optional[int] = None
    drive_type: Optional[int] = None
    drive_type_display: Optional[str] = None
    body_type: str
    body_type_display: str
    transmission_type: Optional[str] = None
    transmission_type_display: Optional[str] = None
    status: str
    status_display: str
    photos: Optional[List[str]] = None
    description: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    fuel_level: Optional[float] = None
    mileage: Optional[int] = None
    course: Optional[int] = None
    auto_class: str
    price_per_minute: int
    price_per_hour: int
    price_per_day: int
    owner_id: Optional[int] = None
    current_renter_id: Optional[int] = None
    available_minutes: Optional[int] = None
    gps_id: Optional[str] = None
    gps_imei: Optional[str] = None
    
    class Config:
        from_attributes = True


class CarEditSchema(BaseModel):
    """Схема для редактирования автомобиля"""
    name: Optional[str] = None
    plate_number: Optional[str] = None
    engine_volume: Optional[float] = None
    year: Optional[int] = None
    drive_type: Optional[int] = None
    body_type: Optional[str] = None
    transmission_type: Optional[str] = None
    status: Optional[CarStatus] = None
    description: Optional[str] = None
    price_per_minute: Optional[int] = None
    price_per_hour: Optional[int] = None
    price_per_day: Optional[int] = None
    auto_class: Optional[str] = None


class CarCommentSchema(BaseModel):
    """Схема комментария к автомобилю"""
    id: int
    car_id: int
    author_id: int
    author_first_name: str
    author_last_name: str
    author_phone: str
    author_role: str
    comment: str
    created_at: str
    is_internal: bool = True  # Комментарии видны только механикам и админам
    
    class Config:
        from_attributes = True


class CarCommentCreateSchema(BaseModel):
    """Схема для создания комментария"""
    comment: str
    is_internal: bool = True


class CarCommentUpdateSchema(BaseModel):
    """Схема для обновления комментария"""
    comment: str


class UserProfileSchema(BaseModel):
    """Схема профиля пользователя"""
    id: int
    phone_number: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    documents_verified: bool
    auto_class: Optional[List[str]] = None
    wallet_balance: float
    selfie_with_license_url: Optional[str] = None
    created_at: str
    is_active: bool
    
    class Config:
        from_attributes = True


class CarAvailabilityTimerSchema(BaseModel):
    """Схема таймера доступности автомобиля"""
    car_id: int
    car_name: str
    plate_number: str
    available_minutes: int
    available_seconds: int
    total_available_seconds: int
    period_from: str
    period_to: str
    availability_percentage: float
    statistics: Dict[str, Any]

class CarCurrentUserSchema(BaseModel):
    """Схема информации о текущем пользователе автомобиля"""
    user_type: str  # "owner" или "renter"
    user_info: Optional[Dict[str, Any]] = None
    rental_info: Optional[Dict[str, Any]] = None
