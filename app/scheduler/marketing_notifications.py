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

from app.push.utils import send_localized_notification_to_user
from app.utils.time_utils import get_local_time


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
            User.fcm_token.isnot(None),
            User.is_active == True
        ).all()
        
        sent_count = 0
        for user in users:
            try:
                asyncio.create_task(
                    send_localized_notification_to_user(
                        db,
                        user.id,
                        "birthday",
                        "birthday"
                    )
                )
                sent_count += 1
            except Exception as e:
                print(f"Ошибка отправки уведомления о дне рождения пользователю {user.id}: {e}")
        
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
        
        # Находим всех активных пользователей с FCM токенами
        users = db.query(User).filter(
            User.fcm_token.isnot(None),
            User.is_active == True
        ).all()
        
        sent_count = 0
        for user in users:
            try:
                asyncio.create_task(
                    send_localized_notification_to_user(
                        db,
                        user.id,
                        "holiday_greeting",
                        "holiday_greeting"
                    )
                )
                sent_count += 1
            except Exception as e:
                print(f"Ошибка отправки праздничного уведомления пользователю {user.id}: {e}")
        
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
                User.fcm_token.isnot(None),
                User.is_active == True
            ).all()
            
            sent_count = 0
            for user in users:
                try:
                    asyncio.create_task(
                        send_localized_notification_to_user(
                            db,
                            user.id,
                            "friday_evening",
                            "friday_evening"
                        )
                    )
                    sent_count += 1
                except Exception as e:
                    print(f"Ошибка отправки уведомления пятницы пользователю {user.id}: {e}")
            
            if sent_count > 0:
                print(f"Отправлено {sent_count} уведомлений 'Пятница вечер'")
        
        # Понедельник 8:00
        elif weekday == 0 and hour == 8:
            users = db.query(User).filter(
                User.fcm_token.isnot(None),
                User.is_active == True
            ).all()
            
            sent_count = 0
            for user in users:
                try:
                    asyncio.create_task(
                        send_localized_notification_to_user(
                            db,
                            user.id,
                            "monday_morning",
                            "monday_morning"
                        )
                    )
                    sent_count += 1
                except Exception as e:
                    print(f"Ошибка отправки уведомления понедельника пользователю {user.id}: {e}")
            
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
            User.fcm_token.isnot(None),
            User.is_active == True
        ).all()

        sent_count = 0
        for user in users:
            try:
                asyncio.create_task(
                    send_localized_notification_to_user(
                        db,
                        user.id,
                        "new_car_available",
                        "new_car_available"
                    )
                )
                sent_count += 1
            except Exception as e:
                print(f"Ошибка отправки уведомления о новом авто пользователю {user.id}: {e}")

        if sent_count > 0:
            print(f"Отправлено {sent_count} уведомлений о новых автомобилях")
    except Exception as e:
        print(f"Ошибка при проверке новых автомобилей: {e}")
    finally:
        db.close()

