from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class CarOwnerResponse(BaseModel):
    """Схема для автомобиля в списке владельца"""
    id: int = Field(..., description="Уникальный идентификатор автомобиля")
    name: str = Field(..., description="Название автомобиля", example="HAVAL F7x")
    plate_number: str = Field(..., description="Государственный номер", example="422ABK02")
    
    class Config:
        from_attributes = True


class TripResponse(BaseModel):
    """Схема для поездки в календаре"""
    id: int = Field(..., description="Уникальный идентификатор поездки")
    duration_minutes: int = Field(..., description="Продолжительность поездки в минутах", example=120)
    earnings: int = Field(..., description="Заработок владельца с поездки в тенге", example=7500)
    rental_type: str = Field(..., description="Тип тарифа", example="hours", enum=["minutes", "hours", "days"])
    start_time: Optional[str] = Field(None, description="Время начала поездки (ISO 8601)", example="2024-01-15T14:30:00")
    end_time: Optional[str] = Field(None, description="Время окончания поездки (ISO 8601)", example="2024-01-15T16:30:00")
    
    class Config:
        from_attributes = True


class MonthEarnings(BaseModel):
    """Схема для заработка за месяц"""
    year: int = Field(..., description="Год", example=2024)
    month: int = Field(..., description="Месяц (1-12)", example=1, ge=1, le=12)
    total_earnings: int = Field(..., description="Общий заработок за месяц в тенге", example=45000)
    trip_count: int = Field(..., description="Количество поездок за месяц", example=8)


class TripsForMonthResponse(BaseModel):
    """Схема для ответа с поездками за месяц"""
    vehicle_id: int = Field(..., description="ID автомобиля")
    vehicle_name: str = Field(..., description="Название автомобиля", example="HAVAL F7x")
    vehicle_plate_number: str = Field(..., description="Госномер автомобиля", example="422ABK02")
    month_earnings: MonthEarnings = Field(..., description="Заработок за выбранный месяц")
    trips: List[TripResponse] = Field(..., description="Список поездок за месяц")
    available_months: List[MonthEarnings] = Field(..., description="Список доступных месяцев с заработком")


class PhotoGroup(BaseModel):
    """Группа фотографий"""
    photos: List[str] = Field(..., description="Список URL фотографий", example=["/uploads/rents/123/before/car/1.jpg"])


class TripPhotos(BaseModel):
    """Фотографии поездки"""
    client_before: PhotoGroup = Field(..., description="Фото от клиента до поездки")
    client_after: PhotoGroup = Field(..., description="Фото от клиента после поездки")
    mechanic_after: PhotoGroup = Field(..., description="Фото от механика после осмотра")


class RouteMapData(BaseModel):
    """Данные для отображения маршрута"""
    start_latitude: float = Field(..., description="Широта начальной точки", example=43.238949)
    start_longitude: float = Field(..., description="Долгота начальной точки", example=76.889709)
    end_latitude: Optional[float] = Field(None, description="Широта конечной точки", example=43.245678)
    end_longitude: Optional[float] = Field(None, description="Долгота конечной точки", example=76.901234)
    duration_over_24h: bool = Field(..., description="Длилась ли поездка более 24 часов", example=False)


class TripDetailResponse(BaseModel):
    """Детальная информация о поездке"""
    id: int = Field(..., description="ID поездки")
    vehicle_id: int = Field(..., description="ID автомобиля")
    vehicle_name: str = Field(..., description="Название автомобиля", example="HAVAL F7x")
    vehicle_plate_number: str = Field(..., description="Госномер", example="422ABK02")
    duration_minutes: int = Field(..., description="Продолжительность в минутах", example=120)
    earnings: int = Field(..., description="Заработок владельца в тенге", example=7500)
    rental_type: str = Field(..., description="Тип тарифа", example="hours", enum=["minutes", "hours", "days"])
    start_time: Optional[str] = Field(None, description="Время начала поездки", example="2024-01-15T14:30:00")
    end_time: Optional[str] = Field(None, description="Время окончания поездки", example="2024-01-15T16:30:00")
    photos: TripPhotos = Field(..., description="Фотографии поездки")
    route_map: RouteMapData = Field(..., description="Данные маршрута для карты")
    
    class Config:
        from_attributes = True


class MyAutosResponse(BaseModel):
    """Ответ для списка автомобилей владельца"""
    cars: List[CarOwnerResponse] = Field(..., description="Список автомобилей владельца с историей поездок")
