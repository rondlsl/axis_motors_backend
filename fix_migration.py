#!/usr/bin/env python3
"""
Скрипт для исправления состояния миграций Alembic
"""
import os
import sys
from sqlalchemy import create_engine, text

# Добавляем путь к приложению
sys.path.append('/app')

from app.core.config import DATABASE_URL

def fix_migration_state():
    """Исправляет состояние миграций в базе данных"""
    try:
        # Создаем подключение к базе данных
        engine = create_engine(DATABASE_URL)
        
        with engine.connect() as connection:
            # Проверяем текущее состояние
            result = connection.execute(text("SELECT version_num FROM alembic_version;"))
            current_version = result.fetchone()
            
            if current_version:
                print(f"Текущая версия в базе данных: {current_version[0]}")
                
                # Обновляем на правильную версию
                connection.execute(text("UPDATE alembic_version SET version_num = 'ae988e1a3a68';"))
                connection.commit()
                
                print("Состояние миграций исправлено на: ae988e1a3a68")
            else:
                print("Таблица alembic_version пуста, создаем запись")
                connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('ae988e1a3a68');"))
                connection.commit()
                
                print("Создана запись с версией: ae988e1a3a68")
                
    except Exception as e:
        print(f"Ошибка при исправлении состояния миграций: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = fix_migration_state()
    if success:
        print("Состояние миграций успешно исправлено!")
    else:
        print("Не удалось исправить состояние миграций")
        sys.exit(1)
