"""
Distributed Lock для billing job.
Гарантирует, что только один инстанс выполняет billing одновременно.
"""
import logging
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from app.services.redis_service import get_redis_service

logger = logging.getLogger(__name__)

# Настройки лока
BILLING_LOCK_NAME = "billing_job"
BILLING_LOCK_TIMEOUT = 120.0  # 2 минуты максимум удержания
BILLING_LOCK_BLOCKING_TIMEOUT = 0.1  # Не ждем, сразу пропускаем


class BillingLock:
    """Управление distributed lock для billing."""

    @staticmethod
    @asynccontextmanager
    async def acquire() -> AsyncGenerator[bool, None]:
        """
        Попытка получить лок на billing job.

        Usage:
            async with BillingLock.acquire() as acquired:
                if acquired:
                    # выполняем billing
                else:
                    # пропускаем - другой инстанс уже выполняет

        Yields: True если лок получен, False если нет.
        """
        redis = get_redis_service()

        # Если Redis недоступен - выполняем без лока (single instance fallback)
        if not redis.is_available:
            logger.debug("Redis unavailable, executing billing without lock")
            yield True
            return

        try:
            async with redis.lock(
                BILLING_LOCK_NAME,
                timeout=BILLING_LOCK_TIMEOUT,
                blocking_timeout=BILLING_LOCK_BLOCKING_TIMEOUT
            ) as lock:
                if lock is not None:
                    logger.debug("Billing lock acquired, executing job")
                    yield True
                else:
                    logger.info("Billing lock held by another instance, skipping")
                    yield False
        except Exception as e:
            logger.error(f"Billing lock error: {e}")
            # В случае ошибки - выполняем (лучше потенциальное дублирование чем пропуск)
            yield True
