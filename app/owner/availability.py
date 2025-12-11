import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.dependencies.database.database import SessionLocal
from app.models.car_model import Car, CarStatus
from app.utils.time_utils import get_local_time

logger = logging.getLogger(__name__)

EXCLUDED_STATUSES = {CarStatus.OWNER, CarStatus.OCCUPIED}


def _month_start(dt: datetime) -> datetime:
    """Return datetime corresponding to the first day of the month at 00:00."""
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def update_car_availability_snapshot(car: Car, now: Optional[datetime] = None) -> None:
    """
    Пересчитывает накопленные минуты доступности для конкретной машины.
    Работает по принципу «накопительного» таймера: если машина доступна (не OWNER/OCCUPIED),
    добавляем прошедшие минуты к available_minutes. В начале каждого месяца счетчик сбрасывается.
    """
    now = now or get_local_time()
    month_start = _month_start(now)

    last_update = car.availability_updated_at or month_start
    if last_update < month_start:
        car.available_minutes = 0
        last_update = month_start

    if last_update > now:
        car.availability_updated_at = now
        return

    # Если машина в статусе, когда не должна копить минуты, просто помечаем время
    if car.status in EXCLUDED_STATUSES:
        car.availability_updated_at = now
        return

    delta_seconds = (now - last_update).total_seconds()
    if delta_seconds < 60:
        # Ждем пока накапает хотя бы минута, чтобы избежать дробных значений
        return

    delta_minutes = int(delta_seconds // 60)
    if delta_minutes <= 0:
        return

    car.available_minutes += delta_minutes
    month_total_minutes = int((now - month_start).total_seconds() // 60)
    if car.available_minutes > month_total_minutes:
        car.available_minutes = month_total_minutes

    # Сохраняем момент, когда в последний раз учли доступность (без остатка < 1 мин)
    car.availability_updated_at = last_update + timedelta(minutes=delta_minutes)
    if car.availability_updated_at < now:
        car.availability_updated_at = now


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
