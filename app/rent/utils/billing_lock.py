"""
Distributed Lock для billing job.
Гарантирует, что только один инстанс выполняет billing одновременно.

Алгоритм:
- SET NX EX (atomic set if not exists with expiry)
- Timeout 120 сек - автоматический release при падении инстанса
- Blocking timeout 0.1 сек - не ждём, сразу пропускаем

Защита от race condition:
- Redis lock с уникальным token для safe release
- При падении инстанса - автоматический release через TTL
"""
import logging
import time
import uuid
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from app.services.redis_service import get_redis_service

logger = logging.getLogger(__name__)

# Настройки лока
BILLING_LOCK_NAME = "billing_job"
BILLING_LOCK_TIMEOUT = 120.0  # 2 минуты максимум удержания
BILLING_LOCK_BLOCKING_TIMEOUT = 0.1  # Не ждем, сразу пропускаем

# Уникальный идентификатор инстанса (для отладки)
INSTANCE_ID = str(uuid.uuid4())[:8]


class BillingLock:
    """
    Управление distributed lock для billing.

    Thread-safe и работает корректно при нескольких инстансах.
    Использует Redis SET NX EX для атомарного захвата лока.
    """

    # Счётчик для отслеживания статистики
    _acquired_count: int = 0
    _skipped_count: int = 0
    _error_count: int = 0

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
        start_time = time.monotonic()

        # Если Redis недоступен - выполняем без лока (single instance fallback)
        if not redis.is_available:
            logger.debug(f"[{INSTANCE_ID}] Redis unavailable, executing billing without lock")
            yield True
            return

        try:
            async with redis.lock(
                BILLING_LOCK_NAME,
                timeout=BILLING_LOCK_TIMEOUT,
                blocking_timeout=BILLING_LOCK_BLOCKING_TIMEOUT
            ) as lock:
                if lock is not None:
                    BillingLock._acquired_count += 1
                    logger.debug(f"[{INSTANCE_ID}] Billing lock acquired (total: {BillingLock._acquired_count})")
                    try:
                        yield True
                    finally:
                        elapsed = time.monotonic() - start_time
                        if elapsed > 60:
                            logger.warning(f"[{INSTANCE_ID}] Billing job took {elapsed:.1f}s (> 60s)")
                else:
                    BillingLock._skipped_count += 1
                    logger.debug(f"[{INSTANCE_ID}] Lock held by another instance, skipping (total skipped: {BillingLock._skipped_count})")
                    yield False
        except Exception as e:
            BillingLock._error_count += 1
            logger.error(f"[{INSTANCE_ID}] Billing lock error (total errors: {BillingLock._error_count}): {e}")
            # В случае ошибки - выполняем (лучше потенциальное дублирование чем пропуск)
            yield True

    @staticmethod
    def get_stats() -> dict:
        """Получить статистику использования лока."""
        return {
            "instance_id": INSTANCE_ID,
            "acquired": BillingLock._acquired_count,
            "skipped": BillingLock._skipped_count,
            "errors": BillingLock._error_count,
        }
