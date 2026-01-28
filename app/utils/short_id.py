"""
Утилита для кодирования UUID в короткий ID (sid) и обратно
"""
import uuid
import base64


def uuid_to_sid(uuid_value: uuid.UUID) -> str:
    """
    Конвертирует UUID в короткий ID (sid)
    
    Args:
        uuid_value: UUID объект
        
    Returns:
        Закодированная строка (sid)
        
    Example:
        >>> uuid_val = uuid.UUID('550e8400-e29b-41d4-a716-446655440000')
        >>> uuid_to_sid(uuid_val)
        'VQ6EAOKbQdSnFkRmVUQAAA'
    """
    # Конвертируем UUID в bytes (16 байт)
    uuid_bytes = uuid_value.bytes
    
    # Кодируем в base64 и убираем padding (==)
    encoded = base64.urlsafe_b64encode(uuid_bytes).decode('ascii').rstrip('=')
    
    return encoded


def sid_to_uuid(sid: str) -> uuid.UUID:
    """
    Конвертирует короткий ID (sid) обратно в UUID
    
    Args:
        sid: Закодированная строка
        
    Returns:
        UUID объект
        
    Example:
        >>> sid_to_uuid('VQ6EAOKbQdSnFkRmVUQAAA')
        UUID('550e8400-e29b-41d4-a716-446655440000')
    """
    # Добавляем padding если необходимо
    padding = 4 - (len(sid) % 4)
    if padding and padding != 4:
        sid += '=' * padding
    
    # Декодируем из base64
    uuid_bytes = base64.urlsafe_b64decode(sid.encode('ascii'))
    
    # Создаем UUID из bytes
    return uuid.UUID(bytes=uuid_bytes)


def uuid_str_to_sid(uuid_str: str) -> str:
    """
    Конвертирует строку UUID в короткий ID (sid)
    
    Args:
        uuid_str: UUID в виде строки
        
    Returns:
        Закодированная строка (sid)
    """
    return uuid_to_sid(uuid.UUID(uuid_str))


def safe_sid_to_uuid(sid: str) -> uuid.UUID:
    """
    Безопасная конвертация sid или UUID-строки в UUID с понятной ошибкой.
    Поддерживает оба формата: короткий ID (base64) и полный UUID.
    
    Args:
        sid: Закодированная строка (short ID) или UUID-строка
        
    Returns:
        UUID объект
        
    Raises:
        ValueError: Если sid имеет неверный формат
        
    Example:
        >>> safe_sid_to_uuid('VQ6EAOKbQdSnFkRmVUQAAA')
        UUID('550e8400-e29b-41d4-a716-446655440000')
        
        >>> safe_sid_to_uuid('550e8400-e29b-41d4-a716-446655440000')
        UUID('550e8400-e29b-41d4-a716-446655440000')
        
        >>> safe_sid_to_uuid('invalid')
        ValueError: Неверный формат Short ID: invalid
    """
    # Уже UUID — возвращаем как есть (например, из SQLAlchemy model)
    if isinstance(sid, uuid.UUID):
        return sid
    sid = str(sid)
    # Проверяем, не является ли это уже полным UUID (с дефисами или без)
    # UUID формат: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (36 символов с дефисами)
    # или 32 hex символа без дефисов
    if len(sid) == 36 and sid.count('-') == 4:
        try:
            return uuid.UUID(sid)
        except ValueError:
            pass
    elif len(sid) == 32:
        try:
            return uuid.UUID(sid)
        except ValueError:
            pass
    
    # Иначе пробуем декодировать как short ID
    try:
        return sid_to_uuid(sid)
    except Exception as e:
        raise ValueError(f"Неверный формат Short ID: {sid}") from e

