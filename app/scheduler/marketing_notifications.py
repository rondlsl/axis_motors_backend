"""
Маркетинговые уведомления через scheduled tasks
"""
import asyncio
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, extract
from typing import List

from app.dependencies.database.database import SessionLocal
from app.models.user_model import User
from app.models.car_model import Car

from app.push.utils import send_localized_notification_to_user_async, get_global_push_notification_semaphore
from app.utils.time_utils import get_local_time

BATCH_SIZE = 20  # Меньший размер батча для более плавной отправки
BATCH_DELAY = 3.0  # Увеличена задержка между батчами
MAX_RETRIES = 3  # Количество попыток при ошибках БД
RETRY_DELAY = 1.0  # Задержка перед повтором (секунды)  


# Государственные праздники (месяц, день)
KZ_HOLIDAYS = [
    (1, 1),   # Новый год
    (1, 2),   # Новый год (второй день)
    (1, 7),   # Рождество
    (3, 8),   # Международный женский день
    (3, 21),  # Наурыз
    (3, 22),  # Наурыз (второй день)
    (3, 23),  # Наурыз (третий день)
    (5, 1),   # День единства народа Казахстана
    (5, 7),   # День защитника Отечества
    (5, 9),   # День Победы
    (6, 6),   # День столицы
    (7, 6),   # День столицы (второй день)
    (8, 30),  # День Конституции
    (12, 1),  # День Первого Президента
    (12, 16), # День Независимости
    (12, 17), # День Независимости (второй день)
]


async def send_notifications_in_batches(user_ids: List, notification_key: str):
    """Отправляет уведомления батчами с ограничением параллелизма через глобальный семафор и retry"""
    sent_count = 0
    # Используем глобальный семафор для координации со всеми задачами
    semaphore = get_global_push_notification_semaphore()
    
    async def send_with_retry(user_id, retry_count=0):
        """Отправка с повторными попытками при ошибках БД"""
        async with semaphore:
            try:
                await send_localized_notification_to_user_async(
                    user_id,
                    notification_key,
                    notification_key
                )
                return True
            except Exception as e:
                error_str = str(e)
                # Если это ошибка БД (QueuePool, connection), пробуем повторить
                is_db_error = "QueuePool" in error_str or "connection" in error_str.lower() or "timeout" in error_str.lower()
                
                if is_db_error and retry_count < MAX_RETRIES:
                    # Экспоненциальная задержка перед повтором
                    delay = RETRY_DELAY * (2 ** retry_count)
                    await asyncio.sleep(delay)
                    return await send_with_retry(user_id, retry_count + 1)
                else:
                    # Не логируем ошибки QueuePool после всех попыток - они ожидаемы
                    if not is_db_error:
                        print(f"Ошибка отправки уведомления пользователю {user_id}: {e}")
                    return False
    
    # Разбиваем на батчи
    for i in range(0, len(user_ids), BATCH_SIZE):
        batch = user_ids[i:i + BATCH_SIZE]
        batch_tasks = [send_with_retry(user_id) for user_id in batch]
        results = await asyncio.gather(*batch_tasks, return_exceptions=True)
        sent_count += sum(1 for r in results if r is True)
        
        # Задержка между батчами, чтобы не перегружать систему и дать БД освободить соединения
        if i + BATCH_SIZE < len(user_ids):
            await asyncio.sleep(BATCH_DELAY)
    
    return sent_count


async def check_birthdays():
    """Проверка дней рождения пользователей и отправка уведомлений"""
    db = SessionLocal()
    try:
        today = get_local_time()
        today_month = today.month
        today_day = today.day
        
        # Находим пользователей с днем рождения сегодня
        users = db.query(User).filter(
            extract('month', User.birth_date) == today_month,
            extract('day', User.birth_date) == today_day,
            User.is_active.is_(True)
        ).all()
        
        if not users:
            return
        
        user_ids = [user.id for user in users]
        sent_count = await send_notifications_in_batches(user_ids, "birthday")
        
        if sent_count > 0:
            print(f"Отправлено {sent_count} уведомлений о днях рождения")
        
    except Exception as e:
        print(f"Ошибка при проверке дней рождения: {e}")
    finally:
        db.close()


async def check_holidays():
    """Проверка государственных праздников и отправка массовых уведомлений"""
    db = SessionLocal()
    try:
        today = get_local_time()
        today_month = today.month
        today_day = today.day
        
        # Проверяем, является ли сегодня праздником
        is_holiday = (today_month, today_day) in KZ_HOLIDAYS
        
        if not is_holiday:
            return
        
        # Находим всех активных пользователей
        users = db.query(User).filter(
            User.is_active.is_(True)
        ).all()
        
        if not users:
            return
        
        user_ids = [user.id for user in users]
        sent_count = await send_notifications_in_batches(user_ids, "holiday_greeting")
        
        if sent_count > 0:
            print(f"Отправлено {sent_count} праздничных уведомлений")
        
    except Exception as e:
        print(f"Ошибка при проверке праздников: {e}")
    finally:
        db.close()


async def check_weekend_promotions():
    """
    Проверка пятницы вечером и понедельника утром для промо-уведомлений.
    Использует get_local_time() для проверки алматинского времени (GMT+5).
    Cron jobs настроены на запуск в нужное время, но проверка внутри функции
    гарантирует правильность даже при рассинхронизации.
    """
    db = SessionLocal()
    try:
        now = get_local_time()  # Алматинское время (GMT+5)
        weekday = now.weekday()  # 0 = понедельник, 4 = пятница
        hour = now.hour
        
        # Пятница 19:00
        if weekday == 4 and hour == 19:
            users = db.query(User).filter(
                User.is_active.is_(True)
            ).all()
            
            if not users:
                return
            
            user_ids = [user.id for user in users]
            sent_count = await send_notifications_in_batches(user_ids, "friday_evening")
            
            if sent_count > 0:
                print(f"Отправлено {sent_count} уведомлений 'Пятница вечер'")
        
        # Понедельник 8:00
        elif weekday == 0 and hour == 8:
            users = db.query(User).filter(
                User.is_active.is_(True)
            ).all()
            
            if not users:
                return
            
            user_ids = [user.id for user in users]
            sent_count = await send_notifications_in_batches(user_ids, "monday_morning")
            
            if sent_count > 0:
                print(f"Отправлено {sent_count} уведомлений 'Понедельник утро'")
        
    except Exception as e:
        print(f"Ошибка при проверке промо-уведомлений: {e}")
    finally:
        db.close()


async def check_new_cars():
    """Проверка появления новых автомобилей (по дате создания) и рассылка уведомлений."""
    db = SessionLocal()
    try:
        cutoff = get_local_time() - timedelta(hours=1)
        new_cars = (
            db.query(Car)
            .filter(
                Car.created_at != None,
                Car.created_at >= cutoff
            )
            .all()
        )

        if not new_cars:
            return

        users = db.query(User).filter(
            User.is_active.is_(True)
        ).all()

        if not users:
            return

        user_ids = [user.id for user in users]
        sent_count = await send_notifications_in_batches(user_ids, "new_car_available")

        if sent_count > 0:
            print(f"Отправлено {sent_count} уведомлений о новых автомобилях")
    except Exception as e:
        print(f"Ошибка при проверке новых автомобилей: {e}")
    finally:
        db.close()
