#!/usr/bin/env python3
"""
Скрипт для синхронизации фотографий автомобилей из файловой системы в БД.
1. Очищает поле photos в БД для всех машин
2. Сканирует папки uploads/cars/{plate_number} и заполняет пути к фотографиям

Запуск внутри Docker контейнера:
    docker exec -it <container_name> python sync_car_photos.py

Или через docker-compose:
    docker-compose exec back python sync_car_photos.py

Чтобы узнать имя контейнера:
    docker ps
"""
import sys
import os

# Добавляем путь к приложению
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.config import DATABASE_URL
from app.models.car_model import Car
from app.models.user_model import User 
from app.utils.plate_normalizer import normalize_plate_number
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

# Создаем подключение к БД
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db = SessionLocal()

# Базовый путь к папке с фотографиями
BASE_PHOTOS_DIR = "uploads/cars"


def get_photos_from_dir(plate_number: str) -> list[str]:
    """
    Получает список фотографий из папки по номеру знака
    
    Args:
        plate_number: Номерной знак автомобиля
        
    Returns:
        Список путей к фотографиям (например: ["/uploads/cars/X4/photo1.jpg", ...])
    """
    # Нормализуем номер (приводим к верхнему регистру)
    normalized_plate = normalize_plate_number(plate_number)
    
    # Формируем путь к папке
    photos_dir = os.path.join(BASE_PHOTOS_DIR, normalized_plate)
    
    photos = []
    
    # Проверяем существование папки
    if not os.path.exists(photos_dir):
        return photos
    
    if not os.path.isdir(photos_dir):
        return photos
    
    # Сканируем файлы в папке
    for filename in sorted(os.listdir(photos_dir)):
        file_path = os.path.join(photos_dir, filename)
        
        # Проверяем, что это файл (а не папка)
        if os.path.isfile(file_path):
            # Формируем путь для БД (нормализуем разделители и добавляем ведущий слеш)
            normalized_path = file_path.replace("\\", "/")
            if not normalized_path.startswith("/"):
                normalized_path = "/" + normalized_path
            photos.append(normalized_path)
    
    return photos


def sync_car_photos():
    """
    Основная функция синхронизации фотографий
    """
    print("=" * 60)
    print("Синхронизация фотографий автомобилей")
    print("=" * 60)
    
    # Получаем все автомобили
    cars = db.query(Car).all()
    print(f"\nНайдено автомобилей: {len(cars)}\n")
    
    updated_count = 0
    skipped_count = 0
    
    for car in cars:
        try:
            # Очищаем поле photos в БД
            car.photos = []
            
            # Получаем фотографии из файловой системы
            if car.plate_number:
                photos = get_photos_from_dir(car.plate_number)
                
                if photos:
                    # Обновляем поле photos в БД
                    car.photos = photos
                    updated_count += 1
                    print(f"✓ {car.plate_number} ({car.name}): добавлено {len(photos)} фото")
                    for photo in photos:
                        print(f"    - {photo}")
                else:
                    skipped_count += 1
                    print(f"○ {car.plate_number} ({car.name}): фото не найдено")
            else:
                skipped_count += 1
                print(f"○ ID {car.id} ({car.name}): нет номера знака")
                
        except Exception as e:
            print(f"✗ Ошибка при обработке {car.plate_number or car.id}: {e}")
            db.rollback()
            continue
    
    # Сохраняем изменения
    try:
        db.commit()
        print("\n" + "=" * 60)
        print(f"Синхронизация завершена!")
        print(f"  - Обновлено: {updated_count} автомобилей")
        print(f"  - Пропущено: {skipped_count} автомобилей")
        print("=" * 60)
    except Exception as e:
        db.rollback()
        print(f"\n✗ Ошибка при сохранении в БД: {e}")
        raise


if __name__ == "__main__":
    try:
        sync_car_photos()
    except Exception as e:
        print(f"\n✗ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

