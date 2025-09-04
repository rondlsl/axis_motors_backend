import httpx
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from app.owner.schemas import RouteData, DailyRoute, GPSCoordinate

# Настройка логгера
logger = logging.getLogger(__name__)


async def get_gps_route_data(
    device_id: str, 
    start_date: str, 
    end_date: str
) -> Optional[RouteData]:
    """
    Получает данные маршрута от внешнего GPS API.
    
    :param device_id: ID GPS устройства (gps_id из таблицы cars)
    :param start_date: Дата и время начала поездки в ISO формате (после apply_offset)
    :param end_date: Дата и время окончания поездки в ISO формате (после apply_offset)
    :return: Данные маршрута или None при ошибке
    """
    print(f"DEBUG GPS: Function called with device_id={device_id}, start_date={start_date}, end_date={end_date}")
    try:
        
        url = f"http://195.49.210.50:8666/vehicles/{device_id}/gps?start_date={start_date}&end_date={end_date}"
        headers = {"accept": "application/json"}
        
        print(f"DEBUG GPS: Making request to {url}")
        print(f"DEBUG GPS: Headers: {headers}")
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers)
            print(f"DEBUG GPS: Response status: {response.status_code}")
            print(f"DEBUG GPS: Response headers: {dict(response.headers)}")
            
            # Выводим сырой ответ для диагностики
            response_text = response.text
            print(f"DEBUG GPS: Raw response (first 500 chars): {response_text[:500]}")
            
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
                
            print(f"DEBUG GPS: Response data keys: {list(data.keys()) if data else 'None'}")
            print(f"DEBUG GPS: Coordinates count in response: {data.get('count', 0) if data else 0}")
            
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
                
            # Преобразуем координаты в наши модели
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
                    logger.error(f"DEBUG GPS: Error processing coordinate {i}: {coord_e}")
                    logger.error(f"DEBUG GPS: Problematic coordinate: {coord}")
                    # Продолжаем с другими координатами
                    continue
            
            print(f"DEBUG GPS: Successfully processed {len(coordinates)} coordinates")
            
            # Группируем координаты по дням
            daily_routes = _group_coordinates_by_day(coordinates, start_date, end_date)
            print(f"DEBUG GPS: Created {len(daily_routes)} daily routes")
            
            route_data = RouteData(
                device_id=data.get("device_id", device_id),
                start_date=start_date,
                end_date=end_date,
                total_coordinates=data.get("count", len(coordinates)),
                daily_routes=daily_routes,
                fuel_start=data.get("fuel", {}).get("start") if data.get("fuel") else None,
                fuel_end=data.get("fuel", {}).get("end") if data.get("fuel") else None
            )
            
            print(f"DEBUG GPS: Successfully created RouteData object")
            return route_data
            
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
    
    # Парсим строковые даты в datetime объекты
    try:
        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
    except ValueError as e:
        logger.error(f"Error parsing dates: start_date={start_date}, end_date={end_date}, error={e}")
        return []
    
    daily_routes = []
    
    # Определяем все дни в диапазоне поездки
    current_date = start_dt.date()
    end_date_only = end_dt.date()
    
    while current_date <= end_date_only:
        day_coordinates = []
        
        if current_date == start_dt.date() and current_date == end_date_only:
            # Поездка в один день - все координаты
            day_coordinates = coordinates
        elif current_date == start_dt.date():
            # Первый день - вычисляем долю дня от общего времени поездки
            total_duration = (end_dt - start_dt).total_seconds()
            if total_duration > 0:
                # Время до конца дня
                end_of_day = datetime.combine(current_date, datetime.max.time().replace(microsecond=0))
                first_day_duration = (end_of_day - start_dt).total_seconds()
                ratio = min(first_day_duration / total_duration, 1.0)
                split_index = max(1, int(len(coordinates) * ratio))
                day_coordinates = coordinates[:split_index]
            else:
                day_coordinates = coordinates
        elif current_date == end_date_only:
            # Последний день - оставшиеся координаты
            days_passed = (current_date - start_dt.date()).days
            total_days = (end_date_only - start_dt.date()).days + 1
            if total_days > 1:
                start_index = int(len(coordinates) * (days_passed / total_days))
                day_coordinates = coordinates[start_index:]
            else:
                day_coordinates = coordinates
        else:
            # Промежуточный день (полный день)
            days_passed = (current_date - start_dt.date()).days
            total_days = (end_date_only - start_dt.date()).days + 1
            start_index = int(len(coordinates) * (days_passed / total_days))
            end_index = int(len(coordinates) * ((days_passed + 1) / total_days))
            day_coordinates = coordinates[start_index:end_index]
        
        if day_coordinates:
            daily_routes.append(DailyRoute(
                date=current_date.strftime("%Y-%m-%d"),
                coordinates=day_coordinates
            ))
        
        current_date += timedelta(days=1)
    
    return daily_routes
