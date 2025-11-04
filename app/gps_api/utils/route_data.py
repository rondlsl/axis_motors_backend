import httpx
import logging
import urllib.parse
import re
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from app.owner.schemas import RouteData, DailyRoute, GPSCoordinate

# Настройка логгера
logger = logging.getLogger(__name__)


def _normalize_date_for_cars_api(date_str: str) -> str:
    if not date_str:
        return date_str
    
    s = date_str.strip()
    
    if ' ' in s and 'T' not in s:
        parts = s.split('.')
        return parts[0]
    
    if 'T' in s:
        s = s.replace('T', ' ')
        if s.endswith('Z'):
            s = s[:-1]
        s = re.sub(r'[+-]\d{2}:\d{2}$', '', s).strip()
        
        if '.' in s:
            s = s.split('.')[0]
        
        if len(s) == 10:
            s = s + ' 00:00:00'
        
        return s
    
    if len(s) == 10 and s.count('-') == 2:
        return s + ' 00:00:00'
    
    return s


async def get_gps_route_data(
    device_id: str, 
    start_date: str, 
    end_date: str
) -> Optional[RouteData]:
    """
    Получает данные маршрута от внешнего GPS API.
    
    :param device_id: ID GPS устройства (gps_id из таблицы cars)
    :param start_date: Дата и время начала поездки (ISO или формат БД: 2025-11-02 16:20:27.125412)
    :param end_date: Дата и время окончания поездки (ISO или формат БД: 2025-11-02 16:20:27.125412)
    :return: Данные маршрута или None при ошибке
    """
    try:
        start_q = _normalize_date_for_cars_api(start_date)
        end_q = _normalize_date_for_cars_api(end_date)
        
        start_encoded = urllib.parse.quote(start_q)
        end_encoded = urllib.parse.quote(end_q)
        
        url = f"http://195.93.152.69:8667/vehicles/{device_id}/gps?start_date={start_encoded}&end_date={end_encoded}"
        headers = {"accept": "application/json"}
        
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(url, headers=headers)
                
                # Выводим сырой ответ для диагностики
                response_text = response.text
                
                if response.status_code != 200:
                    logger.error(f"DEBUG GPS: Non-200 status code: {response.status_code}")
                    logger.error(f"DEBUG GPS: Response text: {response_text}")
                    return None
                
                try:
                    data = response.json()
                except Exception as json_e:
                    logger.error(f"DEBUG GPS: JSON parse error: {json_e}")
                    logger.error(f"DEBUG GPS: Response text: {response_text}")
                    return None
                
                if not data:
                    logger.warning("DEBUG GPS: No data in response")
                    return None
                    
                if "coordinates" not in data:
                    logger.warning("DEBUG GPS: No coordinates key in response")
                    logger.warning(f"DEBUG GPS: Available keys: {list(data.keys())}")
                    return None
                    
                coordinates_list = data["coordinates"]
                if not coordinates_list:
                    logger.warning("DEBUG GPS: Empty coordinates list")
                    return None
                
                coordinates = []
                for i, coord in enumerate(coordinates_list):
                    try:
                        gps_coord = GPSCoordinate(
                            lat=coord["lat"],
                            lon=coord["lon"], 
                            altitude=coord["altitude"],
                            timestamp=coord["timestamp"]
                        )
                        coordinates.append(gps_coord)
                    except Exception as coord_e:
                        logger.error(f"DEBUG GPS: Error processing coordinate {i}: {coord_e}")
                        logger.error(f"DEBUG GPS: Problematic coordinate: {coord}")
                        # Продолжаем с другими координатами
                        continue
                
                # Фильтруем координаты по временному диапазону и группируем по дням
                daily_routes = _group_coordinates_by_day(coordinates, start_date, end_date)
                
                route_data = RouteData(
                    device_id=data.get("device_id", device_id),
                    start_date=start_date,
                    end_date=end_date,
                    total_coordinates=data.get("count", len(coordinates)),
                    daily_routes=daily_routes,
                    fuel_start=data.get("fuel", {}).get("start") if data.get("fuel") else None,
                    fuel_end=data.get("fuel", {}).get("end") if data.get("fuel") else None
                )
                
                return route_data
                
            except Exception as e:
                logger.error(f"DEBUG GPS: Request failed: {e}")
                return None
            
    except Exception as e:
        logger.error(f"DEBUG GPS: Exception occurred for device {device_id}: {e}")
        import traceback
        logger.error(f"DEBUG GPS: Full traceback: {traceback.format_exc()}")
        return None


def _group_coordinates_by_day(
    coordinates: List[GPSCoordinate], 
    start_date: str, 
    end_date: str
) -> List[DailyRoute]:
    """
    Группирует координаты по дням.
    
    :param coordinates: Список всех координат
    :param start_date: Дата начала поездки в ISO формате (после apply_offset)
    :param end_date: Дата окончания поездки в ISO формате (после apply_offset)
    :return: Список маршрутов по дням
    """
    if not coordinates:
        return []
    
    try:
        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
    except ValueError as e:
        logger.error(f"Error parsing dates: start_date={start_date}, end_date={end_date}, error={e}")
        return []
    
    def _parse_ts(ts: str) -> datetime:
        try:
            return datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except Exception:
            return datetime.strptime(ts.split('T')[0], '%Y-%m-%d')

    filtered = [c for c in coordinates if start_dt <= _parse_ts(c.timestamp) <= end_dt]
    if not filtered:
        return []

    # 2) Группируем по дате timestamp реальных точек (без пропорциональных разрезов)
    buckets: dict[str, list[GPSCoordinate]] = {}
    for c in filtered:
        d = _parse_ts(c.timestamp).date().strftime('%Y-%m-%d')
        buckets.setdefault(d, []).append(c)

    # 3) Собираем список по возрастанию даты
    daily_routes: List[DailyRoute] = []
    for day in sorted(buckets.keys()):
        daily_routes.append(DailyRoute(date=day, coordinates=buckets[day]))

    return daily_routes
