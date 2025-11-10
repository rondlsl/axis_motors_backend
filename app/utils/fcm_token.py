"""
Утилиты для работы с FCM токенами
"""
import string
import random
from sqlalchemy.orm import Session
from app.models.user_model import User
from typing import Optional


def generate_fcm_token_string() -> str:
    """
    Генерирует случайную строку для FCM токена в формате ExponentPushToken[...]
    
    Returns:
        Строка токена в формате: ExponentPushToken[<random_string>]
    """
    # Генерируем случайную строку из 22 символов (буквы и цифры)
    # Это стандартная длина для Expo Push Tokens
    characters = string.ascii_letters + string.digits
    random_string = ''.join(random.choice(characters) for _ in range(22))
    return f"ExponentPushToken[{random_string}]"


def ensure_unique_fcm_token(db: Session, user_id=None, max_attempts: int = 10) -> str:
    """
    Генерирует уникальный FCM токен, проверяя отсутствие дубликатов в базе данных.
    
    Args:
        db: Сессия базы данных
        user_id: ID пользователя (UUID или строка), для которого генерируется токен (необязательно)
                Если указан, исключается из проверки на дубликаты
        max_attempts: Максимальное количество попыток генерации (по умолчанию 10)
    
    Returns:
        Уникальный FCM токен в формате: ExponentPushToken[<random_string>]
    
    Raises:
        RuntimeError: Если не удалось сгенерировать уникальный токен за max_attempts попыток
    """
    import uuid
    from app.utils.short_id import safe_sid_to_uuid
    
    # Преобразуем user_id в UUID, если он передан
    user_uuid = None
    if user_id:
        try:
            if isinstance(user_id, str):
                # Пытаемся преобразовать из sid формата
                user_uuid = safe_sid_to_uuid(user_id)
            elif isinstance(user_id, uuid.UUID):
                user_uuid = user_id
        except:
            # Если не удалось преобразовать, игнорируем user_id
            pass
    
    for attempt in range(max_attempts):
        token = generate_fcm_token_string()
        
        # Проверяем, существует ли такой токен у другого пользователя
        query = db.query(User).filter(User.fcm_token == token)
        
        # Если указан user_uuid, исключаем текущего пользователя из проверки
        if user_uuid:
            query = query.filter(User.id != user_uuid)
        
        existing_user = query.first()
        
        if not existing_user:
            # Токен уникален
            return token
    
    # Если не удалось сгенерировать уникальный токен
    raise RuntimeError(f"Не удалось сгенерировать уникальный FCM токен за {max_attempts} попыток")


def ensure_user_has_unique_fcm_token(db: Session, user: User) -> bool:
    """
    Проверяет и обновляет FCM токен пользователя, если необходимо.
    
    Логика:
    1. Если у пользователя нет токена - генерирует новый уникальный
    2. Если у пользователя есть токен - проверяет на дубликаты
    3. Если найден дубликат - генерирует новый уникальный токен
    
    Args:
        db: Сессия базы данных
        user: Пользователь, для которого нужно проверить/обновить токен
    
    Returns:
        True если токен был создан/обновлен, False если изменений не было
    """
    token_updated = False
    
    # Если у пользователя нет токена - генерируем новый
    if not user.fcm_token:
        user.fcm_token = ensure_unique_fcm_token(db, user_id=user.id)
        token_updated = True
    else:
        # Проверяем, нет ли дубликата у другого пользователя
        duplicate_user = db.query(User).filter(
            User.fcm_token == user.fcm_token,
            User.id != user.id
        ).first()
        
        if duplicate_user:
            # Найден дубликат - генерируем новый уникальный токен
            user.fcm_token = ensure_unique_fcm_token(db, user_id=user.id)
            token_updated = True
    
    if token_updated:
        db.add(user)
        db.flush()
    
    return token_updated

