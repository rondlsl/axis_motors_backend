"""
GPS Telemetry Cache для снижения нагрузки на PostgreSQL.

Кэширует последние координаты и телеметрию в Redis.
UPDATE в БД происходит только при значимых изменениях.

Key Design:
    gps:vehicle:{gps_id} → HASH
    
Поля:
    - lat, lon: последние координаты
    - fuel: уровень топлива
    - mileage: пробег
    - updated_at: время последнего обновления кэша
    - last_db_update: время последнего UPDATE в БД

TTL: 3600 сек (1 час)

Diff-проверка:
    - Координаты: изменение > 10 метров → значимое
    - Топливо: |изменение| > 0.5 → значимое (ловит заправку и расход)
    - Пробег: любое изменение → всегда обновляем
    - Время: > 60 сек с последнего DB update → принудительный sync

Graceful degradation:
    При недоступности Redis - все UPDATE идут в БД напрямую.
"""
import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.services.redis_service import get_redis_service
from app.utils.time_utils import get_local_time

logger = logging.getLogger(__name__)

# Prefix для Redis ключей
KEY_PREFIX = "gps:vehicle"

# TTL в секундах (2 часа - защита от burst при Redis restart)
CACHE_TTL = 7200

# Пороги для определения "значимого" изменения
COORDINATE_THRESHOLD_METERS = 10.0  # 10 метров
FUEL_THRESHOLD_LITERS = 0.5  # 0.5 литра
MAX_TIME_WITHOUT_DB_UPDATE = 60  # секунд


@dataclass
class TelemetryData:
    """Структура данных телеметрии."""
    lat: Optional[float] = None
    lon: Optional[float] = None
    fuel: Optional[float] = None
    mileage: Optional[float] = None
    updated_at: Optional[datetime] = None
    last_db_update: Optional[datetime] = None


def _key(gps_id: str) -> str:
    """Генерация Redis ключа для машины."""
    return f"{KEY_PREFIX}:{gps_id}"


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Рассчитать расстояние между двумя точками по формуле Haversine.
    
    Returns:
        Расстояние в метрах
    """
    R = 6371000  # Радиус Земли в метрах
    
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_phi / 2) ** 2 + 
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def is_significant_change(
    cached: TelemetryData,
    new_lat: Optional[float],
    new_lon: Optional[float],
    new_fuel: Optional[float],
    new_mileage: Optional[float]
) -> tuple[bool, str]:
    """
    Проверить, является ли изменение значимым для записи в БД.
    
    ВАЖНО: Координаты ВСЕГДА записываются в БД для real-time отслеживания!
    Оптимизация применяется только для топлива.
    
    Логика:
    1. Координаты изменились (любое изменение > 1м) → UPDATE
    2. Топливо изменилось > 0.5л → UPDATE  
    3. Принудительный sync каждые 60 сек → UPDATE (для пробега и др.)
    
    Returns:
        (is_significant, reason)
    """
    now = get_local_time()
    
    # 1. Первое обновление - всегда записываем
    if cached.lat is None or cached.lon is None:
        return True, "first_update"
    
    # 2. КООРДИНАТЫ - всегда записываем при любом изменении > 1м
    # Это критично для real-time отслеживания машин на карте!
    if new_lat is not None and new_lon is not None:
        # Игнорируем нулевые координаты (GPS ошибка)
        if new_lat != 0.0 or new_lon != 0.0:
            distance = _haversine_distance(
                cached.lat, cached.lon,  # type: ignore
                new_lat, new_lon
            )
            # Порог 1м - фильтруем только GPS шум, но сохраняем все реальные перемещения
            if distance >= 1.0:
                return True, f"coords_changed_{distance:.1f}m"
    
    # 3. Принудительный sync по времени (для пробега и других данных)
    if cached.last_db_update:
        time_since_db = (now - cached.last_db_update).total_seconds()
        if time_since_db >= MAX_TIME_WITHOUT_DB_UPDATE:
            return True, f"time_sync_{int(time_since_db)}s"
    else:
        return True, "no_previous_db_update"
    
    # 4. Топливо - оптимизируем (изменение > 0.5л)
    if new_fuel is not None and cached.fuel is not None:
        fuel_change = abs(new_fuel - cached.fuel)
        if fuel_change >= FUEL_THRESHOLD_LITERS:
            return True, f"fuel_changed_{fuel_change:.1f}L"
    
    return False, "no_significant_change"


async def get_cached_telemetry(gps_id: str) -> TelemetryData:
    """
    Получить закэшированную телеметрию из Redis.
    
    Returns:
        TelemetryData с данными или пустую структуру если кэш пуст
    """
    redis = get_redis_service()
    
    if not redis.is_available or not redis.client:
        return TelemetryData()
    
    try:
        raw = await redis.client.hgetall(_key(gps_id))
        if not raw:
            return TelemetryData()
        
        data = TelemetryData()
        
        if 'lat' in raw:
            data.lat = float(raw['lat'])
        if 'lon' in raw:
            data.lon = float(raw['lon'])
        if 'fuel' in raw:
            data.fuel = float(raw['fuel'])
        if 'mileage' in raw:
            data.mileage = float(raw['mileage'])
        if 'updated_at' in raw:
            data.updated_at = datetime.fromisoformat(raw['updated_at'])
        if 'last_db_update' in raw:
            data.last_db_update = datetime.fromisoformat(raw['last_db_update'])
        
        return data
        
    except Exception as e:
        logger.error(f"Error getting cached telemetry for {gps_id}: {e}")
        return TelemetryData()


async def update_cache(
    gps_id: str,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    fuel: Optional[float] = None,
    mileage: Optional[float] = None,
    db_updated: bool = False
) -> bool:
    """
    Обновить кэш телеметрии в Redis.
    
    Args:
        gps_id: ID машины в GPS системе
        lat, lon: Координаты (если есть)
        fuel: Уровень топлива (если есть)
        mileage: Пробег (если есть)
        db_updated: True если данные были записаны в БД
        
    Returns:
        True если успешно обновлено
    """
    redis = get_redis_service()
    
    if not redis.is_available or not redis.client:
        return False
    
    try:
        now = get_local_time()
        key = _key(gps_id)
        
        mapping = {
            'updated_at': now.isoformat()
        }
        
        if lat is not None and (lat != 0.0 or lon != 0.0 if lon else True):
            mapping['lat'] = str(lat)
        if lon is not None and (lon != 0.0 or lat != 0.0 if lat else True):
            mapping['lon'] = str(lon)
        if fuel is not None and fuel != 0 and fuel != 0.0:
            mapping['fuel'] = str(fuel)
        if mileage is not None:
            mapping['mileage'] = str(mileage)
        if db_updated:
            mapping['last_db_update'] = now.isoformat()
        
        async with redis.client.pipeline(transaction=True) as pipe:
            await pipe.hset(key, mapping=mapping)
            if db_updated:
                await pipe.expire(key, CACHE_TTL)
            await pipe.execute()
        
        return True
        
    except Exception as e:
        logger.error(f"Error updating telemetry cache for {gps_id}: {e}")
        return False


async def should_update_db(
    gps_id: str,
    new_lat: Optional[float],
    new_lon: Optional[float],
    new_fuel: Optional[float],
    new_mileage: Optional[float]
) -> tuple[bool, str]:
    """
    Проверить, нужно ли обновлять БД для этого vehicle.
    
    Высокоуровневая функция - получает кэш и проверяет diff.
    
    Args:
        gps_id: ID машины в GPS системе
        new_*: Новые данные телеметрии
        
    Returns:
        (should_update, reason)
    """
    cached = await get_cached_telemetry(gps_id)
    return is_significant_change(cached, new_lat, new_lon, new_fuel, new_mileage)


# === Batch Operations for Sync Code ===

async def load_telemetry_batch(gps_ids: list[str]) -> dict[str, TelemetryData]:
    """
    Batch-загрузка телеметрии для множества машин.
    
    Используется перед sync обработкой для предзагрузки кэша.
    
    Returns:
        Dict {gps_id: TelemetryData}
    """
    redis = get_redis_service()
    result: dict[str, TelemetryData] = {}
    
    if not gps_ids:
        return result
    
    if not redis.is_available or not redis.client:
        for gps_id in gps_ids:
            result[gps_id] = TelemetryData()
        return result
    
    try:
        async with redis.client.pipeline(transaction=False) as pipe:
            for gps_id in gps_ids:
                await pipe.hgetall(_key(gps_id))
            raw_results = await pipe.execute()
        
        for gps_id, raw in zip(gps_ids, raw_results):
            if not raw:
                result[gps_id] = TelemetryData()
                continue
            
            data = TelemetryData()
            if 'lat' in raw:
                data.lat = float(raw['lat'])
            if 'lon' in raw:
                data.lon = float(raw['lon'])
            if 'fuel' in raw:
                data.fuel = float(raw['fuel'])
            if 'mileage' in raw:
                data.mileage = float(raw['mileage'])
            if 'updated_at' in raw:
                data.updated_at = datetime.fromisoformat(raw['updated_at'])
            if 'last_db_update' in raw:
                data.last_db_update = datetime.fromisoformat(raw['last_db_update'])
            
            result[gps_id] = data
        
        return result
        
    except Exception as e:
        logger.error(f"Error batch loading telemetry cache: {e}")
        for gps_id in gps_ids:
            result[gps_id] = TelemetryData()
        return result


async def save_telemetry_batch(
    updates: list[tuple[str, Optional[float], Optional[float], Optional[float], Optional[float], bool]]
) -> int:
    """
    Batch-сохранение телеметрии в Redis.
    
    Args:
        updates: List of (gps_id, lat, lon, fuel, mileage, db_updated)
        
    Returns:
        Количество успешно сохранённых записей
    """
    redis = get_redis_service()
    
    if not updates:
        return 0
    
    if not redis.is_available or not redis.client:
        return 0
    
    try:
        now = get_local_time()
        saved = 0
        
        async with redis.client.pipeline(transaction=False) as pipe:
            for gps_id, lat, lon, fuel, mileage, db_updated in updates:
                key = _key(gps_id)
                mapping = {
                    'updated_at': now.isoformat()
                }
                
                if lat is not None and (lat != 0.0 or lon != 0.0 if lon else True):
                    mapping['lat'] = str(lat)
                if lon is not None and (lon != 0.0 or lat != 0.0 if lat else True):
                    mapping['lon'] = str(lon)
                if fuel is not None and fuel != 0:
                    mapping['fuel'] = str(fuel)
                if mileage is not None:
                    mapping['mileage'] = str(mileage)
                if db_updated:
                    mapping['last_db_update'] = now.isoformat()
                
                await pipe.hset(key, mapping=mapping)
                # TTL обновляем только при значимом изменении (db_updated).
                # Иначе TTL бы сбрасывался каждую секунду и ключ никогда не истекал.
                if db_updated:
                    await pipe.expire(key, CACHE_TTL)
                saved += 1
            
            await pipe.execute()
        
        return saved
        
    except Exception as e:
        logger.error(f"Error batch saving telemetry cache: {e}")
        return 0


# === Statistics ===

class TelemetryStats:
    """Статистика работы кэша телеметрии."""
    
    _total_updates: int = 0
    _db_updates: int = 0
    _cache_only_updates: int = 0
    
    @classmethod
    def record_update(cls, db_updated: bool) -> None:
        """Записать статистику обновления."""
        cls._total_updates += 1
        if db_updated:
            cls._db_updates += 1
        else:
            cls._cache_only_updates += 1
    
    @classmethod
    def get_stats(cls) -> dict:
        """Получить статистику."""
        db_reduction = 0.0
        if cls._total_updates > 0:
            db_reduction = (cls._cache_only_updates / cls._total_updates) * 100
        
        return {
            "total_updates": cls._total_updates,
            "db_updates": cls._db_updates,
            "cache_only_updates": cls._cache_only_updates,
            "db_reduction_percent": round(db_reduction, 1)
        }
    
    @classmethod
    def reset(cls) -> None:
        """Сбросить статистику."""
        cls._total_updates = 0
        cls._db_updates = 0
        cls._cache_only_updates = 0
