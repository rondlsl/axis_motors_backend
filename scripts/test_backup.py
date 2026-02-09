#!/usr/bin/env python3
"""
Тестовый скрипт для проверки сервиса бэкапов.
Запускать из корня проекта: python scripts/test_backup.py
"""
import sys
import os

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.backup_service import get_backup_service
from app.core.logging_config import get_logger

logger = get_logger(__name__)


def main():
    print("🧪 Тестирование сервиса бэкапов...")
    
    service = get_backup_service()
    
    # Тест 1: Создание бэкапа
    print("\n1️⃣ Создание тестового бэкапа...")
    backup_name = service.create_backup("test_backup.sql")
    
    if backup_name:
        print(f"✅ Бэкап создан: {backup_name}")
    else:
        print("❌ Ошибка создания бэкапа")
        return False
    
    # Тест 2: Список бэкапов
    print("\n2️⃣ Получение списка бэкапов...")
    backups = service.list_backups(limit=10)
    
    if backups:
        print(f"✅ Найдено бэкапов: {len(backups)}")
        for backup in backups[:3]:  # Показываем первые 3
            print(f"   - {backup['name']} ({backup['size']} bytes)")
    else:
        print("❌ Бэкапы не найдены")
    
    # Тест 3: Удаление тестового бэкапа
    print("\n3️⃣ Удаление тестового бэкапа...")
    if backup_name and "test_backup.sql" in backup_name:
        success = service.delete_backup("test_backup.sql")
        if success:
            print("✅ Тестовый бэкап удален")
        else:
            print("❌ Ошибка удаления бэкапа")
    else:
        print("ℹ️ Пропускаем удаление (бэкап в MinIO)")
    
    print("\n🎉 Тест завершен!")
    return True


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Test failed: {e}")
        print(f"❌ Ошибка: {e}")
        sys.exit(1)
