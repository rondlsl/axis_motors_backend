from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from app.models.history_model import RentalType, RentalStatus


class AdvanceBookingRequest(BaseModel):
    """Схема для запроса бронирования заранее"""
    car_id: int = Field(..., description="ID автомобиля")
    rental_type: RentalType = Field(..., description="Тип аренды")
    duration: Optional[int] = Field(None, description="Продолжительность (обязательна для часов и дней)")
    scheduled_start_time: datetime = Field(..., description="Запланированное время начала аренды")
    scheduled_end_time: Optional[datetime] = Field(None, description="Запланированное время окончания аренды")
    delivery_latitude: Optional[float] = Field(None, description="Широта доставки")
    delivery_longitude: Optional[float] = Field(None, description="Долгота доставки")


class BookingResponse(BaseModel):
    """Схема ответа для бронирования"""
    message: str
    rental_id: int
    reservation_time: str
    scheduled_start_time: Optional[str] = None
    scheduled_end_time: Optional[str] = None
    is_advance_booking: bool = False


class BookingListResponse(BaseModel):
    """Схема ответа для списка бронирований"""
    id: int
    car_id: int
    car_name: str
    car_plate_number: str
    rental_type: RentalType
    duration: Optional[int]
    scheduled_start_time: Optional[datetime]
    scheduled_end_time: Optional[datetime]
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    rental_status: RentalStatus
    total_price: Optional[int]
    base_price: Optional[int]
    open_fee: Optional[int]
    delivery_fee: Optional[int]
    reservation_time: datetime
    is_advance_booking: bool
    car_photos: Optional[list] = None


class CancelBookingRequest(BaseModel):
    """Схема для отмены бронирования"""
    reason: Optional[str] = Field(None, description="Причина отмены")


class CancelBookingResponse(BaseModel):
    """Схема ответа для отмены бронирования"""
    message: str
    rental_id: int
    refund_amount: Optional[int] = None
