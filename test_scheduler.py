#!/usr/bin/env python3
"""
Скрипт для проверки работы планировщика обновления данных автомобилей
"""
import sys
sys.path.append('/app')

from app.dependencies.database.database import get_db
from app.models.car_model import Car
from sqlalchemy.orm import Session
from datetime import datetime

def check_car_data():
    """Проверяем данные автомобилей в БД"""
    db_gen = get_db()
    db = next(db_gen)
    
    try:
        cars = db.query(Car).all()
        print(f"=== Данные автомобилей в БД ({datetime.now().strftime('%H:%M:%S')}) ===")
        
        for car in cars:
            print(f"🚗 {car.name} (ID: {car.id})")
            print(f"   GPS ID: {car.gps_id}")
            print(f"   Координаты: {car.latitude}, {car.longitude}")
            print(f"   Топливо: {car.fuel_level}")
            print(f"   Пробег: {car.mileage}")
            print(f"   Статус: {car.status}")
            print("---")
            
        return len(cars)
    except Exception as e:
        print(f"Ошибка при проверке данных: {e}")
        return 0
    finally:
        db.close()

if __name__ == "__main__":
    count = check_car_data()
    print(f"Всего автомобилей в БД: {count}")
