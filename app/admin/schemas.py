from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum


class CarStatus(str, Enum):
    """Статусы автомобилей для админ-панели"""
    FREE = "FREE"  # Свободные
    IN_USE = "IN_USE"  # В аренде
    MAINTENANCE = "MAINTENANCE"  # У механика/на ремонте
    DELIVERING = "DELIVERING"  # В доставке
    OWNER = "OWNER"  # У владельца
    RETURNING = "RETURNING"  # Возвращается
    DELIVERED = "DELIVERED"  # Доставлено
    RETURNED = "RETURNED"  # Возвращено


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
    maintenance_cars: int
