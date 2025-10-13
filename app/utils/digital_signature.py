"""
Утилиты для работы с цифровой подписью пользователя
"""
import uuid
import hashlib
from datetime import datetime
from typing import Optional


def generate_digital_signature(user_id: str, phone_number: str, first_name: str, last_name: str) -> str:
    """
    Генерирует уникальную цифровую подпись для пользователя
    
    Args:
        user_id: UUID пользователя
        phone_number: Номер телефона пользователя
        first_name: Имя пользователя
        last_name: Фамилия пользователя
    
    Returns:
        Уникальная цифровая подпись в формате: XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
    """
    # Создаем уникальную строку на основе данных пользователя
    user_data = f"{user_id}_{phone_number}_{first_name}_{last_name}_{datetime.utcnow().isoformat()}"
    
    # Генерируем хеш
    hash_object = hashlib.sha256(user_data.encode())
    hash_hex = hash_object.hexdigest()
    
    # Берем первые 32 символа и форматируем как UUID
    uuid_string = hash_hex[:32]
    
    # Форматируем как UUID: XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
    formatted_uuid = f"{uuid_string[:8]}-{uuid_string[8:12]}-{uuid_string[12:16]}-{uuid_string[16:20]}-{uuid_string[20:32]}"
    
    return formatted_uuid


def validate_digital_signature(digital_signature: str) -> bool:
    """
    Проверяет корректность формата цифровой подписи
    
    Args:
        digital_signature: Цифровая подпись для проверки
    
    Returns:
        True если формат корректный, False в противном случае
    """
    if not digital_signature:
        return False
    
    try:
        # Проверяем, что это валидный UUID формат
        uuid.UUID(digital_signature)
        return True
    except ValueError:
        return False


def format_digital_signature_for_display(digital_signature: str) -> str:
    """
    Форматирует цифровую подпись для отображения пользователю
    
    Args:
        digital_signature: Цифровая подпись
    
    Returns:
        Отформатированная подпись для отображения
    """
    if not digital_signature:
        return ""
    
    # Показываем только первые 8 символов + "..."
    return f"{digital_signature[:8]}-..."
