"""
Одноразовая задача: 11 февраля 2026 в 13:00 по Алматы — отправить в приложение
уведомление пользователям «11–14 фев, без документов» о том, что баг с регистрацией по почте исправлен.
В любую другую дату функция сразу выходит без отправки.
"""
from __future__ import annotations

from datetime import datetime

from app.core.logging_config import get_logger
from app.dependencies.database.database import SessionLocal
from app.models.user_model import User
from app.push.utils import send_push_to_user_by_id_async
from app.utils.time_utils import get_local_time

logger = get_logger(__name__)

RUN_DATE_ALMATY = (2026, 2, 11)
TITLE = "Исправлена проблема с регистрацией"
BODY = (
    "Ранее при регистрации возникала проблема с отправкой кода на email. "
    "Мы исправили ошибку. Теперь вы можете снова запросить код подтверждения в разделе профиля."
)


def _get_almaty_date():
    """Текущая дата в Алматы (timezone уже учтена в get_local_time)."""
    now = get_local_time()
    return (now.year, now.month, now.day)


async def notify_bug_fixed_feb11_14_job():
    """Запускается по расписанию в 13:00 по Алматы. Срабатывает только 11.02.2026."""
    today = _get_almaty_date()
    if today != RUN_DATE_ALMATY:
        logger.debug(
            "notify_bug_fixed_feb11_14: дата %s, разрешена только %s. Пропуск.",
            today,
            RUN_DATE_ALMATY,
        )
        return

    logger.info("notify_bug_fixed_feb11_14: запуск рассылки (11–14 фев, без документов)")
    db = SessionLocal()
    try:
        users = db.query(User).filter(
            User.upload_document_at.is_(None),
            User.is_deleted == False,
            User.created_at >= datetime(2026, 2, 11),
            User.created_at < datetime(2026, 2, 15),
        ).order_by(User.created_at).all()
    finally:
        db.close()

    if not users:
        logger.info("notify_bug_fixed_feb11_14: нет пользователей по критерию")
        return

    ok = 0
    no_tokens = 0
    fail = 0
    for user in users:
        try:
            sent = await send_push_to_user_by_id_async(user.id, TITLE, BODY)
            if sent:
                ok += 1
            else:
                no_tokens += 1
        except Exception as e:
            fail += 1
            logger.warning("notify_bug_fixed_feb11_14: ошибка для %s: %s", user.phone_number, e)

    logger.info(
        "notify_bug_fixed_feb11_14: готово. push=%s, только в приложении=%s, ошибок=%s",
        ok,
        no_tokens,
        fail,
    )
