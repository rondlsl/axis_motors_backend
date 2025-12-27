"""
Скрипт для заполнения car_availability_history за прошлые месяцы.

Логика:
1. Для каждой машины смотрим месяцы с момента доступности
2. Проверяем, есть ли уже записи в car_availability_history
3. Если нет - считаем доступные минуты на основе:
   - Общее количество минут в месяце
   - Минус время когда машина была в аренде НЕ у владельца (user_id != owner_id)
   - Время аренды владельцем НЕ вычитаем (владелец может пользоваться)

Запуск: python -m scripts.backfill_availability_history
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from calendar import monthrange
from sqlalchemy import and_

from app.dependencies.database.database import SessionLocal
from app.models.car_model import Car, CarAvailabilityHistory
from app.models.history_model import RentalHistory, RentalStatus


CAR_AVAILABILITY_START = {
    "890AVB09": datetime(2025, 11, 1),  # Huanchi - с 1 ноября 2025
    "888DON07": datetime(2025, 12, 1),  # Гелик - с 1 декабря 2025
    "455BNI02": datetime(2025, 12, 1),  # BYD - с 1 декабря 2025
    "959AWM02": datetime(2025, 11, 1),  # Туксон - с 1 ноября 2025
    "666AZV02": datetime(2025, 9, 1),   # Мерс - с 1 сентября 2025
}


def get_month_minutes(year: int, month: int) -> int:
    """Возвращает количество минут в месяце"""
    days = monthrange(year, month)[1]
    return days * 24 * 60


def calculate_rental_minutes_by_clients(db, car_id, owner_id, year: int, month: int) -> int:
    """
    Считает сколько минут машина была в аренде у КЛИЕНТОВ (не владельца) за месяц.
    """
    start_dt = datetime(year, month, 1)
    end_dt = datetime(year, month, monthrange(year, month)[1], 23, 59, 59)
    
    rentals = db.query(RentalHistory).filter(
        RentalHistory.car_id == car_id,
        RentalHistory.rental_status == RentalStatus.COMPLETED,
        RentalHistory.user_id != owner_id,  # Исключаем поездки владельца
        RentalHistory.start_time.isnot(None),
        RentalHistory.end_time.isnot(None),
        RentalHistory.end_time >= start_dt,
        RentalHistory.start_time <= end_dt
    ).all()
    
    total_minutes = 0
    for r in rentals:
        rental_start = max(r.start_time, start_dt)
        rental_end = min(r.end_time, end_dt)
        
        if rental_end > rental_start:
            delta = (rental_end - rental_start).total_seconds() / 60
            total_minutes += int(delta)
    
    return total_minutes


def backfill_car_availability(db, car: Car, start_date: datetime) -> list:
    """Заполняет историю доступности для одной машины"""
    results = []
    now = datetime.now()
    
    current = start_date
    while current < now:
        year, month = current.year, current.month
        
        if year == now.year and month == now.month:
            current = datetime(year + (1 if month == 12 else 0), (month % 12) + 1, 1)
            continue
        
        existing = db.query(CarAvailabilityHistory).filter(
            CarAvailabilityHistory.car_id == car.id,
            CarAvailabilityHistory.year == year,
            CarAvailabilityHistory.month == month
        ).first()
        
        if existing:
            results.append({
                "year": year,
                "month": month,
                "status": "exists",
                "available_minutes": existing.available_minutes
            })
        else:
            month_total_minutes = get_month_minutes(year, month)
            
            client_rental_minutes = calculate_rental_minutes_by_clients(
                db, car.id, car.owner_id, year, month
            )
            
            available_minutes = month_total_minutes - client_rental_minutes
            if available_minutes < 0:
                available_minutes = 0
            
            history = CarAvailabilityHistory(
                car_id=car.id,
                year=year,
                month=month,
                available_minutes=available_minutes
            )
            db.add(history)
            
            results.append({
                "year": year,
                "month": month,
                "status": "created",
                "month_total": month_total_minutes,
                "client_rental": client_rental_minutes,
                "available_minutes": available_minutes
            })
        
        if month == 12:
            current = datetime(year + 1, 1, 1)
        else:
            current = datetime(year, month + 1, 1)
    
    return results


def main():
    db = SessionLocal()
    
    try:
        print("=" * 60)
        print("Backfill Car Availability History")
        print("=" * 60)
        
        for plate_number, start_date in CAR_AVAILABILITY_START.items():
            car = db.query(Car).filter(Car.plate_number == plate_number).first()
            
            if not car:
                print(f"\n❌ Машина {plate_number} не найдена")
                continue
            
            print(f"\n🚗 {car.name} ({plate_number})")
            print(f"   Owner ID: {car.owner_id}")
            print(f"   Доступна с: {start_date.strftime('%d.%m.%Y')}")
            
            results = backfill_car_availability(db, car, start_date)
            
            for r in results:
                if r["status"] == "exists":
                    print(f"   {r['month']:02d}/{r['year']}: уже есть ({r['available_minutes']} мин)")
                else:
                    print(f"   {r['month']:02d}/{r['year']}: создано ({r['available_minutes']} мин доступно, {r['client_rental']} мин аренды клиентами)")
        
        db.commit()
        print("\n✅ Готово!")
        
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
