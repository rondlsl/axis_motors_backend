#!/usr/bin/env python3
"""
Скрипт для исправления состояния миграций Alembic.
"""

import os
import sys
from sqlalchemy import create_engine, text

# Получаем параметры подключения к базе данных
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:gzPgNzfK@db:5432/postgres")

def fix_alembic_state():
    """Исправляет состояние миграций в базе данных."""
    try:
        # Создаем подключение к базе данных
        engine = create_engine(DATABASE_URL)
        
        with engine.connect() as conn:
            # Проверяем текущую ревизию
            result = conn.execute(text("SELECT version_num FROM alembic_version"))
            current_revision = result.fetchone()
            
            if current_revision:
                print(f"Текущая ревизия в базе данных: {current_revision[0]}")
            else:
                print("Таблица alembic_version пуста")
                return
            
            # Устанавливаем правильную ревизию (последняя миграция с именами)
            target_revision = "9a47928fea56"
            
            print(f"Устанавливаем ревизию: {target_revision}")
            
            # Обновляем ревизию
            conn.execute(text(f"UPDATE alembic_version SET version_num = '{target_revision}'"))
            conn.commit()
            
            print(f"Состояние миграций исправлено на: {target_revision}")
            print("Теперь можно запустить: alembic upgrade head")
            
    except Exception as e:
        print(f"Ошибка при исправлении состояния миграций: {e}")
        sys.exit(1)

if __name__ == "__main__":
    fix_alembic_state()
