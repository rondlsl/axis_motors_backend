"""
Кэширование JWT токенов в Redis.
Уменьшает нагрузку на БД при валидации токенов.
"""
import logging
from typing import Optional
from uuid import UUID

from app.services.redis_service import get_redis_service

logger = logging.getLogger(__name__)

# Префикс ключей
TOKEN_CACHE_PREFIX = "token:"

# TTL (в секундах)
TOKEN_CACHE_TTL = 300  # 5 минут


class TokenCache:
    """Управление кэшем токенов в Redis."""

    @staticmethod
    def _token_key(token: str) -> str:
        """Генерация ключа для токена (используем первые 32 символа)."""
        return f"{TOKEN_CACHE_PREFIX}{token[:32]}"

    @staticmethod
    async def get_token_user_id(token: str) -> Optional[str]:
        """
        Получить user_id по токену из кэша.
        Returns: user_id как строка или None если не найден.
        """
        redis = get_redis_service()
        if not redis.is_available:
            return None

        key = TokenCache._token_key(token)
        result = await redis.get(key)

        if result:
            logger.debug(f"Token cache HIT: {key[:20]}...")
            return result

        logger.debug(f"Token cache MISS: {key[:20]}...")
        return None

    @staticmethod
    async def set_token_user_id(token: str, user_id: UUID) -> bool:
        """
        Сохранить маппинг токен -> user_id.
        Returns: True если успешно сохранено.
        """
        redis = get_redis_service()
        if not redis.is_available:
            return False

        key = TokenCache._token_key(token)
        return await redis.set(key, str(user_id), ttl=TOKEN_CACHE_TTL)

    @staticmethod
    async def invalidate_token(token: str) -> bool:
        """Инвалидировать токен в кэше."""
        redis = get_redis_service()
        if not redis.is_available:
            return False

        key = TokenCache._token_key(token)
        deleted = await redis.delete(key)
        return deleted > 0
