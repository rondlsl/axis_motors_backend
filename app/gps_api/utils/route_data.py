import httpx
import urllib.parse
import re
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from app.owner.schemas import RouteData, DailyRoute, GPSCoordinate


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


def _add_timezone_offset_for_api(date_str: str, hours_offset: int = 5) -> str:
    if not date_str:
        return date_str
    
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        dt_offset = dt + timedelta(hours=hours_offset)
        return dt_offset.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, AttributeError):
        return date_str


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
                
                if response.status_code != 200:
                    return None
                
                try:
                    data = response.json()
                except Exception:
                    return None
                
                if not data or "coordinates" not in data:
                    return None
                    
                coordinates_list = data["coordinates"]
                if not coordinates_list:
                    return None
                
                coordinates = []
                for coord in coordinates_list:
                    try:
                        gps_coord = GPSCoordinate(
                            lat=coord["lat"],
                            lon=coord["lon"], 
                            altitude=coord["altitude"],
                            timestamp=coord["timestamp"]
                        )
                        coordinates.append(gps_coord)
                    except Exception:
                        continue
                
                period_start = data.get("period", {}).get("start") if data else None
                
                daily_routes = _group_coordinates_by_day(coordinates, start_date, end_date, period_start)
                
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
                
            except Exception:
                return None
            
    except Exception:
        return None


def _group_coordinates_by_day(
    coordinates: List[GPSCoordinate], 
    start_date: str, 
    end_date: str,
    period_start: Optional[str] = None
) -> List[DailyRoute]:
    """
    Группирует координаты по дням.
    
    :param coordinates: Список всех координат
    :param start_date: Дата начала поездки в ISO формате (после apply_offset)
    :param end_date: Дата окончания поездки в ISO формате (после apply_offset)
    :param period_start: Начало периода из API (для вычисления timestamp)
    :return: Список маршрутов по дням
    """
    if not coordinates:
        return []
    
    try:
        if 'T' in start_date or 'Z' in start_date:
            start_dt_str = start_date.replace('Z', '+00:00') if 'Z' in start_date else start_date
            start_dt = datetime.fromisoformat(start_dt_str)
        else:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S')
        
        if 'T' in end_date or 'Z' in end_date:
            end_dt_str = end_date.replace('Z', '+00:00') if 'Z' in end_date else end_date
            end_dt = datetime.fromisoformat(end_dt_str)
        else:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S')
        
        if start_dt.tzinfo:
            start_dt = start_dt.replace(tzinfo=None)
        if end_dt.tzinfo:
            end_dt = end_dt.replace(tzinfo=None)
        
        start_dt = start_dt - timedelta(hours=5)
        end_dt = end_dt - timedelta(hours=5)
    except (ValueError, AttributeError):
        return []
    
    period_start_dt = None
    if period_start:
        try:
            period_start_str = period_start.replace('Z', '+00:00') if 'Z' in period_start else period_start
            period_start_dt = datetime.fromisoformat(period_start_str)
            if period_start_dt.tzinfo:
                period_start_dt = period_start_dt.replace(tzinfo=None)
            # period_start уже в UTC, оставляем как есть
        except Exception:
            pass
    
    def _parse_ts(ts) -> datetime:
        if isinstance(ts, int):
            if period_start_dt:
                result = period_start_dt + timedelta(seconds=ts)
            else:
                result = start_dt + timedelta(seconds=ts)
            if result.tzinfo:
                result = result.replace(tzinfo=None)
            return result
        elif isinstance(ts, str):
            try:
                ts_str = ts.replace('Z', '+00:00') if 'Z' in ts else ts
                result = datetime.fromisoformat(ts_str)
                if result.tzinfo:
                    result = result.replace(tzinfo=None)
                return result
            except Exception:
                try:
                    result = datetime.strptime(ts.split('T')[0], '%Y-%m-%d')
                    if result.tzinfo:
                        result = result.replace(tzinfo=None)
                    return result
                except Exception:
                    result = start_dt
                    if result.tzinfo:
                        result = result.replace(tzinfo=None)
                    return result
        else:
            result = start_dt
            if result.tzinfo:
                result = result.replace(tzinfo=None)
            return result

    filtered = [c for c in coordinates if start_dt <= _parse_ts(c.timestamp) <= end_dt]
    if not filtered:
        return []

    buckets: dict[str, list[GPSCoordinate]] = {}
    for c in filtered:
        d = _parse_ts(c.timestamp).date().strftime('%Y-%m-%d')
        buckets.setdefault(d, []).append(c)

    daily_routes: List[DailyRoute] = []
    for day in sorted(buckets.keys()):
        daily_routes.append(DailyRoute(date=day, coordinates=buckets[day]))

    return daily_routes
