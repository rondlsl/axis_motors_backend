#!/usr/bin/env python3
"""
Скрипт для обновления transmission_type для существующих машин
Запускать после применения миграции на сервере
"""

import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.car_model import Car, TransmissionType

# Настройка подключения к БД
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/azv_motors")

def update_transmission_types():
    """Обновляет transmission_type для существующих машин"""
    
    # Создаем подключение к БД
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    db = SessionLocal()
    
    try:
        # Получаем все машины
        cars = db.query(Car).all()
        
        print(f"Найдено {len(cars)} машин для обновления")
        
        # Обновляем каждую машину
        for car in cars:
            print(f"Обновляем машину ID {car.id}: {car.name}")
            
            # Определяем тип коробки передач на основе названия машины
            car_name_lower = car.name.lower()
            
            if 'cla45s' in car_name_lower or 'mercedes' in car_name_lower:
                # MB CLA45s - обычно автоматическая
                car.transmission_type = TransmissionType.AUTOMATIC
            elif 'hongqi' in car_name_lower or 'electric' in car_name_lower:
                # Hongqi e-qm5 - электрическая, обычно автоматическая
                car.transmission_type = TransmissionType.AUTOMATIC
            else:
                # По умолчанию автоматическая
                car.transmission_type = TransmissionType.AUTOMATIC
            
            print(f"  -> Установлен тип: {car.transmission_type.value}")
        
        # Сохраняем изменения
        db.commit()
        print("✅ Все машины успешно обновлены!")
        
    except Exception as e:
        print(f"❌ Ошибка при обновлении: {e}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    print("🚗 Обновление типов коробки передач для существующих машин...")
    update_transmission_types()
    print("🎉 Готово!")
