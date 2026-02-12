#!/usr/bin/env python3
"""
Однократный backfill daily_user_stats из таблицы users.
Запуск после применения миграции 010, если в users уже есть данные.

  cd /path/to/azv_motors_backend_v2
  python scripts/backfill_daily_user_stats.py
"""
import sys

# чтобы импортировать app
sys.path.insert(0, ".")


def main():
    from app.dependencies.database.database import SessionLocal
    from app.services.daily_user_stats_service import backfill_daily_user_stats_from_users

    db = SessionLocal()
    try:
        n = backfill_daily_user_stats_from_users(db)
        print(f"Backfill завершён: обновлено дат: {n}")
    except Exception as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
