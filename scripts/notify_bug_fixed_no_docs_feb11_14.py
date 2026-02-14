#!/usr/bin/env python3
"""
Одноразовая рассылка: пользователям «зарегистрировались 11–14 фев, без документов»
отправляется уведомление в приложение (push + запись в БД) о том, что баг с регистрацией по почте исправлен.

Срабатывает ТОЛЬКО 11 февраля 2026 года по времени Алматы (UTC+5).
В любую другую дату скрипт завершается без отправки.

Запуск в 13:00 по Алматы (cron или вручную):
  cd /path/to/azv_motors_backend_v2 && python scripts/notify_bug_fixed_no_docs_feb11_14.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv
load_dotenv()

# Единственная дата, когда скрипт что-то делает (Алматы)
RUN_DATE_ALMATY = (2026, 2, 11)

TITLE = "Исправлена проблема с регистрацией"
BODY = (
    "Ранее при регистрации возникала проблема с отправкой кода на email. "
    "Мы исправили ошибку. Теперь вы можете снова запросить код подтверждения."
)


def get_almaty_date():
    """Текущая дата в Алматы (UTC+5)."""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Almaty")
    except ImportError:
        import pytz
        tz = pytz.timezone("Asia/Almaty")
    return datetime.now(tz).date()


def main():
    today = get_almaty_date()
    if (today.year, today.month, today.day) != RUN_DATE_ALMATY:
        print(f"Дата запуска (Алматы): {today}. Скрипт разрешён только на {RUN_DATE_ALMATY[0]}-{RUN_DATE_ALMATY[1]:02d}-{RUN_DATE_ALMATY[2]:02d}. Выход без отправки.")
        sys.exit(0)

    from app.dependencies.database.database import SessionLocal
    from app.models.user_model import User
    from app.push.utils import send_push_to_user_by_id_async

    db = SessionLocal()
    try:
        # Те же пользователи, что в экспорте: 11–14 фев, без документов
        users = db.query(User).filter(
            User.upload_document_at.is_(None),
            User.is_deleted == False,
            User.created_at >= "2026-02-11",
            User.created_at < "2026-02-15",
        ).order_by(User.created_at).all()
    finally:
        db.close()

    if not users:
        print("Нет пользователей по критерию (11–14 фев, без документов). Выход.")
        sys.exit(0)

    print(f"Дата (Алматы): {today}. Отправка уведомлений в приложение для {len(users)} пользователей...")

    import asyncio

    async def send_all():
        ok = 0
        no_tokens = 0
        fail = 0
        for i, user in enumerate(users, 1):
            try:
                sent = await send_push_to_user_by_id_async(
                    user.id,
                    TITLE,
                    BODY,
                )
                if sent:
                    ok += 1
                    print(f"  [{i}/{len(users)}] OK push: {user.phone_number}")
                else:
                    no_tokens += 1
                    # Запись в БД всё равно создаётся в send_push_to_user_by_id — уведомление будет в приложении
                    print(f"  [{i}/{len(users)}] В приложении (нет FCM): {user.phone_number}")
            except Exception as e:
                fail += 1
                print(f"  [{i}/{len(users)}] FAIL {user.phone_number}: {e}")
        print(f"Готово. Push отправлен: {ok}, только в приложении (без push): {no_tokens}, ошибок: {fail}.")

    asyncio.run(send_all())


if __name__ == "__main__":
    main()
