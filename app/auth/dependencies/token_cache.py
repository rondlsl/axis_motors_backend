"""
Кэширование JWT токенов в Redis.
Уменьшает нагрузку на БД при валидации токенов.

Архитектура:
- Ключ token:<hash> -> user_id (основной кэш)
- Ключ user_tokens:<user_id> -> SET токенов (для массовой инвалидации)
- TTL совпадает с временем жизни токена
"""
import logging
import hashlib
from typing import Optional, List
from uuid import UUID

from app.services.redis_service import get_redis_service
from app.core.config import ACCESS_TOKEN_EXPIRE_MINUTES

logger = logging.getLogger(__name__)

# Префиксы ключей
TOKEN_CACHE_PREFIX = "token:"
USER_TOKENS_PREFIX = "user_tokens:"

# TTL (в секундах) - соответствует времени жизни access токена
TOKEN_CACHE_TTL = ACCESS_TOKEN_EXPIRE_MINUTES * 60  # 140 минут -> 8400 секунд


class TokenCache:
    """
    Управление кэшем токенов в Redis.

    Thread-safe и работает корректно при нескольких инстансах.
    При недоступности Redis - graceful degradation к БД.
    """

    @staticmethod
    def _token_hash(token: str) -> str:
        """
        Хэшируем токен для ключа (безопасность + экономия памяти).
        SHA256 первые 32 символа достаточно для уникальности.
        """
        return hashlib.sha256(token.encode()).hexdigest()[:32]

    @staticmethod
    def _token_key(token: str) -> str:
        """Генерация ключа для токена."""
        return f"{TOKEN_CACHE_PREFIX}{TokenCache._token_hash(token)}"

    @staticmethod
    def _user_tokens_key(user_id: UUID) -> str:
        """Генерация ключа для множества токенов пользователя."""
        return f"{USER_TOKENS_PREFIX}{str(user_id)}"

    @staticmethod
    async def get_token_user_id(token: str) -> Optional[str]:
        """
        Получить user_id по токену из кэша.

        Returns:
            user_id как строка или None если не найден/Redis недоступен.
        """
        redis = get_redis_service()
        if not redis.is_available:
            return None

        key = TokenCache._token_key(token)
        try:
            result = await redis.get(key)
            if result:
                logger.debug("Token cache HIT")
                return result
            logger.debug("Token cache MISS")
            return None
        except Exception as e:
            logger.error(f"Token cache GET error: {e}")
            return None

    @staticmethod
    async def set_token_user_id(
        token: str,
        user_id: UUID,
        ttl: Optional[int] = None
    ) -> bool:
        """
        Сохранить маппинг токен -> user_id.

        Args:
            token: JWT токен
            user_id: UUID пользователя
            ttl: время жизни в секундах (по умолчанию TOKEN_CACHE_TTL)

        Returns:
            True если успешно сохранено.
        """
        redis = get_redis_service()
        if not redis.is_available:
            return False

        effective_ttl = ttl if ttl is not None else TOKEN_CACHE_TTL
        token_key = TokenCache._token_key(token)
        user_tokens_key = TokenCache._user_tokens_key(user_id)
        token_hash = TokenCache._token_hash(token)

        try:
            # Атомарно: сохраняем токен и добавляем в SET пользователя
            client = redis.client
            if client:
                async with client.pipeline(transaction=True) as pipe:
                    # Сохраняем маппинг token -> user_id
                    pipe.set(token_key, str(user_id), ex=effective_ttl)
                    # Добавляем хэш токена в SET пользователя
                    pipe.sadd(user_tokens_key, token_hash)
                    # Обновляем TTL для SET
                    pipe.expire(user_tokens_key, effective_ttl)
                    await pipe.execute()
                return True
            return False
        except Exception as e:
            logger.error(f"Token cache SET error: {e}")
            return False

    @staticmethod
    async def invalidate_token(token: str) -> bool:
        """
        Инвалидировать один токен в кэше.

        Returns:
            True если токен был удалён.
        """
        redis = get_redis_service()
        if not redis.is_available:
            return False

        key = TokenCache._token_key(token)
        try:
            deleted = await redis.delete(key)
            if deleted > 0:
                logger.debug("Token invalidated from cache")
            return deleted > 0
        except Exception as e:
            logger.error(f"Token invalidate error: {e}")
            return False

    @staticmethod
    async def invalidate_all_user_tokens(user_id: UUID) -> int:
        """
        Инвалидировать ВСЕ токены пользователя.
        Используется при logout, смене пароля, блокировке.

        Returns:
            Количество удалённых токенов.
        """
        redis = get_redis_service()
        if not redis.is_available:
            return 0

        user_tokens_key = TokenCache._user_tokens_key(user_id)

        try:
            client = redis.client
            if not client:
                return 0

            # Получаем все хэши токенов пользователя
            token_hashes = await client.smembers(user_tokens_key)
            if not token_hashes:
                return 0

            # Формируем ключи для удаления
            keys_to_delete = [f"{TOKEN_CACHE_PREFIX}{h}" for h in token_hashes]
            keys_to_delete.append(user_tokens_key)

            # Удаляем все ключи одной командой
            deleted = await client.delete(*keys_to_delete)
            logger.info(f"Invalidated {deleted} tokens for user {user_id}")
            return deleted
        except Exception as e:
            logger.error(f"Invalidate all user tokens error: {e}")
            return 0

    @staticmethod
    async def invalidate_tokens_batch(tokens: List[str]) -> int:
        """
        Инвалидировать список токенов (batch операция).

        Args:
            tokens: список JWT токенов

        Returns:
            Количество удалённых токенов.
        """
        redis = get_redis_service()
        if not redis.is_available or not tokens:
            return 0

        try:
            keys = [TokenCache._token_key(t) for t in tokens]
            deleted = await redis.delete(*keys)
            logger.debug(f"Batch invalidated {deleted} tokens")
            return deleted
        except Exception as e:
            logger.error(f"Batch invalidate error: {e}")
            return 0
