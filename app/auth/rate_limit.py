"""
Rate limiting для SMS с использованием Redis.
Поддерживает graceful degradation к in-memory если Redis недоступен.
"""
import logging
from typing import Tuple, Dict
from datetime import datetime

from app.services.redis_service import get_redis_service
from app.utils.time_utils import get_local_time

logger = logging.getLogger(__name__)

# Константы
SMS_COOLDOWN_SECONDS = 60     # Минимальный интервал между SMS
SMS_HOURLY_LIMIT = 5          # Максимум SMS в час

# Префиксы Redis ключей
SMS_LAST_SENT_PREFIX = "sms:last:"      # Время последней отправки
SMS_HOURLY_COUNT_PREFIX = "sms:count:"  # Счетчик за час
SMS_HOUR_START_PREFIX = "sms:hour:"     # Начало текущего часа

# TTL
SMS_CACHE_TTL = 3600  # 1 час

# Системные номера (без rate limit)
SYSTEM_PHONE_NUMBERS = {
    "70000000000",   # админ
    "71234567890",   # механик
    "71234567898",   # МВД
    "71234567899",   # финансист
    "79999999999",   # бухгалтер
    "71231111111",   # владелец автомобилей
}

# Fallback in-memory кэш (когда Redis недоступен)
_fallback_cache: Dict[str, dict] = {}


class SMSRateLimit:
    """Rate limiting для SMS отправки."""

    @staticmethod
    async def check(phone_number: str) -> Tuple[bool, str]:
        """
        Проверить rate limit для SMS.

        Args:
            phone_number: номер телефона

        Returns:
            Tuple[can_send: bool, error_message: str]
        """
        # Системные номера - без лимита
        if phone_number in SYSTEM_PHONE_NUMBERS:
            return True, ""

        redis = get_redis_service()

        if redis.is_available:
            return await SMSRateLimit._check_redis(phone_number)
        else:
            return SMSRateLimit._check_memory(phone_number)

    @staticmethod
    async def update(phone_number: str) -> None:
        """
        Обновить счетчики после успешной отправки SMS.
        """
        if phone_number in SYSTEM_PHONE_NUMBERS:
            return

        redis = get_redis_service()

        if redis.is_available:
            await SMSRateLimit._update_redis(phone_number)
        else:
            SMSRateLimit._update_memory(phone_number)

    # === Redis Implementation ===

    @staticmethod
    async def _check_redis(phone_number: str) -> Tuple[bool, str]:
        """Проверка через Redis."""
        redis = get_redis_service()
        now = get_local_time()
        now_ts = int(now.timestamp())

        # Ключи
        last_key = f"{SMS_LAST_SENT_PREFIX}{phone_number}"
        count_key = f"{SMS_HOURLY_COUNT_PREFIX}{phone_number}"
        hour_key = f"{SMS_HOUR_START_PREFIX}{phone_number}"

        # Проверка cooldown
        last_sent_ts = await redis.get(last_key)
        if last_sent_ts:
            elapsed = now_ts - int(last_sent_ts)
            if elapsed < SMS_COOLDOWN_SECONDS:
                remaining = SMS_COOLDOWN_SECONDS - elapsed
                return False, f"Подождите {remaining} секунд перед повторной отправкой SMS"

        # Проверка часового лимита
        hour_start_ts = await redis.get(hour_key)
        if hour_start_ts:
            # Проверяем, прошел ли час
            if now_ts - int(hour_start_ts) < 3600:
                count_str = await redis.get(count_key)
                count = int(count_str) if count_str else 0
                if count >= SMS_HOURLY_LIMIT:
                    return False, "Превышен лимит SMS. Попробуйте через час."

        return True, ""

    @staticmethod
    async def _update_redis(phone_number: str) -> None:
        """Обновление счетчиков в Redis."""
        redis = get_redis_service()
        now = get_local_time()
        now_ts = int(now.timestamp())

        # Ключи
        last_key = f"{SMS_LAST_SENT_PREFIX}{phone_number}"
        count_key = f"{SMS_HOURLY_COUNT_PREFIX}{phone_number}"
        hour_key = f"{SMS_HOUR_START_PREFIX}{phone_number}"

        # Обновляем время последней отправки
        await redis.set(last_key, now_ts, ttl=SMS_CACHE_TTL)

        # Проверяем/обновляем часовой счетчик
        hour_start_ts = await redis.get(hour_key)

        if not hour_start_ts or (now_ts - int(hour_start_ts) >= 3600):
            # Начинаем новый час
            await redis.set(hour_key, now_ts, ttl=SMS_CACHE_TTL)
            await redis.set(count_key, 1, ttl=SMS_CACHE_TTL)
        else:
            # Инкрементируем счетчик
            await redis.incr(count_key)

    # === In-Memory Fallback ===

    @staticmethod
    def _check_memory(phone_number: str) -> Tuple[bool, str]:
        """Проверка через in-memory (fallback)."""
        now = get_local_time()

        if phone_number not in _fallback_cache:
            return True, ""

        cache = _fallback_cache[phone_number]

        # Cooldown
        last_sent = cache.get("last_sent")
        if last_sent:
            elapsed = (now - last_sent).total_seconds()
            if elapsed < SMS_COOLDOWN_SECONDS:
                remaining = int(SMS_COOLDOWN_SECONDS - elapsed)
                return False, f"Подождите {remaining} секунд перед повторной отправкой SMS"

        # Hourly limit
        hour_start = cache.get("hour_start")
        if hour_start and (now - hour_start).total_seconds() < 3600:
            hourly_count = cache.get("hourly_count", 0)
            if hourly_count >= SMS_HOURLY_LIMIT:
                return False, "Превышен лимит SMS. Попробуйте через час."

        return True, ""

    @staticmethod
    def _update_memory(phone_number: str) -> None:
        """Обновление in-memory счетчиков."""
        now = get_local_time()

        if phone_number not in _fallback_cache:
            _fallback_cache[phone_number] = {
                "last_sent": now,
                "hourly_count": 1,
                "hour_start": now
            }
        else:
            cache = _fallback_cache[phone_number]
            hour_start = cache.get("hour_start")

            if not hour_start or (now - hour_start).total_seconds() >= 3600:
                cache["hour_start"] = now
                cache["hourly_count"] = 1
            else:
                cache["hourly_count"] = cache.get("hourly_count", 0) + 1

            cache["last_sent"] = now
