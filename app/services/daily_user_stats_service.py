"""
Сервис предагрегации регистраций пользователей (DailyUserStats).
Атомарное обновление счётчика при регистрации без full scan users.
"""
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logging_config import get_logger

logger = get_logger(__name__)


def backfill_daily_user_stats_from_users(db: Session) -> int:
    """
    Один раз заполняет daily_user_stats по данным из users (по date(created_at)).
    Вызов после применения миграции 010, если в users уже есть данные.
    Возвращает количество вставленных/обновлённых дат.
    """
    stmt = text("""
        INSERT INTO daily_user_stats (date, registered_count)
        SELECT created_at::date, COUNT(*)::int
        FROM users
        WHERE created_at IS NOT NULL
        GROUP BY created_at::date
        ON CONFLICT (date) DO UPDATE
        SET registered_count = EXCLUDED.registered_count
    """)
    result = db.execute(stmt)
    db.commit()
    return result.rowcount if hasattr(result, "rowcount") else 0


def increment_daily_user_registered(db: Session, registration_date: date) -> None:
    """
    Атомарно увеличивает счётчик зарегистрированных пользователей за указанную дату.
    Использует INSERT ... ON CONFLICT DO UPDATE — одна строка на дату, минимум блокировок.

    Вызывать в той же транзакции, что и создание User (после db.add(user), до commit).

    :param db: активная сессия SQLAlchemy (sync)
    :param registration_date: дата в локальной таймзоне (день создания аккаунта)
    """
    stmt = text("""
        INSERT INTO daily_user_stats (date, registered_count)
        VALUES (:d, 1)
        ON CONFLICT (date) DO UPDATE
        SET registered_count = daily_user_stats.registered_count + 1
    """)
    try:
        db.execute(stmt, {"d": registration_date})
    except Exception as e:
        logger.exception(
            "Ошибка обновления daily_user_stats для даты %s: %s",
            registration_date,
            e,
        )
        raise
