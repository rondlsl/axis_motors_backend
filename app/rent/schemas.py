from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
import uuid
from app.models.history_model import RentalType, RentalStatus
from app.schemas.base import SidMixin


class AdvanceBookingRequest(BaseModel):
    """Схема для запроса бронирования заранее"""
    car_id: str = Field(..., description="ID автомобиля")
    rental_type: RentalType = Field(..., description="Тип аренды")
    duration: Optional[int] = Field(None, description="Продолжительность (обязательна для часов и дней)")
    scheduled_start_time: datetime = Field(..., description="Запланированное время начала аренды")
    scheduled_end_time: Optional[datetime] = Field(None, description="Запланированное время окончания аренды")
    delivery_latitude: Optional[float] = Field(None, description="Широта доставки")
    delivery_longitude: Optional[float] = Field(None, description="Долгота доставки")
    with_driver: bool = Field(False, description="Аренда с водителем")


class BookingResponse(SidMixin):
    """Схема ответа для бронирования"""
    message: str
    rental_id: str
    reservation_time: str
    scheduled_start_time: Optional[str] = None
    scheduled_end_time: Optional[str] = None
    is_advance_booking: bool = False


class BookingListResponse(SidMixin):
    """Схема ответа для списка бронирований"""
    id: str
    car_id: str
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
    car_vin: Optional[str] = None
    car_color: Optional[str] = None


class CancelBookingRequest(BaseModel):
    """Схема для отмены бронирования"""
    reason: Optional[str] = Field(None, description="Причина отмены")


class CancelBookingResponse(SidMixin):
    """Схема ответа для отмены бронирования"""
    message: str
    rental_id: str
    refund_amount: Optional[int] = None


class RentalCalculatorRequest(BaseModel):
    """Схема запроса для калькулятора стоимости аренды"""
    car_id: str = Field(..., description="ID автомобиля")
    rental_type: RentalType = Field(..., description="Тип аренды: MINUTES, HOURS, DAYS")
    duration: Optional[int] = Field(None, description="Продолжительность (обязательна для HOURS и DAYS)")
    include_delivery: bool = Field(False, description="Включить доставку")
    with_driver: bool = Field(False, description="Аренда с водителем")


class RentalCostBreakdown(BaseModel):
    """Детализированная разбивка стоимости"""
    base_price: int = Field(..., description="Базовая стоимость аренды")
    open_fee: int = Field(..., description="Стоимость открытия дверей")
    fuel_cost: int = Field(..., description="Стоимость топлива (резерв)")
    delivery_fee: int = Field(..., description="Стоимость доставки")
    minute_cost_reserve: int = Field(..., description="Резерв на поминутную оплату")
    driver_fee: int = Field(0, description="Стоимость водителя")


class RentalCalculatorResponse(BaseModel):
    """Схема ответа калькулятора стоимости аренды"""
    car_id: str
    car_name: Optional[str] = None
    rental_type: RentalType
    duration: Optional[int]
    include_delivery: bool
    breakdown: RentalCostBreakdown
    total_minimum_balance: int = Field(..., description="Минимальный баланс для аренды")


class ExtendRentalRequest(BaseModel):
    """Схема запроса для продления суточного тарифа"""
    days: int = Field(..., ge=1, le=30, description="Количество дней для продления (от 1 до 30)")


class ExtendRentalResponse(BaseModel):
    """Схема ответа для продления аренды"""
    message: str
    rental_id: str
    new_duration: int = Field(..., description="Новая продолжительность аренды в днях")
    extension_cost: int = Field(..., description="Стоимость продления")
    new_base_price: int = Field(..., description="Новая базовая стоимость аренды")
    remaining_balance: float = Field(..., description="Оставшийся баланс пользователя")
