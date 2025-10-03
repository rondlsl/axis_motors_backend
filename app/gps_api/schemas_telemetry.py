from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class VehicleTelemetryResponse(BaseModel):
    """Полная телеметрия автомобиля"""
    
    # Основная информация
    imei: str = Field(..., description="IMEI устройства")
    vehicle_id: int = Field(..., description="ID автомобиля")
    car_name: str = Field(..., description="Название автомобиля")
    device_type_id: int = Field(..., description="Тип устройства")
    last_active_time: datetime = Field(..., description="Время последней активности")
    is_online: bool = Field(..., description="Статус онлайн")
    is_moving: bool = Field(..., description="В движении")
    
    # Координаты
    latitude: float = Field(..., description="Широта")
    longitude: float = Field(..., description="Долгота")
    
    # Основные параметры движения
    speed: float = Field(..., description="Скорость движения (км/ч)")
    course: float = Field(..., description="Курс (градусы)")
    altitude: float = Field(..., description="Высота над уровнем моря (м)")
    
    # Спутники
    gps_satellites: int = Field(..., description="Количество GPS спутников")
    glonass_satellites: int = Field(..., description="Количество ГЛОНАСС спутников")
    galileo_satellites: int = Field(..., description="Количество Galileo спутников")
    beidou_satellites: int = Field(..., description="Количество Beidou спутников")
    total_satellites: int = Field(..., description="Общее количество спутников")
    
    # Напряжение
    board_voltage: float = Field(..., description="Бортовое напряжение (В)")
    
    # Двигатель
    engine_rpm: Optional[int] = Field(None, description="Обороты двигателя (об/мин)")
    engine_temperature: Optional[float] = Field(None, description="Температура двигателя (°C)")
    engine_hours: Optional[float] = Field(None, description="Часы работы двигателя")
    is_engine_on: bool = Field(..., description="Двигатель включен")
    
    # Топливо и пробег
    fuel_level: Optional[float] = Field(None, description="Уровень топлива (л)")
    fuel_consumption: Optional[float] = Field(None, description="Расход топлива")
    mileage: Optional[float] = Field(None, description="Пробег (км)")
    
    # Двери
    front_right_door_open: bool = Field(..., description="Передняя правая дверь открыта")
    front_left_door_open: bool = Field(..., description="Передняя левая дверь открыта")
    rear_right_door_open: bool = Field(..., description="Задняя правая дверь открыта")
    rear_left_door_open: bool = Field(..., description="Задняя левая дверь открыта")
    
    # Замки дверей
    front_right_door_locked: bool = Field(..., description="Передняя правая дверь заблокирована")
    front_left_door_locked: bool = Field(..., description="Передняя левая дверь заблокирована")
    rear_right_door_locked: bool = Field(..., description="Задняя правая дверь заблокирована")
    rear_left_door_locked: bool = Field(..., description="Задняя левая дверь заблокирована")
    central_locks_locked: bool = Field(..., description="Центральные замки заблокированы")
    
    # Стекла
    front_right_window_closed: bool = Field(..., description="Переднее правое стекло закрыто")
    front_left_window_closed: bool = Field(..., description="Переднее левое стекло закрыто")
    rear_right_window_closed: bool = Field(..., description="Заднее правое стекло закрыто")
    rear_left_window_closed: bool = Field(..., description="Заднее левое стекло закрыто")
    
    # Капот и багажник
    hood_open: bool = Field(..., description="Капот открыт")
    trunk_open: bool = Field(..., description="Багажник открыт")
    
    # Свет и тормоза
    lights_on: bool = Field(..., description="Фары включены")
    light_auto_mode: bool = Field(..., description="Автоматический режим света")
    handbrake_on: bool = Field(..., description="Ручной тормоз включен")
    brake_pedal_pressed: bool = Field(..., description="Педаль тормоза нажата")
    
    # Дополнительные параметры
    steering_angle: Optional[float] = Field(None, description="Угол поворота руля")
    gas_pedal_position: Optional[float] = Field(None, description="Положение педали газа")
    brake_force: Optional[float] = Field(None, description="Тормозное усилие")
    
    # Безопасность
    driver_seatbelt_fastened: bool = Field(..., description="Ремень водителя пристегнут")
    alarm_active: bool = Field(..., description="Сигнализация активна")
    ignition_on: bool = Field(..., description="Зажигание включено")
    
    # Связь
    gsm_signal: Optional[int] = Field(None, description="Уровень GSM сигнала")
    connection_status_net: Optional[int] = Field(None, description="Статус сетевого соединения")
    connection_status_server1: bool = Field(..., description="Соединение с сервером 1")
    connection_status_server2: bool = Field(..., description="Соединение с сервером 2")
    connection_status_server3: bool = Field(..., description="Соединение с сервером 3")
    
    # Акселерометр
    acceleration_x: Optional[float] = Field(None, description="Ускорение по оси X")
    acceleration_y: Optional[float] = Field(None, description="Ускорение по оси Y")
    acceleration_z: Optional[float] = Field(None, description="Ускорение по оси Z")
    
    # Точность GPS
    hdop: Optional[float] = Field(None, description="Горизонтальная точность позиционирования")
    pdop: Optional[int] = Field(None, description="Позиционная точность")
    
    
    class Config:
        from_attributes = True


class VehicleTelemetryError(BaseModel):
    """Ошибка получения телеметрии"""
    error: str = Field(..., description="Описание ошибки")
    message: str = Field(default="Нет данных", description="Сообщение об ошибке")
