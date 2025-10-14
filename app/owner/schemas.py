from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
import uuid
from app.schemas.base import SidMixin


class CarOwnerResponse(BaseModel):
    """Схема для автомобиля в списке владельца"""
    id: str = Field(..., description="Уникальный идентификатор автомобиля")
    name: str = Field(..., description="Название автомобиля", example="HAVAL F7x")
    plate_number: str = Field(..., description="Государственный номер", example="422ABK02")
    available_minutes: int = Field(..., description="Доступные минуты в текущем месяце", example=38400)
    
    class Config:
        from_attributes = True


class TripResponse(SidMixin):
    """Схема для поездки в календаре"""
    id: str = Field(..., description="Уникальный идентификатор поездки")
    duration_minutes: int = Field(..., description="Продолжительность поездки в минутах", example=120)
    earnings: int = Field(..., description="Заработок владельца с поездки в тенге", example=7500)
    rental_type: str = Field(..., description="Тип тарифа", example="hours", enum=["minutes", "hours", "days"])
    start_time: Optional[str] = Field(None, description="Время начала поездки (ISO 8601)", example="2024-01-15T14:30:00")
    end_time: Optional[str] = Field(None, description="Время окончания поездки (ISO 8601)", example="2024-01-15T16:30:00")
    user_id: str = Field(..., description="ID водителя (пользователя)", example="VQ6EAOKbQdSnFkRmVUQAAA")
    fuel_cost: Optional[int] = Field(None, description="Стоимость топлива в тенге (только для поездок владельца)", example=2250)
    delivery_cost: Optional[int] = Field(None, description="Стоимость доставки в тенге (только для поездок владельца)", example=5000)
    
    class Config:
        from_attributes = True


class MonthEarnings(BaseModel):
    """Схема для заработка за месяц"""
    year: int = Field(..., description="Год", example=2024)
    month: int = Field(..., description="Месяц (1-12)", example=1, ge=1, le=12)
    total_earnings: int = Field(..., description="Общий заработок за месяц в тенге", example=45000)
    trip_count: int = Field(..., description="Количество поездок за месяц", example=8)
    available_minutes: int = Field(..., description="Количество минут доступности для клиентов", example=38400)


class TripsForMonthResponse(BaseModel):
    """Схема для ответа с поездками за месяц"""
    vehicle_id: str = Field(..., description="ID автомобиля")
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


class GPSCoordinate(BaseModel):
    """GPS координата"""
    lat: float = Field(..., description="Широта", example=43.238949)
    lon: float = Field(..., description="Долгота", example=76.889709)
    altitude: float = Field(..., description="Высота над уровнем моря", example=0.0)
    timestamp: int = Field(..., description="Временная метка", example=0)


class DailyRoute(BaseModel):
    """Маршрут за один день"""
    date: str = Field(..., description="Дата в формате YYYY-MM-DD", example="2024-01-15")
    coordinates: List[GPSCoordinate] = Field(..., description="Координаты за день")


class RouteData(BaseModel):
    """Полные данные маршрута"""
    device_id: str = Field(..., description="ID GPS устройства", example="800153076")
    start_date: str = Field(..., description="Дата начала в ISO формате", example="2024-01-15T14:30:00")
    end_date: str = Field(..., description="Дата окончания в ISO формате", example="2024-01-15T16:30:00")
    total_coordinates: int = Field(..., description="Общее количество координат", example=658)
    daily_routes: List[DailyRoute] = Field(..., description="Маршруты по дням")
    fuel_start: Optional[str] = Field(None, description="Уровень топлива в начале", example="23 л")
    fuel_end: Optional[str] = Field(None, description="Уровень топлива в конце", example="22 л")


class RouteMapData(BaseModel):
    """Данные для отображения маршрута"""
    start_latitude: float = Field(..., description="Широта начальной точки", example=43.238949)
    start_longitude: float = Field(..., description="Долгота начальной точки", example=76.889709)
    end_latitude: Optional[float] = Field(None, description="Широта конечной точки", example=43.245678)
    end_longitude: Optional[float] = Field(None, description="Долгота конечной точки", example=76.901234)
    duration_over_24h: bool = Field(..., description="Длилась ли поездка более 24 часов", example=False)
    route_data: Optional[RouteData] = Field(None, description="Детальные данные маршрута с координатами")


class TripDetailResponse(BaseModel):
    """Детальная информация о поездке"""
    id: str = Field(..., description="ID поездки (sid)")
    vehicle_id: str = Field(..., description="ID автомобиля (sid)")
    vehicle_name: str = Field(..., description="Название автомобиля", example="HAVAL F7x")
    vehicle_plate_number: str = Field(..., description="Госномер", example="422ABK02")
    duration_minutes: int = Field(..., description="Продолжительность в минутах", example=120)
    earnings: int = Field(..., description="Заработок владельца в тенге", example=7500)
    rental_type: str = Field(..., description="Тип тарифа", example="hours", enum=["minutes", "hours", "days"])
    start_time: Optional[str] = Field(None, description="Время начала поездки", example="2024-01-15T14:30:00")
    end_time: Optional[str] = Field(None, description="Время окончания поездки", example="2024-01-15T16:30:00")
    fuel_cost: Optional[int] = Field(None, description="Стоимость топлива в тенге (только для поездок владельца)", example=2250)
    delivery_cost: Optional[int] = Field(None, description="Стоимость доставки в тенге (только для поездок владельца)", example=5000)
    photos: TripPhotos = Field(..., description="Фотографии поездки")
    route_map: RouteMapData = Field(..., description="Данные маршрута для карты")
    mechanic_delivery: Optional[Dict[str, Any]] = Field(None, description="Информация о доставке механика")
    mechanic_inspection: Optional[Dict[str, Any]] = Field(None, description="Информация об осмотре механика")
    
    class Config:
        from_attributes = True


class MyAutosResponse(BaseModel):
    """Ответ для списка автомобилей владельца"""
    cars: List[CarOwnerResponse] = Field(..., description="Список автомобилей владельца с историей поездок")
