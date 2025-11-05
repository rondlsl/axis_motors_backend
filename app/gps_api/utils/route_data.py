import httpx
import logging
import urllib.parse
import re
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from app.owner.schemas import RouteData, DailyRoute, GPSCoordinate

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


def _add_timezone_offset_for_api(date_str: str, hours_offset: int = 5) -> str:
    if not date_str:
        return date_str
    
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        dt_offset = dt + timedelta(hours=hours_offset)
        return dt_offset.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, AttributeError) as e:
        logger.warning(f"Error adding timezone offset to date '{date_str}': {e}")
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
        
        print(f"GPS API Request - device_id: {device_id}")
        print(f"GPS API Request - Original start_date: {start_date}")
        print(f"GPS API Request - Original end_date: {end_date}")
        print(f"GPS API Request - Normalized start_q: {start_q}")
        print(f"GPS API Request - Normalized end_q: {end_q}")
        print(f"GPS API Request - Encoded start: {start_encoded}")
        print(f"GPS API Request - Encoded end: {end_encoded}")
        print(f"GPS API Request - Full URL: {url}")
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(url, headers=headers)
                
                response_text = response.text
                
                print(f"GPS API Response - Status code: {response.status_code}")
                print(f"GPS API Response - Response text: {response_text[:500]}")  # Первые 500 символов
                logger.info(f"GPS API Response - Status code: {response.status_code}")
                logger.info(f"GPS API Response - Response text: {response_text}")
                
                if response.status_code != 200:
                    logger.error(f"DEBUG GPS: Non-200 status code: {response.status_code}")
                    logger.error(f"DEBUG GPS: Response text: {response_text}")
                    return None
                
                try:
                    data = response.json()
                    print(f"GPS API Response - Parsed JSON keys: {list(data.keys()) if data else 'None'}")
                    print(f"GPS API Response - Coordinates count: {len(data.get('coordinates', [])) if data and 'coordinates' in data else 0}")
                    logger.info(f"GPS API Response - Parsed JSON: {data}")
                except Exception as json_e:
                    logger.error(f"DEBUG GPS: JSON parse error: {json_e}")
                    logger.error(f"DEBUG GPS: Response text: {response_text}")
                    print(f"GPS API Response - JSON parse error: {json_e}")
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
                    print("DEBUG GPS: Empty coordinates list")
                    logger.warning("DEBUG GPS: Empty coordinates list")
                    return None
                
                print(f"DEBUG GPS: Processing {len(coordinates_list)} coordinates")
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
                        print(f"DEBUG GPS: Error processing coordinate {i}: {coord_e}")
                        print(f"DEBUG GPS: Problematic coordinate: {coord}")
                        logger.error(f"DEBUG GPS: Error processing coordinate {i}: {coord_e}")
                        logger.error(f"DEBUG GPS: Problematic coordinate: {coord}")
                        continue
                
                print(f"DEBUG GPS: Successfully processed {len(coordinates)} coordinates")
                print(f"DEBUG GPS: Calling _group_coordinates_by_day with start_date={start_date}, end_date={end_date}")
                
                period_start = data.get("period", {}).get("start") if data else None
                print(f"DEBUG GPS: Period start from API: {period_start}")
                
                try:
                    daily_routes = _group_coordinates_by_day(coordinates, start_date, end_date, period_start)
                    print(f"DEBUG GPS: Created {len(daily_routes)} daily routes")
                except Exception as daily_e:
                    print(f"DEBUG GPS: Error in _group_coordinates_by_day: {daily_e}")
                    logger.error(f"DEBUG GPS: Error in _group_coordinates_by_day: {daily_e}")
                    import traceback
                    logger.error(f"DEBUG GPS: Traceback: {traceback.format_exc()}")
                    raise
                
                print(f"DEBUG GPS: Creating RouteData object")
                try:
                    route_data = RouteData(
                        device_id=data.get("device_id", device_id),
                        start_date=start_date,
                        end_date=end_date,
                        total_coordinates=data.get("count", len(coordinates)),
                        daily_routes=daily_routes,
                        fuel_start=data.get("fuel", {}).get("start") if data.get("fuel") else None,
                        fuel_end=data.get("fuel", {}).get("end") if data.get("fuel") else None
                    )
                    print(f"DEBUG GPS: RouteData created successfully")
                    print(f"DEBUG GPS: RouteData device_id={route_data.device_id}, total_coordinates={route_data.total_coordinates}, daily_routes_count={len(route_data.daily_routes)}")
                    return route_data
                except Exception as route_e:
                    print(f"DEBUG GPS: Error creating RouteData: {route_e}")
                    logger.error(f"DEBUG GPS: Error creating RouteData: {route_e}")
                    import traceback
                    logger.error(f"DEBUG GPS: Traceback: {traceback.format_exc()}")
                    raise
                
            except Exception as e:
                print(f"DEBUG GPS: Request failed: {e}")
                import traceback
                print(f"DEBUG GPS: Traceback: {traceback.format_exc()}")
                logger.error(f"DEBUG GPS: Request failed: {e}")
                logger.error(f"DEBUG GPS: Traceback: {traceback.format_exc()}")
                return None
            
    except Exception as e:
        print(f"DEBUG GPS: Exception occurred for device {device_id}: {e}")
        import traceback
        print(f"DEBUG GPS: Full traceback: {traceback.format_exc()}")
        logger.error(f"DEBUG GPS: Exception occurred for device {device_id}: {e}")
        logger.error(f"DEBUG GPS: Full traceback: {traceback.format_exc()}")
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
        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
    except ValueError as e:
        logger.error(f"Error parsing dates: start_date={start_date}, end_date={end_date}, error={e}")
        return []
    
    period_start_dt = None
    if period_start:
        try:
            period_start_dt = datetime.fromisoformat(period_start.replace('Z', '+00:00'))
        except Exception as e:
            logger.warning(f"Error parsing period_start: {period_start}, error: {e}")
    
    def _parse_ts(ts) -> datetime:
        if isinstance(ts, int):
            if period_start_dt:
                return period_start_dt + timedelta(seconds=ts)
            else:
                return start_dt + timedelta(seconds=ts)
        elif isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts.replace('Z', '+00:00'))
            except Exception:
                try:
                    return datetime.strptime(ts.split('T')[0], '%Y-%m-%d')
                except Exception:
                    return start_dt
        else:
            return start_dt

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
