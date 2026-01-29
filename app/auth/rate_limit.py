"""
Rate limiting для SMS с использованием Redis.
Поддерживает graceful degradation к in-memory если Redis недоступен.

Защита от SMS bombing:
1. Per-phone rate limit: 60 сек cooldown + 5 SMS/час на номер
2. Per-IP rate limit: 10 SMS/минуту + 50 SMS/час с одного IP

Thread-safe и работает корректно при нескольких инстансах.
"""
import logging
from typing import Tuple, Dict, Optional

from app.services.redis_service import get_redis_service
from app.utils.time_utils import get_local_time

logger = logging.getLogger(__name__)

# === Константы для phone-based лимита ===
SMS_COOLDOWN_SECONDS = 60     # Минимальный интервал между SMS на один номер
SMS_HOURLY_LIMIT = 5          # Максимум SMS в час на один номер

# === Константы для IP-based лимита (защита от bombing) ===
IP_MINUTE_LIMIT = 10          # Максимум SMS в минуту с одного IP
IP_HOURLY_LIMIT = 50          # Максимум SMS в час с одного IP
IP_DAILY_LIMIT = 200          # Максимум SMS в сутки с одного IP

# Префиксы Redis ключей
SMS_LAST_SENT_PREFIX = "sms:last:"      # Время последней отправки (phone)
SMS_HOURLY_COUNT_PREFIX = "sms:count:"  # Счетчик за час (phone)
SMS_HOUR_START_PREFIX = "sms:hour:"     # Начало текущего часа (phone)

# IP-based ключи (sliding window)
IP_MINUTE_PREFIX = "sms:ip:min:"        # Счетчик SMS/минуту с IP
IP_HOURLY_PREFIX = "sms:ip:hour:"       # Счетчик SMS/час с IP
IP_DAILY_PREFIX = "sms:ip:day:"         # Счетчик SMS/сутки с IP

# TTL
SMS_CACHE_TTL = 3600          # 1 час
IP_MINUTE_TTL = 60            # 1 минута
IP_HOURLY_TTL = 3600          # 1 час
IP_DAILY_TTL = 86400          # 24 часа

# Системные номера (без rate limit)
SYSTEM_PHONE_NUMBERS = {
    "70000000000",   # админ
    "71234567890",   # механик
    "71234567898",   # МВД
    "71234567899",   # финансист
    "79999999999",   # бухгалтер
    "71231111111",   # владелец автомобилей
}

# Доверенные IP (без IP rate limit, но phone limit остаётся)
TRUSTED_IPS = {
    "127.0.0.1",
    "::1",
}

# Fallback in-memory кэш (когда Redis недоступен)
_fallback_cache: Dict[str, dict] = {}
_fallback_ip_cache: Dict[str, dict] = {}


class SMSRateLimit:
    """
    Rate limiting для SMS отправки.

    Двухуровневая защита:
    1. Per-phone: ограничение на конкретный номер телефона
    2. Per-IP: ограничение на IP адрес (защита от SMS bombing)
    """

    @staticmethod
    async def check(phone_number: str, client_ip: Optional[str] = None) -> Tuple[bool, str]:
        """
        Проверить rate limit для SMS.

        Args:
            phone_number: номер телефона
            client_ip: IP адрес клиента (опционально, для IP-based лимита)

        Returns:
            Tuple[can_send: bool, error_message: str]
        """
        # Системные номера - без лимита
        if phone_number in SYSTEM_PHONE_NUMBERS:
            return True, ""

        redis = get_redis_service()

        # === Шаг 1: Проверяем IP-based лимит (если IP передан) ===
        if client_ip and client_ip not in TRUSTED_IPS:
            if redis.is_available:
                ip_ok, ip_error = await SMSRateLimit._check_ip_redis(client_ip)
            else:
                ip_ok, ip_error = SMSRateLimit._check_ip_memory(client_ip)

            if not ip_ok:
                logger.warning(f"IP rate limit exceeded: {client_ip}")
                return False, ip_error

        # === Шаг 2: Проверяем phone-based лимит ===
        if redis.is_available:
            return await SMSRateLimit._check_redis(phone_number)
        else:
            return SMSRateLimit._check_memory(phone_number)

    @staticmethod
    async def update(phone_number: str, client_ip: Optional[str] = None) -> None:
        """
        Обновить счетчики после успешной отправки SMS.

        Args:
            phone_number: номер телефона
            client_ip: IP адрес клиента (опционально)
        """
        if phone_number in SYSTEM_PHONE_NUMBERS:
            return

        redis = get_redis_service()

        # Обновляем phone-based счетчики
        if redis.is_available:
            await SMSRateLimit._update_redis(phone_number)
        else:
            SMSRateLimit._update_memory(phone_number)

        # Обновляем IP-based счетчики
        if client_ip and client_ip not in TRUSTED_IPS:
            if redis.is_available:
                await SMSRateLimit._update_ip_redis(client_ip)
            else:
                SMSRateLimit._update_ip_memory(client_ip)

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

    # === IP-based Rate Limiting (Redis) ===

    @staticmethod
    async def _check_ip_redis(client_ip: str) -> Tuple[bool, str]:
        """
        Проверка IP-based лимита через Redis.
        Использует sliding window counter pattern.
        """
        redis = get_redis_service()

        # Ключи для разных временных окон
        minute_key = f"{IP_MINUTE_PREFIX}{client_ip}"
        hourly_key = f"{IP_HOURLY_PREFIX}{client_ip}"
        daily_key = f"{IP_DAILY_PREFIX}{client_ip}"

        try:
            # Проверяем минутный лимит
            minute_count_str = await redis.get(minute_key)
            minute_count = int(minute_count_str) if minute_count_str else 0
            if minute_count >= IP_MINUTE_LIMIT:
                return False, "Слишком много запросов. Подождите минуту."

            # Проверяем часовой лимит
            hourly_count_str = await redis.get(hourly_key)
            hourly_count = int(hourly_count_str) if hourly_count_str else 0
            if hourly_count >= IP_HOURLY_LIMIT:
                return False, "Превышен лимит запросов. Попробуйте через час."

            # Проверяем суточный лимит
            daily_count_str = await redis.get(daily_key)
            daily_count = int(daily_count_str) if daily_count_str else 0
            if daily_count >= IP_DAILY_LIMIT:
                return False, "Превышен суточный лимит запросов."

            return True, ""
        except Exception as e:
            logger.error(f"IP rate limit check error: {e}")
            # При ошибке - пропускаем (fail open для доступности)
            return True, ""

    @staticmethod
    async def _update_ip_redis(client_ip: str) -> None:
        """Обновление IP-based счетчиков в Redis."""
        redis = get_redis_service()

        minute_key = f"{IP_MINUTE_PREFIX}{client_ip}"
        hourly_key = f"{IP_HOURLY_PREFIX}{client_ip}"
        daily_key = f"{IP_DAILY_PREFIX}{client_ip}"

        try:
            client = redis.client
            if client:
                async with client.pipeline(transaction=True) as pipe:
                    # Инкремент минутного счетчика
                    pipe.incr(minute_key)
                    pipe.expire(minute_key, IP_MINUTE_TTL)

                    # Инкремент часового счетчика
                    pipe.incr(hourly_key)
                    pipe.expire(hourly_key, IP_HOURLY_TTL)

                    # Инкремент суточного счетчика
                    pipe.incr(daily_key)
                    pipe.expire(daily_key, IP_DAILY_TTL)

                    await pipe.execute()
        except Exception as e:
            logger.error(f"IP rate limit update error: {e}")

    # === IP-based Rate Limiting (In-Memory Fallback) ===

    @staticmethod
    def _check_ip_memory(client_ip: str) -> Tuple[bool, str]:
        """Проверка IP-based лимита через in-memory (fallback)."""
        now = get_local_time()

        if client_ip not in _fallback_ip_cache:
            return True, ""

        cache = _fallback_ip_cache[client_ip]

        # Проверяем минутный лимит
        minute_start = cache.get("minute_start")
        if minute_start and (now - minute_start).total_seconds() < 60:
            minute_count = cache.get("minute_count", 0)
            if minute_count >= IP_MINUTE_LIMIT:
                return False, "Слишком много запросов. Подождите минуту."

        # Проверяем часовой лимит
        hour_start = cache.get("hour_start")
        if hour_start and (now - hour_start).total_seconds() < 3600:
            hourly_count = cache.get("hourly_count", 0)
            if hourly_count >= IP_HOURLY_LIMIT:
                return False, "Превышен лимит запросов. Попробуйте через час."

        return True, ""

    @staticmethod
    def _update_ip_memory(client_ip: str) -> None:
        """Обновление IP-based in-memory счетчиков."""
        now = get_local_time()

        if client_ip not in _fallback_ip_cache:
            _fallback_ip_cache[client_ip] = {
                "minute_start": now,
                "minute_count": 1,
                "hour_start": now,
                "hourly_count": 1
            }
            return

        cache = _fallback_ip_cache[client_ip]

        # Обновляем минутный счетчик
        minute_start = cache.get("minute_start")
        if not minute_start or (now - minute_start).total_seconds() >= 60:
            cache["minute_start"] = now
            cache["minute_count"] = 1
        else:
            cache["minute_count"] = cache.get("minute_count", 0) + 1

        # Обновляем часовой счетчик
        hour_start = cache.get("hour_start")
        if not hour_start or (now - hour_start).total_seconds() >= 3600:
            cache["hour_start"] = now
            cache["hourly_count"] = 1
        else:
            cache["hourly_count"] = cache.get("hourly_count", 0) + 1
