"""
Задачи для обработки забронированных заранее автомобилей
"""
from app.core.logging_config import get_logger
logger = get_logger(__name__)

import asyncio
from datetime import datetime
from sqlalchemy.orm import Session
from app.dependencies.database.database import get_db
from app.rent.utils.scheduler import process_scheduled_bookings


async def process_scheduled_bookings_task():
    """
    Задача для периодической обработки забронированных заранее автомобилей
    Запускается каждые 5 минут
    """
    while True:
        try:
            # Получаем сессию базы данных
            db = next(get_db())
            
            # Обрабатываем забронированные заранее автомобили
            result = process_scheduled_bookings(db)
            
            logger.info(f"[{datetime.now()}] Обработано забронированных заранее автомобилей:")
            logger.debug(f"  - Активировано: {result['activated_bookings']}")
            logger.debug(f"  - Отменено: {result['cancelled_bookings']}")
            logger.debug(f"  - Завершено: {result['completed_bookings']}")
            
        except Exception as e:
            logger.info(f"[{datetime.now()}] Ошибка при обработке забронированных заранее автомобилей: {e}")
        
        finally:
            # Закрываем сессию
            if 'db' in locals():
                db.close()
        
        # Ждем 5 минут до следующей проверки
        await asyncio.sleep(300)  # 300 секунд = 5 минут


def start_scheduler():
    """
    Запускает планировщик задач
    """
    asyncio.create_task(process_scheduled_bookings_task())
