#!/usr/bin/env python3
"""
Скрипт для проверки, что поля доставки добавлены в таблицу rental_history.
"""

import os
import sys
from sqlalchemy import create_engine, text

# Получаем параметры подключения к базе данных
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:gzPgNzfK@db:5432/postgres")

def check_delivery_fields():
    """Проверяет, что поля доставки добавлены в таблицу rental_history."""
    try:
        # Создаем подключение к базе данных
        engine = create_engine(DATABASE_URL)
        
        with engine.connect() as conn:
            # Проверяем структуру таблицы rental_history
            result = conn.execute(text("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns 
                WHERE table_name = 'rental_history' 
                AND column_name LIKE '%delivery%'
                ORDER BY column_name;
            """))
            
            columns = result.fetchall()
            
            if columns:
                print("✅ Поля доставки успешно добавлены в таблицу rental_history:")
                print("-" * 60)
                for col in columns:
                    print(f"  {col[0]:<25} | {col[1]:<15} | Nullable: {col[2]:<3} | Default: {col[3] or 'None'}")
                print("-" * 60)
            else:
                print("❌ Поля доставки не найдены в таблице rental_history")
                return False
            
            # Проверяем текущую ревизию Alembic
            result = conn.execute(text("SELECT version_num FROM alembic_version"))
            current_revision = result.fetchone()
            
            if current_revision:
                print(f"📋 Текущая ревизия Alembic: {current_revision[0]}")
            
            print("\n🎉 Система справедливого начисления штрафов за доставку готова к работе!")
            return True
            
    except Exception as e:
        print(f"❌ Ошибка при проверке полей доставки: {e}")
        return False

if __name__ == "__main__":
    check_delivery_fields()
