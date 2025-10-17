from typing import Optional
from app.models.car_model import Car
from app.admin.cars.schemas import CarDetailSchema


def status_display(status: Optional[str]) -> str:
    """Преобразует статус автомобиля в читаемый вид"""
    return {
        "FREE": "Свободно",
        "PENDING": "Ожидает механика",
        "IN_USE": "В аренде",
        "SERVICE": "На тех обслуживании",
        "DELIVERING": "В доставке",
        "DELIVERING_IN_PROGRESS": "Доставлено",
        "COMPLETED": "Завершено",
        "SERVICE": "На обслуживании",
        "RESERVED": "Зарезервирована",
        "SCHEDULED": "Забронирована заранее",
        "OWNER": "У владельца",
        "OCCUPIED": "Занята",
    }.get(status or "", status or "")


def car_to_detail_schema(car: Car) -> CarDetailSchema:
    """Преобразует модель Car в CarDetailSchema"""
    return CarDetailSchema(
        id=car.id,
        name=car.name,
        plate_number=car.plate_number,
        engine_volume=car.engine_volume,
        year=car.year,
        drive_type=car.drive_type,
        drive_type_display=_get_drive_type_display(car.drive_type),
        body_type=car.body_type.value if car.body_type else "UNKNOWN",
        body_type_display=car.body_type.value if car.body_type else "Не указан",
        transmission_type=car.transmission_type.value if car.transmission_type else None,
        transmission_type_display=car.transmission_type.value if car.transmission_type else None,
        status=car.status or "FREE",
        status_display=status_display(car.status),
        photos=car.photos or [],
        description=car.description,
        latitude=car.latitude,
        longitude=car.longitude,
        fuel_level=car.fuel_level,
        mileage=car.mileage,
        course=car.course,
        auto_class=car.auto_class.value if car.auto_class else "UNKNOWN",
        price_per_minute=car.price_per_minute,
        price_per_hour=car.price_per_hour,
        price_per_day=car.price_per_day,
        owner_id=car.owner_id,
        current_renter_id=car.current_renter_id,
        available_minutes=None,  # Будет рассчитано отдельно
        gps_id=car.gps_id,
        gps_imei=car.gps_imei,
        vin=car.vin,
        color=car.color,
    )


def _get_drive_type_display(drive_type: Optional[int]) -> Optional[str]:
    """Преобразует тип привода в читаемый вид"""
    if drive_type is None:
        return None
    return {
        1: "FWD (Передний привод)",
        2: "RWD (Задний привод)", 
        3: "AWD (Полный привод)",
        4: "4WD (Полный привод)",
    }.get(drive_type, f"Неизвестный ({drive_type})")
