import httpx
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from app.owner.schemas import RouteData, DailyRoute, GPSCoordinate

# Настройка логгера
logger = logging.getLogger(__name__)


async def get_gps_route_data(
    device_id: str, 
    start_date: datetime, 
    end_date: datetime
) -> Optional[RouteData]:
    """
    Получает данные маршрута от внешнего GPS API.
    
    :param device_id: ID GPS устройства (gps_id из таблицы cars)
    :param start_date: Дата и время начала поездки
    :param end_date: Дата и время окончания поездки
    :return: Данные маршрута или None при ошибке
    """
    print(f"DEBUG GPS: Function called with device_id={device_id}, start_date={start_date}, end_date={end_date}")
    try:
        
        url = f"http://195.49.210.50:8666/vehicles/{device_id}/gps?start_date={start_date}&end_date={end_date}"
        headers = {"accept": "application/json"}
        
        print(f"DEBUG GPS: Making request to {url}")
        print(f"DEBUG GPS: Params: {params}")
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
                start_date=start_str,
                end_date=end_str,
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
    start_date: datetime, 
    end_date: datetime
) -> List[DailyRoute]:
    """
    Группирует координаты по дням.
    
    :param coordinates: Список всех координат
    :param start_date: Дата начала поездки
    :param end_date: Дата окончания поездки
    :return: Список маршрутов по дням
    """
    daily_routes = []
    
    # Определяем все дни в диапазоне поездки
    current_date = start_date.date()
    end_date_only = end_date.date()
    
    while current_date <= end_date_only:
        # Фильтруем координаты для текущего дня
        # Поскольку timestamp в данных относительный, используем индексы
        # для примерного разделения по дням
        
        day_coordinates = []
        
        if current_date == start_date.date() and current_date == end_date_only:
            # Одна день - все координаты
            day_coordinates = coordinates
        elif current_date == start_date.date():
            # Первый день - примерно первая половина координат
            total_duration = (end_date - start_date).total_seconds()
            end_of_day = datetime.combine(current_date, datetime.max.time())
            first_day_duration = (end_of_day - start_date).total_seconds()
            ratio = first_day_duration / total_duration
            split_index = int(len(coordinates) * ratio)
            day_coordinates = coordinates[:split_index]
        elif current_date == end_date_only:
            # Последний день - оставшиеся координаты
            days_passed = (current_date - start_date.date()).days
            total_days = (end_date_only - start_date.date()).days + 1
            start_index = int(len(coordinates) * (days_passed / total_days))
            day_coordinates = coordinates[start_index:]
        else:
            # Промежуточный день
            days_passed = (current_date - start_date.date()).days
            total_days = (end_date_only - start_date.date()).days + 1
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
