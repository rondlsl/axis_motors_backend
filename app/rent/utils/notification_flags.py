"""
Distributed Notification Flags для billing.

Хранит состояние уведомлений в Redis для предотвращения дублей 
при перезапуске и в кластерном режиме.

Key Design:
    billing:notify:{rent_id} → HASH
    
Поля:
    - pre_waiting, waiting, pre_overtime, overtime: bool флаги (0/1)
    - low_balance_1000, low_balance_zero, telegram_10min_alert: bool флаги
    - low_fuel_alert, fuel_finalized, engine_lock_scheduled: bool флаги
    - balance_zero_at: ISO timestamp или None
    - driver_hours_paid, driver_days_paid: int счётчики
    - overtime_minutes_charged, minutes_charged: int счётчики

TTL: 24 часа - автоочистка завершённых аренд

Graceful degradation:
    При недоступности Redis - fallback на in-memory dict с предупреждением.
"""
import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from app.services.redis_service import get_redis_service

logger = logging.getLogger(__name__)

# Префикс для Redis ключей
KEY_PREFIX = "billing:notify"

# TTL в секундах (24 часа)
# Активные аренды продлевают TTL при каждом обращении
# Завершённые - автоматически удаляются
FLAGS_TTL = 86400

# Fallback in-memory storage при недоступности Redis
# ВАЖНО: Используется только как последний fallback
_fallback_flags: dict[int, dict[str, Any]] = {}


def _key(rent_id: int | UUID) -> str:
    """Генерация Redis ключа для аренды."""
    return f"{KEY_PREFIX}:{rent_id}"


# === Boolean Flag Operations ===

async def get_flag(rent_id: int | UUID, flag_name: str) -> bool:
    """
    Получить значение boolean флага.
    
    Args:
        rent_id: ID аренды
        flag_name: Имя флага (pre_waiting, waiting, low_balance_1000, etc.)
        
    Returns:
        True если флаг установлен, False иначе
    """
    redis = get_redis_service()
    
    if not redis.is_available or not redis.client:
        return _fallback_flags.get(rent_id, {}).get(flag_name, False)
    
    try:
        value = await redis.client.hget(_key(rent_id), flag_name)
        return value == "1"
    except Exception as e:
        logger.error(f"Redis HGET error for billing flag {rent_id}:{flag_name}: {e}")
        return _fallback_flags.get(rent_id, {}).get(flag_name, False)


async def set_flag(rent_id: int | UUID, flag_name: str, value: bool = True) -> bool:
    """
    Установить boolean флаг.
    
    Атомарная операция - безопасна для concurrent access.
    Автоматически продлевает TTL ключа.
    
    Args:
        rent_id: ID аренды
        flag_name: Имя флага
        value: Значение (True/False)
        
    Returns:
        True если успешно, False при ошибке
    """
    redis = get_redis_service()
    key = _key(rent_id)
    
    if not redis.is_available or not redis.client:
        _fallback_flags.setdefault(rent_id, {})[flag_name] = value
        return True
    
    try:
        # HSET + обновление TTL в pipeline для атомарности
        async with redis.client.pipeline(transaction=True) as pipe:
            await pipe.hset(key, flag_name, "1" if value else "0")
            await pipe.expire(key, FLAGS_TTL)
            await pipe.execute()
        return True
    except Exception as e:
        logger.error(f"Redis HSET error for billing flag {rent_id}:{flag_name}: {e}")
        # Fallback
        _fallback_flags.setdefault(rent_id, {})[flag_name] = value
        return False


async def set_flag_if_not_exists(rent_id: int | UUID, flag_name: str) -> bool:
    """
    Установить флаг только если он ещё не установлен (HSETNX).
    
    Атомарная операция - гарантирует "exactly once" семантику.
    Используется для предотвращения дублирования уведомлений.
    
    Args:
        rent_id: ID аренды
        flag_name: Имя флага
        
    Returns:
        True если флаг был установлен (т.е. раньше не существовал),
        False если флаг уже существовал
    """
    redis = get_redis_service()
    key = _key(rent_id)
    
    if not redis.is_available or not redis.client:
        flags = _fallback_flags.setdefault(rent_id, {})
        if flags.get(flag_name):
            return False
        flags[flag_name] = True
        return True
    
    try:
        # HSETNX + EXPIRE в pipeline для атомарности
        # Без pipeline: crash между HSETNX и EXPIRE = ключ без TTL = memory leak
        async with redis.client.pipeline(transaction=True) as pipe:
            await pipe.hsetnx(key, flag_name, "1")
            await pipe.expire(key, FLAGS_TTL)
            results = await pipe.execute()
        return results[0] == 1  # HSETNX result
    except Exception as e:
        logger.error(f"Redis HSETNX error for billing flag {rent_id}:{flag_name}: {e}")
        # Fallback - менее строгая гарантия, но лучше чем ничего
        flags = _fallback_flags.setdefault(rent_id, {})
        if flags.get(flag_name):
            return False
        flags[flag_name] = True
        return True


# === Counter Operations ===

async def get_counter(rent_id: int | UUID, counter_name: str) -> int:
    """
    Получить значение счётчика.
    
    Args:
        rent_id: ID аренды
        counter_name: Имя счётчика (driver_hours_paid, overtime_minutes_charged, etc.)
        
    Returns:
        Значение счётчика (0 если не существует)
    """
    redis = get_redis_service()
    
    if not redis.is_available or not redis.client:
        return _fallback_flags.get(rent_id, {}).get(counter_name, 0)
    
    try:
        value = await redis.client.hget(_key(rent_id), counter_name)
        return int(value) if value else 0
    except Exception as e:
        logger.error(f"Redis HGET error for billing counter {rent_id}:{counter_name}: {e}")
        return _fallback_flags.get(rent_id, {}).get(counter_name, 0)


async def set_counter(rent_id: int | UUID, counter_name: str, value: int) -> bool:
    """
    Установить значение счётчика.
    
    Args:
        rent_id: ID аренды
        counter_name: Имя счётчика
        value: Новое значение
        
    Returns:
        True если успешно
    """
    redis = get_redis_service()
    key = _key(rent_id)
    
    if not redis.is_available or not redis.client:
        _fallback_flags.setdefault(rent_id, {})[counter_name] = value
        return True
    
    try:
        async with redis.client.pipeline(transaction=True) as pipe:
            await pipe.hset(key, counter_name, str(value))
            await pipe.expire(key, FLAGS_TTL)
            await pipe.execute()
        return True
    except Exception as e:
        logger.error(f"Redis HSET error for billing counter {rent_id}:{counter_name}: {e}")
        _fallback_flags.setdefault(rent_id, {})[counter_name] = value
        return False


# === Timestamp Operations ===

async def get_timestamp(rent_id: int | UUID, field_name: str) -> Optional[datetime]:
    """
    Получить timestamp из Redis.
    
    Args:
        rent_id: ID аренды
        field_name: Имя поля (balance_zero_at, etc.)
        
    Returns:
        datetime объект или None
    """
    redis = get_redis_service()
    
    if not redis.is_available or not redis.client:
        return _fallback_flags.get(rent_id, {}).get(field_name)
    
    try:
        value = await redis.client.hget(_key(rent_id), field_name)
        if value:
            return datetime.fromisoformat(value)
        return None
    except Exception as e:
        logger.error(f"Redis HGET error for billing timestamp {rent_id}:{field_name}: {e}")
        return _fallback_flags.get(rent_id, {}).get(field_name)


async def set_timestamp(rent_id: int | UUID, field_name: str, value: datetime) -> bool:
    """
    Установить timestamp в Redis.
    
    Args:
        rent_id: ID аренды
        field_name: Имя поля
        value: datetime объект
        
    Returns:
        True если успешно
    """
    redis = get_redis_service()
    key = _key(rent_id)
    
    if not redis.is_available or not redis.client:
        _fallback_flags.setdefault(rent_id, {})[field_name] = value
        return True
    
    try:
        async with redis.client.pipeline(transaction=True) as pipe:
            await pipe.hset(key, field_name, value.isoformat())
            await pipe.expire(key, FLAGS_TTL)
            await pipe.execute()
        return True
    except Exception as e:
        logger.error(f"Redis HSET error for billing timestamp {rent_id}:{field_name}: {e}")
        _fallback_flags.setdefault(rent_id, {})[field_name] = value
        return False


async def set_timestamp_if_not_exists(rent_id: int | UUID, field_name: str, value: datetime) -> bool:
    """
    Установить timestamp только если поле не существует.
    
    Returns:
        True если timestamp был установлен (т.е. раньше не существовал)
    """
    redis = get_redis_service()
    key = _key(rent_id)
    
    if not redis.is_available or not redis.client:
        flags = _fallback_flags.setdefault(rent_id, {})
        if field_name in flags:
            return False
        flags[field_name] = value
        return True
    
    try:
        # HSETNX + EXPIRE в pipeline для атомарности
        async with redis.client.pipeline(transaction=True) as pipe:
            await pipe.hsetnx(key, field_name, value.isoformat())
            await pipe.expire(key, FLAGS_TTL)
            results = await pipe.execute()
        return results[0] == 1  # HSETNX result
    except Exception as e:
        logger.error(f"Redis HSETNX error for billing timestamp {rent_id}:{field_name}: {e}")
        flags = _fallback_flags.setdefault(rent_id, {})
        if field_name in flags:
            return False
        flags[field_name] = value
        return True


# === Bulk Operations ===

async def get_all_flags(rent_id: int | UUID) -> dict[str, Any]:
    """
    Получить все флаги для аренды.
    
    Returns:
        Dict со всеми флагами и счётчиками
    """
    redis = get_redis_service()
    
    if not redis.is_available or not redis.client:
        return _fallback_flags.get(rent_id, {}).copy()
    
    try:
        raw = await redis.client.hgetall(_key(rent_id))
        if not raw:
            return {}
        
        # Преобразуем типы
        result: dict[str, Any] = {}
        bool_fields = {
            "pre_waiting", "waiting", "pre_overtime", "overtime",
            "low_balance_1000", "low_balance_zero", "telegram_10min_alert",
            "low_fuel_alert", "fuel_finalized", "engine_lock_scheduled"
        }
        int_fields = {
            "driver_hours_paid", "driver_days_paid", 
            "overtime_minutes_charged", "minutes_charged"
        }
        timestamp_fields = {"balance_zero_at"}
        
        for key, value in raw.items():
            if key in bool_fields:
                result[key] = value == "1"
            elif key in int_fields:
                result[key] = int(value) if value else 0
            elif key in timestamp_fields:
                try:
                    result[key] = datetime.fromisoformat(value) if value else None
                except ValueError:
                    result[key] = None
            else:
                result[key] = value
        
        return result
    except Exception as e:
        logger.error(f"Redis HGETALL error for billing flags {rent_id}: {e}")
        return _fallback_flags.get(rent_id, {}).copy()


async def delete_flags(rent_id: int | UUID) -> bool:
    """
    Удалить все флаги для аренды (при завершении).
    
    Args:
        rent_id: ID аренды
        
    Returns:
        True если успешно
    """
    redis = get_redis_service()
    
    # Очищаем fallback
    _fallback_flags.pop(rent_id, None)
    
    if not redis.is_available or not redis.client:
        return True
    
    try:
        await redis.client.delete(_key(rent_id))
        return True
    except Exception as e:
        logger.error(f"Redis DELETE error for billing flags {rent_id}: {e}")
        return False


async def cleanup_inactive_rentals(active_rent_ids: set[int | UUID]) -> int:
    """
    Очистка флагов для завершённых аренд.
    
    Вызывается в конце billing job для очистки fallback storage.
    Redis очищается автоматически по TTL.
    
    Args:
        active_rent_ids: Set активных ID аренд
        
    Returns:
        Количество очищенных записей
    """
    cleaned = 0
    
    # Очищаем только fallback (Redis сам очистится по TTL)
    for rid in list(_fallback_flags.keys()):
        if rid not in active_rent_ids:
            _fallback_flags.pop(rid, None)
            cleaned += 1
    
    if cleaned > 0:
        logger.debug(f"Cleaned up {cleaned} inactive rental flags from fallback storage")
    
    return cleaned


# === Batch Operations for Sync Code ===

async def load_flags_batch(rent_ids: list[int | UUID]) -> dict[int | UUID, dict[str, Any]]:
    """
    Загрузить флаги для множества аренд одним batch запросом.
    
    Используется для загрузки флагов перед sync обработкой в billing job.
    
    Args:
        rent_ids: Список ID аренд
        
    Returns:
        Dict {rent_id: {flag_name: value, ...}}
    """
    redis = get_redis_service()
    result: dict[int | UUID, dict[str, Any]] = {}
    
    if not rent_ids:
        return result
    
    if not redis.is_available or not redis.client:
        for rid in rent_ids:
            result[rid] = _fallback_flags.get(rid, {}).copy()
        return result
    
    try:
        # Используем pipeline для batch загрузки
        async with redis.client.pipeline(transaction=False) as pipe:
            for rid in rent_ids:
                await pipe.hgetall(_key(rid))
            raw_results = await pipe.execute()
        
        bool_fields = {
            "pre_waiting", "waiting", "pre_overtime", "overtime",
            "low_balance_1000", "low_balance_zero", "telegram_10min_alert",
            "low_fuel_alert", "fuel_finalized", "engine_lock_scheduled"
        }
        int_fields = {
            "driver_hours_paid", "driver_days_paid", 
            "overtime_minutes_charged", "minutes_charged"
        }
        timestamp_fields = {"balance_zero_at"}
        
        for rid, raw in zip(rent_ids, raw_results):
            if not raw:
                result[rid] = {}
                continue
            
            flags: dict[str, Any] = {}
            for key, value in raw.items():
                if key in bool_fields:
                    flags[key] = value == "1"
                elif key in int_fields:
                    flags[key] = int(value) if value else 0
                elif key in timestamp_fields:
                    try:
                        flags[key] = datetime.fromisoformat(value) if value else None
                    except ValueError:
                        flags[key] = None
                else:
                    flags[key] = value
            result[rid] = flags
        
        return result
        
    except Exception as e:
        logger.error(f"Redis batch load error for billing flags: {e}")
        # Fallback
        for rid in rent_ids:
            result[rid] = _fallback_flags.get(rid, {}).copy()
        return result


async def save_flags_batch(flags_dict: dict[int | UUID, dict[str, Any]]) -> int:
    """
    Сохранить флаги для множества аренд одним batch запросом.
    
    Используется для сохранения флагов после sync обработки в billing job.
    
    Args:
        flags_dict: Dict {rent_id: {flag_name: value, ...}}
        
    Returns:
        Количество успешно сохранённых записей
    """
    redis = get_redis_service()
    saved = 0
    
    if not flags_dict:
        return saved
    
    # Обновляем fallback storage
    for rid, flags in flags_dict.items():
        _fallback_flags[rid] = flags.copy()
    
    if not redis.is_available or not redis.client:
        return len(flags_dict)
    
    try:
        async with redis.client.pipeline(transaction=False) as pipe:
            for rid, flags in flags_dict.items():
                if not flags:
                    continue
                
                key = _key(rid)
                mapping = {}
                
                for field, value in flags.items():
                    if isinstance(value, bool):
                        mapping[field] = "1" if value else "0"
                    elif isinstance(value, datetime):
                        mapping[field] = value.isoformat()
                    elif isinstance(value, (int, float)):
                        mapping[field] = str(int(value))
                    elif value is not None:
                        mapping[field] = str(value)
                
                if mapping:
                    await pipe.hset(key, mapping=mapping)
                    await pipe.expire(key, FLAGS_TTL)
                    saved += 1
            
            await pipe.execute()
        
        return saved
        
    except Exception as e:
        logger.error(f"Redis batch save error for billing flags: {e}")
        return len(flags_dict)  # Fallback сохранён


async def delete_flags_batch(rent_ids: list[int | UUID]) -> int:
    """
    Удалить флаги для множества завершённых аренд.
    
    Args:
        rent_ids: Список ID аренд для удаления
        
    Returns:
        Количество удалённых записей
    """
    redis = get_redis_service()
    
    if not rent_ids:
        return 0
    
    # Очищаем fallback
    for rid in rent_ids:
        _fallback_flags.pop(rid, None)
    
    if not redis.is_available or not redis.client:
        return len(rent_ids)
    
    try:
        keys = [_key(rid) for rid in rent_ids]
        deleted = await redis.client.delete(*keys)
        return deleted
    except Exception as e:
        logger.error(f"Redis batch delete error for billing flags: {e}")
        return 0


# === Migration Helper ===

async def migrate_from_memory(memory_flags: dict[int, dict[str, Any]]) -> int:
    """
    Миграция данных из in-memory dict в Redis.
    
    Полезно при первом деплое новой версии.
    
    Args:
        memory_flags: Старый in-memory dict
        
    Returns:
        Количество мигрированных записей
    """
    redis = get_redis_service()
    
    if not redis.is_available or not redis.client:
        logger.warning("Cannot migrate to Redis - service unavailable")
        return 0
    
    migrated = 0
    for rent_id, flags in memory_flags.items():
        try:
            key = _key(rent_id)
            mapping = {}
            
            for field, value in flags.items():
                if isinstance(value, bool):
                    mapping[field] = "1" if value else "0"
                elif isinstance(value, datetime):
                    mapping[field] = value.isoformat()
                elif isinstance(value, (int, float)):
                    mapping[field] = str(int(value))
                elif value is not None:
                    mapping[field] = str(value)
            
            if mapping:
                await redis.client.hset(key, mapping=mapping)
                await redis.client.expire(key, FLAGS_TTL)
                migrated += 1
                
        except Exception as e:
            logger.error(f"Migration error for rent_id {rent_id}: {e}")
    
    logger.info(f"Migrated {migrated} rental flags to Redis")
    return migrated
