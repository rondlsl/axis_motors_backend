import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.dependencies.database.database import SessionLocal
from app.models.car_model import Car, CarStatus
from app.utils.time_utils import get_local_time, ALMATY_OFFSET

logger = logging.getLogger(__name__)

EXCLUDED_STATUSES = {CarStatus.OWNER, CarStatus.OCCUPIED}

UTC_TZ = timezone.utc


def _to_utc(dt: datetime) -> datetime:
    """Переводим datetime (алматинский) в timezone-aware UTC."""
    if dt.tzinfo is None:
        return (dt - ALMATY_OFFSET).replace(tzinfo=UTC_TZ)
    return dt.astimezone(UTC_TZ)


def _month_start(dt: datetime) -> datetime:
    """Return datetime corresponding to the first day of the month at 00:00."""
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def update_car_availability_snapshot(car: Car, now: Optional[datetime] = None) -> None:
    """
    Пересчитывает накопленные минуты доступности для конкретной машины.
    Работает по принципу «накопительного» таймера: если машина доступна (не OWNER/OCCUPIED),
    добавляем прошедшие минуты к available_minutes. В начале каждого месяца счетчик сбрасывается.
    """
    local_now = now or get_local_time()
    now_utc = _to_utc(local_now)
    month_start_local = _month_start(local_now)
    month_start_utc = _to_utc(month_start_local)

    last_update = _to_utc(car.availability_updated_at) if car.availability_updated_at else month_start_utc
    if last_update < month_start_utc:
        car.available_minutes = 0
        last_update = month_start_utc

    if last_update > now_utc:
        car.availability_updated_at = now_utc
        return

    if car.status in EXCLUDED_STATUSES:
        car.availability_updated_at = now_utc
        return

    delta_seconds = (now_utc - last_update).total_seconds()
    if delta_seconds < 60:
        return

    delta_minutes = int(delta_seconds // 60)
    if delta_minutes <= 0:
        return

    car.available_minutes += delta_minutes
    month_total_minutes = int((now_utc - month_start_utc).total_seconds() // 60)
    if car.available_minutes > month_total_minutes:
        car.available_minutes = month_total_minutes

    next_update = last_update + timedelta(minutes=delta_minutes)
    car.availability_updated_at = next_update if next_update > now_utc else now_utc


def update_cars_availability_job() -> None:
    """
    Планировщик: обновляет таймер доступности для всех машин.
    Запускается периодически (см. main.py).
    """
    db: Session = SessionLocal()
    try:
        now = get_local_time()
        cars = db.query(Car).all()
        for car in cars:
            update_car_availability_snapshot(car, now)
        db.commit()
    except Exception as exc:
        logger.error(f"Ошибка при обновлении доступности автомобилей: {exc}")
        db.rollback()
    finally:
        db.close()
