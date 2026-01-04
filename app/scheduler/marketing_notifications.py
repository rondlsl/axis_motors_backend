"""
Маркетинговые уведомления через scheduled tasks

- Запрашиваются только user_id, не полные объекты
- Фильтруются пользователи с push токенами
- Уменьшен BATCH_SIZE и увеличен BATCH_DELAY
- Запуск в background для неблокирующей работы
"""
import asyncio
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, extract
from typing import List
import logging

from app.dependencies.database.database import SessionLocal
from app.models.user_model import User
from app.models.car_model import Car
from app.models.user_device_model import UserDevice

from app.push.utils import send_localized_notification_to_user_async, get_global_push_notification_semaphore
from app.utils.time_utils import get_local_time

logger = logging.getLogger(__name__)

BATCH_SIZE = 10  # Уменьшено с 20 для снижения нагрузки на БД
BATCH_DELAY = 5.0  # Увеличено с 3.0 для более плавной обработки
MAX_RETRIES = 3  # Количество попыток при ошибках БД
RETRY_DELAY = 1.0  # Задержка перед повтором (секунды)  


# Государственные праздники Казахстана (месяц, день, notification_key)
KZ_HOLIDAYS = [
    (1, 1, "new_year"),   # Новый год
    (1, 2, "new_year"),   # Новый год (второй день)
    (1, 7, "christmas"),  # Рождество
    (3, 8, "womens_day"),  # Международный женский день
    (3, 21, "nauryz"),  # Наурыз
    (3, 22, "nauryz"),  # Наурыз (второй день)
    (3, 23, "nauryz"),  # Наурыз (третий день)
    (5, 1, "unity_day"),   # День единства народа Казахстана
    (5, 7, "defender_day"),   # День защитника Отечества
    (5, 9, "victory_day"),   # День Победы
    (7, 6, "capital_day"),   # День столицы
    (8, 30, "constitution_day"),  # День Конституции
    (10, 25, "republic_day"), # День Республики
    (12, 16, "independence_day"), # День Независимости
    (12, 17, "independence_day"), # День Независимости (второй день)
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
        
        user_ids_result = (
            db.query(User.id)
            .outerjoin(UserDevice, User.id == UserDevice.user_id)
            .filter(
                extract('month', User.birth_date) == today_month,
                extract('day', User.birth_date) == today_day,
                User.is_active.is_(True),
                or_(
                    User.fcm_token.isnot(None),
                    and_(
                        UserDevice.fcm_token.isnot(None),
                        UserDevice.is_active.is_(True),
                        UserDevice.revoked_at.is_(None)
                    )
                )
            )
            .distinct()
            .all()
        )
        
        if not user_ids_result:
            return
        
        user_ids = [uid[0] for uid in user_ids_result]
        logger.info(f"Дни рождения: {len(user_ids)} пользователей с push токенами")
        
        db.close()
        db = None
        
        sent_count = await send_notifications_in_batches(user_ids, "birthday")
        
        if sent_count > 0:
            logger.info(f"Отправлено {sent_count} уведомлений о днях рождения")
        
    except Exception as e:
        logger.error(f"Ошибка при проверке дней рождения: {e}")
    finally:
        if db:
            db.close()


async def check_holidays():
    """
    Проверка государственных праздников и отправка массовых уведомлений.
    ОПТИМИЗИРОВАНО: Запрашиваются только user_id пользователей с push токенами.
    """
    db = SessionLocal()
    try:
        today = get_local_time()
        today_month = today.month
        today_day = today.day
        
        # Проверяем, является ли сегодня праздником и получаем notification_key
        notification_key = None
        for month, day, key in KZ_HOLIDAYS:
            if today_month == month and today_day == day:
                notification_key = key
                break
        
        if not notification_key:
            return
        
        user_ids_result = (
            db.query(User.id)
            .outerjoin(UserDevice, User.id == UserDevice.user_id)
            .filter(
                User.is_active.is_(True),
                or_(
                    User.fcm_token.isnot(None),
                    and_(
                        UserDevice.fcm_token.isnot(None),
                        UserDevice.is_active.is_(True),
                        UserDevice.revoked_at.is_(None)
                    )
                )
            )
            .distinct()
            .all()
        )
        
        if not user_ids_result:
            return
        
        user_ids = [uid[0] for uid in user_ids_result]
        logger.info(f"Праздничные уведомления ({notification_key}): {len(user_ids)} пользователей с push токенами")
        
        sent_count = await send_notifications_in_batches(user_ids, notification_key)
        
        if sent_count > 0:
            logger.info(f"Отправлено {sent_count} праздничных уведомлений '{notification_key}'")
        
    except Exception as e:
        logger.error(f"Ошибка при проверке праздников: {e}")
    finally:
        db.close()


async def check_weekend_promotions():
    """
    Проверка пятницы вечером и понедельника утром для промо-уведомлений.
    Использует get_local_time() для проверки алматинского времени (GMT+5).
    
    - Запрашиваются только user_id, не полные объекты
    - Фильтруются пользователи с push токенами
    - Запуск в background для неблокирующей работы
    """
    db = SessionLocal()
    try:
        now = get_local_time()  # Алматинское время (GMT+5)
        weekday = now.weekday()  # 0 = понедельник, 4 = пятница
        hour = now.hour
        
        notification_key = None
        
        # Пятница 19:00
        if weekday == 4 and hour == 19:
            notification_key = "friday_evening"
        # Понедельник 8:00
        elif weekday == 0 and hour == 8:
            notification_key = "monday_morning"
        
        if not notification_key:
            return
        
        user_ids_result = (
            db.query(User.id)
            .outerjoin(UserDevice, User.id == UserDevice.user_id)
            .filter(
                User.is_active.is_(True),
                or_(
                    User.fcm_token.isnot(None),
                    and_(
                        UserDevice.fcm_token.isnot(None),
                        UserDevice.is_active.is_(True),
                        UserDevice.revoked_at.is_(None)
                    )
                )
            )
            .distinct()
            .all()
        )
        
        if not user_ids_result:
            logger.info(f"Нет пользователей с push токенами для {notification_key}")
            return
        
        user_ids = [uid[0] for uid in user_ids_result]
        logger.info(f"{notification_key}: {len(user_ids)} пользователей с push токенами")
        
        # Закрываем сессию БД ДО отправки уведомлений
        db.close()
        db = None
        
        sent_count = await send_notifications_in_batches(user_ids, notification_key)
        
        if sent_count > 0:
            logger.info(f"Отправлено {sent_count} уведомлений '{notification_key}'")
        
    except Exception as e:
        logger.error(f"Ошибка при проверке промо-уведомлений: {e}")
    finally:
        if db:
            db.close()


async def check_new_cars():
    """Проверка появления новых автомобилей (по дате создания) и рассылка уведомлений."""
    db = SessionLocal()
    try:
        cutoff = get_local_time() - timedelta(hours=1)
        
        new_cars_exist = (
            db.query(Car.id)
            .filter(
                Car.created_at != None,
                Car.created_at >= cutoff
            )
            .first()
        )

        if not new_cars_exist:
            return

        user_ids_result = (
            db.query(User.id)
            .outerjoin(UserDevice, User.id == UserDevice.user_id)
            .filter(
                User.is_active.is_(True),
                or_(
                    User.fcm_token.isnot(None),
                    and_(
                        UserDevice.fcm_token.isnot(None),
                        UserDevice.is_active.is_(True),
                        UserDevice.revoked_at.is_(None)
                    )
                )
            )
            .distinct()
            .all()
        )

        if not user_ids_result:
            return

        user_ids = [uid[0] for uid in user_ids_result]
        logger.info(f"Новые автомобили: {len(user_ids)} пользователей с push токенами")
        
        db.close()
        db = None
        
        sent_count = await send_notifications_in_batches(user_ids, "new_car_available")

        if sent_count > 0:
            logger.info(f"Отправлено {sent_count} уведомлений о новых автомобилях")
    except Exception as e:
        logger.error(f"Ошибка при проверке новых автомобилей: {e}")
    finally:
        if db:
            db.close()
