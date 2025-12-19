from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from app.models.car_model import CarStatus
import uuid
from app.schemas.base import SidMixin


class CarFilterSchema(BaseModel):
    """Схема фильтра для автомобилей"""
    status: Optional[CarStatus] = None
    search_query: Optional[str] = None
    auto_class: Optional[str] = None


class OwnerSchema(BaseModel):
    """Схема владельца автомобиля"""
    owner_id: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    phone_number: str
    selfie: Optional[str] = None

    class Config:
        from_attributes = True


class CurrentRenterSchema(BaseModel):
    """Схема текущего арендатора автомобиля"""
    current_renter_id: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    phone_number: str
    role: str
    selfie: Optional[str] = None

    class Config:
        from_attributes = True


class CarListItemSchema(BaseModel):
    """Схема элемента списка автомобилей"""
    id: str
    name: str
    plate_number: str
    status: Optional[str] = None
    status_display: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    fuel_level: Optional[float] = None
    mileage: Optional[int] = None
    auto_class: str
    body_type: str
    year: Optional[int] = None
    owner: Optional[OwnerSchema] = None
    current_renter: Optional[CurrentRenterSchema] = None
    photos: Optional[List[str]] = None
    vin: Optional[str] = None
    color: Optional[str] = None
    rating: Optional[float] = None 

    class Config:
        from_attributes = True


class CarMapItemSchema(BaseModel):
    """Схема элемента карты автомобилей"""
    id: str
    name: str
    plate_number: str
    status: Optional[str] = None
    status_display: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    fuel_level: Optional[float] = None
    course: Optional[int] = None
    photos: Optional[List[str]] = None
    current_renter: Optional[dict] = None
    vin: Optional[str] = None
    color: Optional[str] = None
    rating: Optional[float] = None 


class CarStatusUpdateSchema(BaseModel):
    """Схема обновления статуса автомобиля"""
    status: CarStatus
    reason: Optional[str] = Field(None, description="Причина изменения статуса")


class CarListResponseSchema(BaseModel):
    """Схема ответа списка автомобилей"""
    cars: List[CarListItemSchema]
    total_count: int
    filtered_count: int


class CarMapResponseSchema(BaseModel):
    """Схема ответа карты автомобилей"""
    cars: List[CarMapItemSchema]
    total_count: int


class CarStatisticsSchema(BaseModel):
    """Схема статистики автомобилей"""
    total_cars: int
    free_cars: int
    in_use_cars: int
    active_rentals: int
    available_cars: int
    service_cars: int


class CarCommentCreateSchema(BaseModel):
    """Схема создания комментария к автомобилю"""
    comment: str
    is_internal: bool = False


class CarCommentUpdateSchema(BaseModel):
    """Схема обновления комментария к автомобилю"""
    comment: str


class CarAvailabilityTimerSchema(BaseModel):
    """Схема таймера доступности автомобиля"""
    car_id: str
    available_minutes: int
    last_rental_end: Optional[str] = None
    current_status: str


class CarCurrentUserSchema(BaseModel):
    """Схема текущего пользователя автомобиля"""
    user_type: str  # "owner", "renter", "none"
    user_info: Optional[Dict[str, Any]] = None


class CarDetailSchema(BaseModel):
    """Схема детальной информации об автомобиле"""
    id: str
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
    owner_id: Optional[str] = None
    current_renter_id: Optional[str] = None
    available_minutes: Optional[int] = None
    gps_id: Optional[str] = None
    gps_imei: Optional[str] = None
    vin: Optional[str] = None
    color: Optional[str] = None
    rating: Optional[float] = None  
    
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
    description: Optional[str] = None
    price_per_minute: Optional[int] = None
    price_per_hour: Optional[int] = None
    price_per_day: Optional[int] = None
    auto_class: Optional[str] = None
    vin: Optional[str] = None
    color: Optional[str] = None


class CarCommentSchema(SidMixin):
    """Схема комментария к автомобилю"""
    id: str
    car_id: str
    author_id: str
    author_name: str
    author_role: str
    comment: str
    created_at: str
    is_internal: bool

    class Config:
        from_attributes = True


class CarCommentCreateSchema(BaseModel):
    """Схема создания комментария"""
    comment: str
    is_internal: bool = True


class CarCommentUpdateSchema(BaseModel):
    """Схема обновления комментария"""
    comment: str


class CarAvailabilityTimerSchema(BaseModel):
    """Схема таймера доступности автомобиля"""
    car_id: str
    available_minutes: int
    last_rental_end: Optional[str] = None
    current_status: str


class CarCurrentUserSchema(SidMixin):
    """Схема текущего пользователя автомобиля"""
    user_id: Optional[str] = None
    user_type: str  # "owner" или "renter"
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    selfie_url: Optional[str] = None
