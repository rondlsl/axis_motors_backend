#!/usr/bin/env python3
"""
Одноразовая рассылка: пользователям «зарегистрировались 11–14 фев, без документов»
отправляется уведомление в приложение (push + запись в БД) о том, что баг с регистрацией по почте исправлен.

Запуск сегодня в 13:00 по Алматы (cron или вручную):
  cd /path/to/azv_motors_backend_v2 && python scripts/notify_bug_fixed_no_docs_feb11_14.py

Тест на одном номере:
  python scripts/notify_bug_fixed_no_docs_feb11_14.py 77056478662
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv
load_dotenv()

TITLE = "Исправлена проблема с регистрацией"
BODY = (
    "Ранее при регистрации возникала проблема с отправкой кода на email. "
    "Мы исправили ошибку. Теперь вы можете снова запросить код подтверждения."
)


def main():
    from sqlalchemy import create_engine, text
    from app.core.config import DATABASE_URL
    import uuid

    # Загружаем все ORM-модели до вызова push (иначе Car→RentalHistory, User→UserDevice не находятся)
    import app.models.init  # noqa: F401
    import app.models.user_device_model  # noqa: F401

    from app.push.utils import send_push_to_user_by_id_async

    # Тест на одном номере: python scripts/notify_bug_fixed_no_docs_feb11_14.py 77056478662
    test_phone = (sys.argv[1] or os.environ.get("PHONE_TEST", "")).strip() if len(sys.argv) > 1 else os.environ.get("PHONE_TEST", "")

    engine = create_engine(DATABASE_URL.replace("postgresql+psycopg2", "postgresql+psycopg2"))
    with engine.connect() as conn:
        if test_phone:
            rows = conn.execute(
                text("SELECT id, phone_number FROM users WHERE phone_number = :phone AND is_deleted = false"),
                {"phone": test_phone},
            ).fetchall()
            if not rows:
                print(f"Пользователь с номером {test_phone} не найден или удалён.")
                sys.exit(1)
            print(f"Режим теста: только {test_phone}")
        else:
            rows = conn.execute(text("""
                SELECT id, phone_number
                FROM users
                WHERE upload_document_at IS NULL
                  AND is_deleted = false
                  AND created_at >= '2026-02-11'
                  AND created_at < '2026-02-15'
                ORDER BY created_at
            """)).fetchall()

    if not rows:
        print("Нет пользователей по критерию (11–14 фев, без документов). Выход.")
        sys.exit(0)

    users = [{"id": uuid.UUID(str(r[0])), "phone_number": r[1]} for r in rows]
    print(f"Отправка уведомлений в приложение для {len(users)} пользователей...")

    import asyncio

    async def send_all():
        ok = 0
        no_tokens = 0
        fail = 0
        for i, user in enumerate(users, 1):
            try:
                sent = await send_push_to_user_by_id_async(
                    user["id"],
                    TITLE,
                    BODY,
                )
                if sent:
                    ok += 1
                    print(f"  [{i}/{len(users)}] OK push: {user['phone_number']}")
                else:
                    no_tokens += 1
                    print(f"  [{i}/{len(users)}] В приложении (нет FCM): {user['phone_number']}")
            except Exception as e:
                fail += 1
                print(f"  [{i}/{len(users)}] FAIL {user['phone_number']}: {e}")
        print(f"Готово. Push отправлен: {ok}, только в приложении (без push): {no_tokens}, ошибок: {fail}.")

    asyncio.run(send_all())


if __name__ == "__main__":
    main()
