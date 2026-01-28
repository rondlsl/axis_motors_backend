"""
Redis Service для централизованной работы с кэшем.
Поддерживает graceful degradation при недоступности Redis.
"""
import logging
from typing import Optional, Union
from contextlib import asynccontextmanager

import redis.asyncio as redis

from app.core.config import (
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
    REDIS_PASSWORD,
    REDIS_ENABLED,
    REDIS_POOL_SIZE,
    REDIS_TIMEOUT,
)

logger = logging.getLogger(__name__)


class RedisService:
    """Async Redis сервис с connection pooling и graceful degradation."""

    _instance: Optional['RedisService'] = None
    _pool: Optional[redis.ConnectionPool] = None
    _client: Optional[redis.Redis] = None
    _initialized: bool = False
    _available: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def initialize(self) -> bool:
        """
        Инициализация connection pool.
        Вызывать при startup приложения.
        Returns: True если Redis доступен, False если нет.
        """
        if self._initialized:
            return self._available

        if not REDIS_ENABLED:
            logger.info("Redis disabled by configuration (REDIS_ENABLED=false)")
            self._available = False
            self._initialized = True
            return False

        try:
            self._pool = redis.ConnectionPool(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                password=REDIS_PASSWORD,
                max_connections=REDIS_POOL_SIZE,
                socket_timeout=REDIS_TIMEOUT,
                socket_connect_timeout=REDIS_TIMEOUT,
                decode_responses=True,
            )

            self._client = redis.Redis(connection_pool=self._pool)

            # Проверяем подключение
            await self._client.ping()

            self._available = True
            self._initialized = True
            logger.info(f"Redis connected: {REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}")
            return True

        except Exception as e:
            logger.warning(f"Redis unavailable, falling back to database: {e}")
            self._available = False
            self._initialized = True
            return False

    async def shutdown(self) -> None:
        """Закрытие connection pool. Вызывать при shutdown приложения."""
        if self._client:
            await self._client.close()
        if self._pool:
            await self._pool.disconnect()
        self._initialized = False
        self._available = False
        logger.info("Redis connection closed")

    @property
    def is_available(self) -> bool:
        """Проверить, доступен ли Redis."""
        return self._available

    @property
    def client(self) -> Optional[redis.Redis]:
        """Получить Redis клиент. Может быть None если Redis недоступен."""
        return self._client if self._available else None

    # === CRUD операции с graceful degradation ===

    async def get(self, key: str) -> Optional[str]:
        """Получить значение по ключу. Возвращает None если Redis недоступен."""
        if not self._available or not self._client:
            return None
        try:
            return await self._client.get(key)
        except Exception as e:
            logger.error(f"Redis GET error for key {key}: {e}")
            return None

    async def set(
        self,
        key: str,
        value: Union[str, int],
        ttl: Optional[int] = None,
        nx: bool = False,
        xx: bool = False
    ) -> bool:
        """
        Установить значение.
        Args:
            key: ключ
            value: значение
            ttl: время жизни в секундах
            nx: установить только если ключ не существует
            xx: установить только если ключ существует
        Returns: True если успешно, False если нет.
        """
        if not self._available or not self._client:
            return False
        try:
            result = await self._client.set(key, value, ex=ttl, nx=nx, xx=xx)
            return result is not None and result is not False
        except Exception as e:
            logger.error(f"Redis SET error for key {key}: {e}")
            return False

    async def delete(self, *keys: str) -> int:
        """Удалить ключи. Возвращает количество удаленных."""
        if not self._available or not self._client:
            return 0
        try:
            return await self._client.delete(*keys)
        except Exception as e:
            logger.error(f"Redis DELETE error for keys {keys}: {e}")
            return 0

    async def exists(self, key: str) -> bool:
        """Проверить существование ключа."""
        if not self._available or not self._client:
            return False
        try:
            return await self._client.exists(key) > 0
        except Exception as e:
            logger.error(f"Redis EXISTS error for key {key}: {e}")
            return False

    async def incr(self, key: str, amount: int = 1) -> Optional[int]:
        """Инкремент значения. Возвращает новое значение."""
        if not self._available or not self._client:
            return None
        try:
            return await self._client.incrby(key, amount)
        except Exception as e:
            logger.error(f"Redis INCR error for key {key}: {e}")
            return None

    async def expire(self, key: str, ttl: int) -> bool:
        """Установить TTL для ключа."""
        if not self._available or not self._client:
            return False
        try:
            return await self._client.expire(key, ttl)
        except Exception as e:
            logger.error(f"Redis EXPIRE error for key {key}: {e}")
            return False

    # === Distributed Lock ===

    @asynccontextmanager
    async def lock(
        self,
        name: str,
        timeout: float = 60.0,
        blocking_timeout: float = 5.0
    ):
        """
        Distributed lock context manager.

        Usage:
            async with redis_service.lock("billing_job"):
                # critical section

        Args:
            name: имя лока
            timeout: автоматический release через N секунд (защита от deadlock)
            blocking_timeout: сколько ждать получения лока

        Yields: Lock объект или None если Redis недоступен или лок не получен
        """
        if not self._available or not self._client:
            logger.warning(f"Redis unavailable, skipping lock '{name}'")
            yield None
            return

        lock = self._client.lock(
            f"lock:{name}",
            timeout=timeout,
            blocking_timeout=blocking_timeout
        )

        acquired = False
        try:
            acquired = await lock.acquire(blocking=True)
            if acquired:
                logger.debug(f"Lock acquired: {name}")
                yield lock
            else:
                logger.info(f"Could not acquire lock '{name}' within timeout")
                yield None
        except Exception as e:
            logger.error(f"Lock error for '{name}': {e}")
            yield None
        finally:
            if acquired:
                try:
                    await lock.release()
                    logger.debug(f"Lock released: {name}")
                except Exception as e:
                    logger.error(f"Lock release error for '{name}': {e}")


# Глобальный экземпляр сервиса (singleton)
_redis_service: Optional[RedisService] = None


def get_redis_service() -> RedisService:
    """Получить экземпляр Redis сервиса (sync-safe getter)."""
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService()
    return _redis_service


async def init_redis() -> bool:
    """Инициализировать Redis при старте. Возвращает True если доступен."""
    service = get_redis_service()
    return await service.initialize()


async def shutdown_redis() -> None:
    """Закрыть Redis при остановке."""
    service = get_redis_service()
    await service.shutdown()
