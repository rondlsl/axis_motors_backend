import httpx
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from app.owner.schemas import RouteData, DailyRoute, GPSCoordinate


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
    try:
        # Форматируем даты в нужный формат для API
        start_str = start_date.strftime("%Y-%m-%dT%H:%M:%S")
        end_str = end_date.strftime("%Y-%m-%dT%H:%M:%S")
        
        url = f"http://195.49.210.50:8666/vehicles/{device_id}/gps"
        params = {
            "start_date": start_str,
            "end_date": end_str
        }
        headers = {"accept": "application/json"}
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            
            if not data or "coordinates" not in data:
                return None
                
            # Преобразуем координаты в наши модели
            coordinates = [
                GPSCoordinate(
                    lat=coord["lat"],
                    lon=coord["lon"], 
                    altitude=coord["altitude"],
                    timestamp=coord["timestamp"]
                )
                for coord in data["coordinates"]
            ]
            
            # Группируем координаты по дням
            daily_routes = _group_coordinates_by_day(coordinates, start_date, end_date)
            
            return RouteData(
                device_id=data.get("device_id", device_id),
                start_date=start_str,
                end_date=end_str,
                total_coordinates=data.get("count", len(coordinates)),
                daily_routes=daily_routes,
                fuel_start=data.get("fuel", {}).get("start"),
                fuel_end=data.get("fuel", {}).get("end")
            )
            
    except Exception as e:
        print(f"Ошибка получения GPS данных для {device_id}: {e}")
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
