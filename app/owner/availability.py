import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session, object_session

from app.dependencies.database.database import SessionLocal
from app.models.car_model import Car, CarStatus, CarAvailabilityHistory
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
        db = object_session(car)
        if db:
            prev_month_date = month_start_local - timedelta(days=1)
            
            existing_history = db.query(CarAvailabilityHistory).filter(
                CarAvailabilityHistory.car_id == car.id,
                CarAvailabilityHistory.year == prev_month_date.year,
                CarAvailabilityHistory.month == prev_month_date.month
            ).first()
            
            if not existing_history:
                history = CarAvailabilityHistory(
                    car_id=car.id,
                    year=prev_month_date.year,
                    month=prev_month_date.month,
                    available_minutes=car.available_minutes,
                    created_at=get_local_time()
                )
                db.add(history)
        
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


CAR_AVAILABILITY_START = {
    "890AVB09": datetime(2025, 11, 1),
    "888DON07": datetime(2025, 12, 1),
    "455BNI02": datetime(2025, 12, 1),
    "959AWM02": datetime(2025, 11, 1),
    "666AZV02": datetime(2025, 9, 1),
    "195BGY02": datetime(2025, 12, 28),  
}


def backfill_availability_history() -> None:
    """
    Запускается при старте приложения.
    1. Заполняет car_availability_history за прошлые месяцы, если данных ещё нет.
    2. Пересчитывает available_minutes в таблице cars для текущего месяца.
    """
    from calendar import monthrange
    from app.models.history_model import RentalHistory, RentalStatus
    
    db: Session = SessionLocal()
    try:
        now = get_local_time()
        logger.info("Backfill availability history: начало проверки...")
        
        for plate_number, start_date in CAR_AVAILABILITY_START.items():
            car = db.query(Car).filter(Car.plate_number == plate_number).first()
            if not car:
                continue
            
            current = start_date
            while current < now:
                year, month = current.year, current.month
                
                is_current_month = (year == now.year and month == now.month)
                
                if is_current_month:
                    days = monthrange(year, month)[1]
                    month_start = datetime(year, month, 1)
                    
                    rentals = db.query(RentalHistory).filter(
                        RentalHistory.car_id == car.id,
                        RentalHistory.rental_status == RentalStatus.COMPLETED,
                        RentalHistory.user_id != car.owner_id,
                        RentalHistory.start_time.isnot(None),
                        RentalHistory.end_time.isnot(None),
                        RentalHistory.end_time >= month_start,
                        RentalHistory.start_time <= now
                    ).all()
                    
                    client_rental_minutes = 0
                    for r in rentals:
                        rental_start = max(r.start_time, month_start)
                        rental_end = min(r.end_time, now)
                        if rental_end > rental_start:
                            client_rental_minutes += int((rental_end - rental_start).total_seconds() / 60)
                    
                    minutes_since_month_start = int((now - month_start).total_seconds() / 60)
                    available_minutes = max(0, minutes_since_month_start - client_rental_minutes)
                    
                    car.available_minutes = available_minutes
                    car.availability_updated_at = now
                    logger.info(f"Backfill CURRENT: {plate_number} = {available_minutes} мин")
                    
                    if month == 12:
                        current = datetime(year + 1, 1, 1)
                    else:
                        current = datetime(year, month + 1, 1)
                    continue
                
                existing = db.query(CarAvailabilityHistory).filter(
                    CarAvailabilityHistory.car_id == car.id,
                    CarAvailabilityHistory.year == year,
                    CarAvailabilityHistory.month == month
                ).first()
                
                if not existing:
                    days = monthrange(year, month)[1]
                    month_total_minutes = days * 24 * 60
                    
                    start_dt = datetime(year, month, 1)
                    end_dt = datetime(year, month, days, 23, 59, 59)
                    
                    rentals = db.query(RentalHistory).filter(
                        RentalHistory.car_id == car.id,
                        RentalHistory.rental_status == RentalStatus.COMPLETED,
                        RentalHistory.user_id != car.owner_id,
                        RentalHistory.start_time.isnot(None),
                        RentalHistory.end_time.isnot(None),
                        RentalHistory.end_time >= start_dt,
                        RentalHistory.start_time <= end_dt
                    ).all()
                    
                    client_rental_minutes = 0
                    for r in rentals:
                        rental_start = max(r.start_time, start_dt)
                        rental_end = min(r.end_time, end_dt)
                        if rental_end > rental_start:
                            client_rental_minutes += int((rental_end - rental_start).total_seconds() / 60)
                    
                    available_minutes = max(0, month_total_minutes - client_rental_minutes)
                    
                    history = CarAvailabilityHistory(
                        car_id=car.id,
                        year=year,
                        month=month,
                        available_minutes=available_minutes
                    )
                    db.add(history)
                    logger.info(f"Backfill: {plate_number} {month:02d}/{year} = {available_minutes} мин")
                
                if month == 12:
                    current = datetime(year + 1, 1, 1)
                else:
                    current = datetime(year, month + 1, 1)
        
        db.commit()
        logger.info("Backfill availability history: завершено")
        
    except Exception as exc:
        logger.error(f"Ошибка backfill availability history: {exc}")
        db.rollback()
    finally:
        db.close()
