from typing import Optional

from app.models.car_model import Car
from app.admin.schemas import CarDetailSchema


def status_display(status: Optional[str]) -> str:
    return {
        "FREE": "Свободно",
        "PENDING": "Ожидает механика",
        "IN_USE": "В аренде",
        "SERVICE": "На обслуживании",
        "DELIVERING": "В доставке",
        "DELIVERING_IN_PROGRESS": "Доставлено",
        "COMPLETED": "Завершено",
        "RESERVED": "Зарезервирована",
        "SCHEDULED": "Забронирована заранее",
        "OWNER": "У владельца",
        "OCCUPIED": "Занята",
    }.get(status or "", status or "")


def car_to_detail_schema(car: Car) -> CarDetailSchema:
    return CarDetailSchema(
        id=car.id,
        name=car.name,
        plate_number=car.plate_number,
        engine_volume=car.engine_volume,
        year=car.year,
        drive_type=car.drive_type,
        drive_type_display=str(car.drive_type) if car.drive_type is not None else None,
        body_type=str(car.body_type) if car.body_type else "",
        body_type_display=str(car.body_type) if car.body_type else "",
        transmission_type=str(car.transmission_type) if car.transmission_type else None,
        transmission_type_display=str(car.transmission_type) if car.transmission_type else None,
        status=car.status,
        status_display=status_display(car.status),
        photos=car.photos or [],
        description=car.description,
        latitude=car.latitude,
        longitude=car.longitude,
        fuel_level=car.fuel_level,
        mileage=car.mileage,
        course=car.course,
        auto_class=str(car.auto_class) if car.auto_class else "",
        price_per_minute=car.price_per_minute,
        price_per_hour=car.price_per_hour,
        price_per_day=car.price_per_day,
        owner_id=car.owner_id,
        current_renter_id=car.current_renter_id,
        available_minutes=None,
        gps_id=car.gps_id,
        gps_imei=car.gps_imei,
    )


