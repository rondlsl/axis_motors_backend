from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, and_, or_
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

from app.auth.dependencies.get_current_user import get_current_user
from app.dependencies.database.database import get_db
from app.models.user_model import User
from app.models.car_model import Car
from app.models.history_model import RentalHistory, RentalStatus, RentalType
from app.owner.schemas import (
    MyAutosResponse, CarOwnerResponse, TripsForMonthResponse,
    TripResponse, MonthEarnings, TripDetailResponse, TripPhotos,
    PhotoGroup, RouteMapData
)
from app.gps_api.utils.route_data import get_gps_route_data
import logging

from app.owner.utils import _clip_overlap_seconds
from app.rent.utils.calculate_price import get_open_price

# Настройка логгера
logger = logging.getLogger(__name__)

OwnerRouter = APIRouter(
    tags=["👤 Владелец авто (My Auto)"],
    prefix="/my-auto"
)

OFFSET_HOURS = 5


def apply_offset(dt: datetime) -> str | None:
    """Применяет смещение времени +5 часов для корректного отображения"""
    return (dt + timedelta(hours=OFFSET_HOURS)).isoformat() if dt else None


def calculate_owner_earnings(rental: RentalHistory) -> int:
    """
    Рассчитывает заработок владельца с поездки.
    Владелец получает всю сумму total_price, так как это доход с его автомобиля.
    """
    if rental.total_price:
        return rental.total_price
    return 0


@OwnerRouter.get(
    "/",
    response_model=MyAutosResponse,
    summary="Получить мои автомобили",
    description="Возвращает список автомобилей владельца с историей поездок",
    responses={
        200: {
            "description": "Список автомобилей владельца",
            "content": {
                "application/json": {
                    "example": {
                        "cars": [
                            {
                                "id": 1,
                                "name": "HAVAL F7x",
                                "plate_number": "422ABK02"
                            },
                            {
                                "id": 2,
                                "name": "MB CLA45s",
                                "plate_number": "666AZV02"
                            }
                        ]
                    }
                }
            }
        },
        401: {"description": "Не авторизован"},
        403: {"description": "Нет прав доступа"}
    }
)
def get_my_cars(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> MyAutosResponse:
    """
    Получить список автомобилей владельца с историей поездок.
    
    Показываются только автомобили, которые принадлежат текущему пользователю
    и имеют завершенные поездки. Для каждого автомобиля возвращается:
    - ID автомобиля
    - Название автомобиля  
    - Государственный номер
    
    **Требует аутентификации**: Bearer token
    """
    # Получаем автомобили пользователя, которые имеют завершенные поездки
    # Используем подзапрос чтобы избежать проблем с DISTINCT и JSON полями
    car_ids_with_history = (
        db.query(RentalHistory.car_id)
        .filter(
            RentalHistory.rental_status == RentalStatus.COMPLETED
        )
        .distinct()
        .subquery()
    )

    cars_with_history = (
        db.query(Car)
        .filter(
            Car.owner_id == current_user.id,
            Car.id.in_(db.query(car_ids_with_history.c.car_id))
        )
        .all()
    )

    cars_response = [
        CarOwnerResponse(
            id=car.id,
            name=car.name,
            plate_number=car.plate_number
        )
        for car in cars_with_history
    ]

    return MyAutosResponse(cars=cars_response)


@OwnerRouter.get(
    "/{vehicle_id}",
    response_model=TripsForMonthResponse,
    summary="Получить поездки по месяцам",
    description="Возвращает календарь поездок для конкретного автомобиля за указанный месяц"
)
def get_trips_by_month(
        vehicle_id: int,
        month: Optional[int] = Query(None, description="Месяц (1-12). Если не указан, возвращается текущий месяц"),
        year: Optional[int] = Query(None, description="Год. Если не указан, возвращается текущий год"),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> TripsForMonthResponse:
    """
    Получить поездки по конкретному автомобилю за определенный месяц.
    
    Для каждой поездки возвращается:
    - Продолжительность в минутах
    - Сумма заработка владельца
    - Используемый тариф (поминутный, почасовой, посуточный)
    - Время начала и окончания поездки
    
    Также возвращается:
    - Общий заработок за месяц
    - Список доступных месяцев с заработком
    - Информация об автомобиле
    
    **Требует аутентификации**: Bearer token
    **Права доступа**: Только владелец автомобиля
    """
    # Проверяем, что автомобиль принадлежит пользователю
    car = db.query(Car).filter(
        Car.id == vehicle_id,
        Car.owner_id == current_user.id
    ).first()

    if not car:
        raise HTTPException(
            status_code=404,
            detail="Автомобиль не найден или не принадлежит вам"
        )

    # Определяем месяц и год
    now = datetime.now()
    target_month = month if month is not None else now.month
    target_year = year if year is not None else now.year

    if not (1 <= target_month <= 12):
        raise HTTPException(status_code=400, detail="Месяц должен быть от 1 до 12")

    # Получаем поездки за указанный месяц
    trips = (
        db.query(RentalHistory)
        .filter(
            RentalHistory.car_id == vehicle_id,
            RentalHistory.rental_status == RentalStatus.COMPLETED,
            extract('year', RentalHistory.end_time) == target_year,
            extract('month', RentalHistory.end_time) == target_month
        )
        .order_by(RentalHistory.end_time.desc())
        .all()
    )

    # Формируем ответ для поездок
    trips_response = []
    month_total_earnings = 0

    for trip in trips:
        duration_minutes = 0
        if trip.start_time and trip.end_time:
            duration_seconds = (trip.end_time - trip.start_time).total_seconds()
            duration_minutes = int(duration_seconds / 60)

        earnings = calculate_owner_earnings(trip)
        month_total_earnings += earnings

        trips_response.append(TripResponse(
            id=trip.id,
            duration_minutes=duration_minutes,
            earnings=earnings,
            rental_type=trip.rental_type.value,
            start_time=apply_offset(trip.start_time),
            end_time=apply_offset(trip.end_time)
        ))

    # Получаем все доступные месяцы с заработком
    available_months_query = (
        db.query(
            extract('year', RentalHistory.end_time).label('year'),
            extract('month', RentalHistory.end_time).label('month'),
            func.sum(RentalHistory.total_price).label('total_earnings'),
            func.count(RentalHistory.id).label('trip_count')
        )
        .filter(
            RentalHistory.car_id == vehicle_id,
            RentalHistory.rental_status == RentalStatus.COMPLETED,
            RentalHistory.total_price.isnot(None)
        )
        .group_by(
            extract('year', RentalHistory.end_time),
            extract('month', RentalHistory.end_time)
        )
        .order_by(
            extract('year', RentalHistory.end_time).desc(),
            extract('month', RentalHistory.end_time).desc()
        )
        .all()
    )

    available_months = [
        MonthEarnings(
            year=int(row.year),
            month=int(row.month),
            total_earnings=int(row.total_earnings or 0),
            trip_count=int(row.trip_count)
        )
        for row in available_months_query
    ]

    # Заработок за текущий месяц
    current_month_earnings = MonthEarnings(
        year=target_year,
        month=target_month,
        total_earnings=month_total_earnings,
        trip_count=len(trips)
    )

    return TripsForMonthResponse(
        vehicle_id=vehicle_id,
        vehicle_name=car.name,
        vehicle_plate_number=car.plate_number,
        month_earnings=current_month_earnings,
        trips=trips_response,
        available_months=available_months
    )


@OwnerRouter.get(
    "/{vehicle_id}/{trip_id}",
    response_model=TripDetailResponse,
    summary="Детальная информация о поездке",
    description="Возвращает подробную информацию о конкретной поездке с фотографиями и маршрутом"
)
async def get_trip_details(
        vehicle_id: int,
        trip_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> TripDetailResponse:
    """
    Получить детальную информацию о конкретной поездке.
    
    Возвращает:
    - Информацию о времени и заработке
    - Фотографии, разделённые на три группы:
      1. Фото от клиента **до поездки**
      2. Фото от клиента **после поездки**  
      3. Фото от механика **после осмотра**
    - Данные маршрута для отображения карты
    - Информацию о том, длилась ли поездка более 24 часов
    
    Если поездка длилась более 24 часов, отображается календарь с картой маршрута.
    Если менее 24 часов - одна карта с маршрутом.
    
    **Требует аутентификации**: Bearer token
    **Права доступа**: Только владелец автомобиля
    """
    # Проверяем, что автомобиль принадлежит пользователю
    car = db.query(Car).filter(
        Car.id == vehicle_id,
        Car.owner_id == current_user.id
    ).first()

    if not car:
        raise HTTPException(
            status_code=404,
            detail="Автомобиль не найден или не принадлежит вам"
        )

    # Получаем поездку
    trip = db.query(RentalHistory).filter(
        RentalHistory.id == trip_id,
        RentalHistory.car_id == vehicle_id,
        RentalHistory.rental_status == RentalStatus.COMPLETED
    ).first()

    if not trip:
        raise HTTPException(
            status_code=404,
            detail="Поездка не найдена"
        )

    # Рассчитываем продолжительность
    duration_minutes = 0
    if trip.start_time and trip.end_time:
        duration_seconds = (trip.end_time - trip.start_time).total_seconds()
        duration_minutes = int(duration_seconds / 60)

    # Заработок
    earnings = calculate_owner_earnings(trip)

    # Фотографии
    photos = TripPhotos(
        client_before=PhotoGroup(photos=trip.photos_before or []),
        client_after=PhotoGroup(photos=trip.photos_after or []),
        mechanic_after=PhotoGroup(photos=trip.delivery_photos_after or [])
    )

    # Маршрут с GPS данными
    duration_over_24h = duration_minutes > (24 * 60)

    # Получаем GPS данные маршрута если есть gps_id
    route_data = None

    if car.gps_id and trip.start_time and trip.end_time:
        try:
            route_data = await get_gps_route_data(
                device_id=car.gps_id,
                start_date=apply_offset(trip.start_time),
                end_date=apply_offset(trip.end_time)
            )
            if route_data:
                print(f"DEBUG: GPS coordinates count: {route_data.total_coordinates}")
            else:
                print("DEBUG: GPS data is None")
        except Exception as e:
            print(f"DEBUG: Exception in GPS fetch: {e}")
            import traceback
            print(f"DEBUG: Full traceback: {traceback.format_exc()}")
    else:
        print(
            f"DEBUG: Skipping GPS fetch - gps_id: {car.gps_id}, start_time: {trip.start_time}, end_time: {trip.end_time}")

    route_map = RouteMapData(
        start_latitude=trip.start_latitude,
        start_longitude=trip.start_longitude,
        end_latitude=trip.end_latitude,
        end_longitude=trip.end_longitude,
        duration_over_24h=duration_over_24h,
        route_data=route_data
    )

    return TripDetailResponse(
        id=trip.id,
        vehicle_id=vehicle_id,
        vehicle_name=car.name,
        vehicle_plate_number=car.plate_number,
        duration_minutes=duration_minutes,
        earnings=earnings,
        rental_type=trip.rental_type.value,
        start_time=apply_offset(trip.start_time),
        end_time=apply_offset(trip.end_time),
        photos=photos,
        route_map=route_map
    )


@OwnerRouter.get("/cars-with-not-owner-timer")
async def get_owner_cars_with_not_owner_timer(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """
    Возвращает по каждой машине владельца:
    - полные данные машины
    - timer: минуты/секунды/total_seconds — сколько времени с начала месяца машина НЕ была арендована самим владельцем
      (т.е. всё время месяца минус все интервалы любых его собственных аренд по этой машине,
       включая RESERVED/DELIVERY_RESERVED/DELIVERING/IN_USE и т.д., кроме CANCELLED).
    - period: отрезок расчёта [month_start, now]
    """

    # Берём «сейчас» в UTC (чтобы не зависеть от TZ); главное — последовательно использовать одно и то же.
    now = datetime.now(timezone.utc)

    # Начало текущего месяца (UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Все машины пользователя
    cars: List[Car] = (
        db.query(Car)
        .filter(Car.owner_id == current_user.id)
        .all()
    )

    if not cars:
        return []

    car_ids = [c.id for c in cars]

    # Все аренды ТОЛЬКО владельца по этим машинам, которые хоть как-то пересекают окно месяца.
    # Логика пересечения:
    # - reservation_time < window_end (иначе арендный интервал начинается после окна)
    # - и (end_time IS NULL ИЛИ end_time > window_start) — значит, арендный интервал задел окно
    # Исключаем CANCELLED (отменённые не считаем временем «арендована владельцем»).
    owner_rentals: List[RentalHistory] = (
        db.query(RentalHistory)
        .filter(
            RentalHistory.car_id.in_(car_ids),
            RentalHistory.user_id == current_user.id,
            RentalHistory.rental_status != RentalStatus.CANCELLED,
            RentalHistory.reservation_time < now,
            or_(RentalHistory.end_time == None, RentalHistory.end_time > month_start),
        )
        .all()
    )

    # Группируем аренды по машине
    rentals_by_car: Dict[int, List[RentalHistory]] = {}
    for r in owner_rentals:
        rentals_by_car.setdefault(r.car_id, []).append(r)

    total_window_seconds = int((now - month_start).total_seconds())

    result: List[Dict[str, Any]] = []

    for car in cars:
        # Суммируем все интервалы, когда МАШИНУ арендовал сам владелец
        # Отрезок аренды владельца берём от reservation_time (гарантированно не null)
        # до end_time (или now, если аренда ещё идёт/в зарезервированном/доставочном статусе).
        owner_used_seconds = 0

        for r in rentals_by_car.get(car.id, []):
            # старт — с момента резервирования (или старта, если хотите — тогда замените на r.start_time or r.reservation_time)
            start_ts = r.start_time or r.reservation_time  # если хотите «жёстче» — берите ровно reservation_time
            end_ts = r.end_time or None  # None => до now

            # Пересечение с окном месяца
            owner_used_seconds += _clip_overlap_seconds(start_ts, end_ts, month_start, now)

        not_owner_seconds = max(0, total_window_seconds - owner_used_seconds)

        minutes = not_owner_seconds // 60
        seconds = not_owner_seconds % 60

        car_payload = {
            "id": car.id,
            "name": car.name,
            "plate_number": car.plate_number,
            "fuel_level": car.fuel_level,
            "latitude": car.latitude,
            "longitude": car.longitude,
            "course": car.course,
            "engine_volume": car.engine_volume,
            "drive_type": car.drive_type,
            "year": car.year,
            "photos": car.photos,
            "status": car.status,
            "price_per_minute": car.price_per_minute,
            "price_per_hour": car.price_per_hour,
            "price_per_day": car.price_per_day,
            "open_price": get_open_price(car),
            "owned_car": True,
            "description": car.description,
        }

        result.append({
            "car": car_payload,
            "timer": {
                "minutes": minutes,
                "seconds": seconds,
                "total_seconds": not_owner_seconds
            },
            "period": {
                "from": month_start.isoformat(),
                "to": now.isoformat()
            }
        })

    return result
