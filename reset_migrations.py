#!/usr/bin/env python3
"""
Скрипт для сброса состояния миграций Alembic
"""
import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

def reset_migrations():
    """Сброс состояния миграций"""
    
    # Получаем URL базы данных из переменных окружения или используем значения по умолчанию
    database_url = os.getenv('DATABASE_URL')
    
    if not database_url:
        # Собираем URL из отдельных переменных
        host = os.getenv('POSTGRES_HOST', '195.93.152.69')
        port = os.getenv('POSTGRES_PORT', '5432')
        user = os.getenv('POSTGRES_USER', 'postgres')
        password = os.getenv('POSTGRES_PASSWORD', 'postgres')
        db_name = os.getenv('POSTGRES_DB', 'azv_motors_backend_v2')
        
        database_url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}"
        print(f"Используем URL: {database_url}")
    
    if not database_url:
        print("Ошибка: Не удалось определить URL базы данных")
        return False
    
    try:
        # Подключаемся к базе данных
        engine = create_engine(database_url)
        
        with engine.connect() as conn:
            # Удаляем таблицу alembic_version
            print("Удаляем таблицу alembic_version...")
            conn.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE;"))
            
            # Удаляем все ENUM типы
            print("Удаляем ENUM типы...")
            enums_to_drop = [
                'wallettransactiontype', 'userpromostatus', 'notificationstatus', 'contracttype',
                'actiontype', 'rentalstatus', 'rentaltype', 'verificationstatus',
                'guarantorrequeststatus', 'applicationstatus', 'carstatus', 'transmissiontype',
                'carautoclass', 'carbodytype', 'autoclass', 'userrole'
            ]
            
            for enum_name in enums_to_drop:
                try:
                    conn.execute(text(f"DROP TYPE IF EXISTS {enum_name} CASCADE;"))
                    print(f"  Удален ENUM: {enum_name}")
                except SQLAlchemyError as e:
                    print(f"  Предупреждение при удалении {enum_name}: {e}")
            
            # Удаляем все таблицы
            print("Удаляем все таблицы...")
            tables_to_drop = [
                'wallet_transactions', 'support_actions', 'user_promo_codes', 'promo_codes',
                'notifications', 'user_contract_signatures', 'contract_files', 'verification_codes',
                'car_comments', 'rental_actions', 'rental_reviews', 'rental_history',
                'guarantors', 'guarantor_requests', 'applications', 'cars', 'users'
            ]
            
            for table_name in tables_to_drop:
                try:
                    conn.execute(text(f"DROP TABLE IF EXISTS {table_name} CASCADE;"))
                    print(f"  Удалена таблица: {table_name}")
                except SQLAlchemyError as e:
                    print(f"  Предупреждение при удалении {table_name}: {e}")
            
            conn.commit()
            print("Сброс миграций завершен успешно!")
            return True
            
    except SQLAlchemyError as e:
        print(f"Ошибка при сбросе миграций: {e}")
        return False

if __name__ == "__main__":
    success = reset_migrations()
    sys.exit(0 if success else 1)
