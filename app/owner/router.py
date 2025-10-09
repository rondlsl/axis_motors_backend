from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, and_, or_
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
import math

from app.auth.dependencies.get_current_user import get_current_user
from app.dependencies.database.database import get_db
from app.models.user_model import User, UserRole
from app.models.car_model import Car, CarStatus
from app.models.history_model import RentalHistory, RentalStatus, RentalType, RentalReview
from app.owner.schemas import (
    MyAutosResponse, CarOwnerResponse, TripsForMonthResponse,
    TripResponse, MonthEarnings, TripDetailResponse, TripPhotos,
    PhotoGroup, RouteMapData
)
from app.gps_api.utils.route_data import get_gps_route_data
import logging

from app.owner.utils import _clip_overlap_seconds, calculate_total_unavailable_seconds, calculate_month_availability_minutes, ALMATY_TZ
from app.rent.utils.calculate_price import get_open_price

# Настройка логгера
logger = logging.getLogger(__name__)

OwnerRouter = APIRouter(
    tags=["👤 Владелец авто (My Auto)"],
    prefix="/my-auto"
)

OFFSET_HOURS = 5
FUEL_PRICE_PER_LITER = 450
ELECTRIC_FUEL_PRICE_PER_LITER = 200


def apply_offset(dt: datetime) -> str | None:
    """Применяет смещение времени +5 часов для корректного отображения"""
    return (dt + timedelta(hours=OFFSET_HOURS)).isoformat() if dt else None


def calculate_fuel_cost(rental: RentalHistory, car: Car, current_user: User) -> int:
    """
    Рассчитывает стоимость топлива для поездки.
    Если поездка была совершена владельцем, то полная стоимость топлива списывается с его баланса.
    Округление в пользу платформы: fuel_before округляем вверх, fuel_after округляем вниз.
    """
    if rental.fuel_before is None or rental.fuel_after is None:
        return 0
    
    # Округляем в пользу платформы:
    # fuel_before округляем вверх (больше топлива в начале)
    # fuel_after округляем вниз (меньше топлива в конце)
    fuel_before_rounded = math.ceil(rental.fuel_before) if rental.fuel_before else 0
    fuel_after_rounded = math.floor(rental.fuel_after) if rental.fuel_after else 0
    
    fuel_consumed = fuel_before_rounded - fuel_after_rounded
    if fuel_consumed <= 0:
        return 0
    
    # Если поездка была совершена владельцем
    if rental.user_id == car.owner_id:
        # Определяем цену за литр в зависимости от типа автомобиля
        if car.body_type == "ELECTRIC":
            price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
        else:
            price_per_liter = FUEL_PRICE_PER_LITER
        
        # Владелец платит полную стоимость топлива
        fuel_cost = int(fuel_consumed * price_per_liter)
        return fuel_cost
    
    # Для обычных клиентов топливо уже включено в общую стоимость
    return 0


def calculate_owner_earnings(rental: RentalHistory, car: Car, current_user: User) -> int:
    """
    Рассчитывает заработок владельца с поездки.
    Если поездка была совершена владельцем, то заработок = 0 (владелец не зарабатывает на своих поездках).
    Для поездок клиентов владелец получает 50% только от базовых услуг (без доставки, открытия дверей и бензина).
    """
    # Если поездка была совершена владельцем, заработок = 0
    if rental.user_id == car.owner_id:
        return 0
    
    # Владелец получает 50% только от базовых услуг (без delivery_fee, open_fee, fuel_fee)
    base_earnings = (rental.base_price or 0) + (rental.overtime_fee or 0) + (rental.waiting_fee or 0) + (rental.distance_fee or 0)
    
    # Исключаем доходы от сервисов платформы:
    # - delivery_fee - сервис доставки платформы
    # - open_fee - сервис открытия дверей платформы  
    # - fuel_fee - расходы на топливо клиента
    
    return int(base_earnings * 0.5)


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

    # Получаем текущий месяц и год
    now = datetime.now(ALMATY_TZ)
    current_month = now.month
    current_year = now.year
    
    cars_response = []
    for car in cars_with_history:
        # Рассчитываем доступные минуты для текущего месяца
        available_minutes = calculate_month_availability_minutes(
            car_id=car.id,
            year=current_year,
            month=current_month,
            owner_id=current_user.id,
            db=db
        )
        
        cars_response.append(CarOwnerResponse(
            id=car.id,
            name=car.name,
            plate_number=car.plate_number,
            available_minutes=available_minutes
        ))

    return MyAutosResponse(cars=cars_response)


@OwnerRouter.get("/cars-with-availability-timer")
async def get_owner_cars_with_availability_timer(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """
    Возвращает по каждой машине владельца:
    - полные данные машины
    - timer: минуты/секунды/total_seconds — сколько времени с начала месяца машина была доступна для аренды клиентами
      (т.е. всё время месяца минус все интервалы, когда машина была недоступна:
       - аренды владельцем (все статусы кроме CANCELLED)
       - аренды клиентами (RESERVED/IN_USE/DELIVERING/DELIVERY_RESERVED/DELIVERING_IN_PROGRESS)
       - доставки клиентам).
    - period: отрезок расчёта [month_start, now]
    """
    
    # Берём «сейчас» в алматинском времени
    now = datetime.now(ALMATY_TZ)

    # Начало текущего месяца (алматинское время)
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

    # Все аренды по машинам владельца, которые хоть как-то пересекают окно месяца.
    # Включаем как аренды владельца, так и аренды клиентов.
    # Логика пересечения:
    # - reservation_time < window_end (иначе арендный интервал начинается после окна)
    # - и (end_time IS NULL ИЛИ end_time > window_start) — значит, арендный интервал задел окно
    # Исключаем CANCELLED (отменённые не делают машину недоступной).
    all_rentals: List[RentalHistory] = (
        db.query(RentalHistory)
        .filter(
            RentalHistory.car_id.in_(car_ids),
            RentalHistory.rental_status != RentalStatus.CANCELLED,
            RentalHistory.reservation_time < now,
            or_(RentalHistory.end_time == None, RentalHistory.end_time > month_start),
        )
        .all()
    )
    
    # Аренды найдены

    # Группируем аренды по машине
    rentals_by_car: Dict[int, List[RentalHistory]] = {}
    for r in all_rentals:
        rentals_by_car.setdefault(r.car_id, []).append(r)

    total_window_seconds = int((now - month_start).total_seconds())

    result: List[Dict[str, Any]] = []

    for car in cars:
        # Собираем все интервалы недоступности для данной машины
        unavailable_intervals = []
        
        for r in rentals_by_car.get(car.id, []):
            # Период недоступности начинается с момента резервирования
            start_ts = r.reservation_time
            # Период недоступности заканчивается в end_time или продолжается до now
            end_ts = r.end_time  # None означает, что аренда еще активна
            
            unavailable_intervals.append((start_ts, end_ts))

        # Вычисляем общее время недоступности с учетом перекрывающихся интервалов
        unavailable_seconds = calculate_total_unavailable_seconds(
            unavailable_intervals, month_start, now
        )

        # Время доступности = общее время месяца - время недоступности
        available_seconds = max(0, total_window_seconds - unavailable_seconds)

        minutes = available_seconds // 60
        seconds = available_seconds % 60

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
            "transmission_type": car.transmission_type,
            "body_type": car.body_type,
            "auto_class": car.auto_class,
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

        # Дополнительная статистика
        availability_percentage = (available_seconds / total_window_seconds * 100) if total_window_seconds > 0 else 0
        
        # Подсчитываем количество аренд владельца и клиентов
        owner_rentals_count = sum(1 for r in rentals_by_car.get(car.id, []) if r.user_id == current_user.id)
        client_rentals_count = sum(1 for r in rentals_by_car.get(car.id, []) if r.user_id != current_user.id)

        result.append({
            "car": car_payload,
            "timer": {
                "minutes": minutes,
                "seconds": seconds,
                "total_seconds": available_seconds
            },
            "statistics": {
                "availability_percentage": round(availability_percentage, 2),
                "total_rentals": len(rentals_by_car.get(car.id, [])),
                "owner_rentals": owner_rentals_count,
                "client_rentals": client_rentals_count,
                "unavailable_seconds": unavailable_seconds
            },
            "period": {
                "from": month_start.isoformat(),
                "to": now.isoformat()
            }
        })

    return result


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
    try:
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

        # Получаем поездки за указанный месяц, исключая поездки механиков
        trips = (
            db.query(RentalHistory)
            .join(User, RentalHistory.user_id == User.id)
            .filter(
                RentalHistory.car_id == vehicle_id,
                RentalHistory.rental_status == RentalStatus.COMPLETED,
                extract('year', RentalHistory.end_time) == target_year,
                extract('month', RentalHistory.end_time) == target_month,
                User.role != UserRole.MECHANIC  # Исключаем поездки механиков
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

            fuel_cost = calculate_fuel_cost(trip, car, current_user)
            earnings = calculate_owner_earnings(trip, car, current_user)
            
            # Если есть fuel_cost (поездка владельца), то из заработка вычитаем стоимость топлива
            if fuel_cost > 0:
                earnings = earnings - fuel_cost
            
            month_total_earnings += earnings

            # Создаем базовый словарь для TripResponse
            trip_data = {
                "id": trip.id,
                "duration_minutes": duration_minutes,
                "earnings": earnings,
                "rental_type": trip.rental_type.value,
                "start_time": apply_offset(trip.start_time),
                "end_time": apply_offset(trip.end_time),
                "user_id": trip.user_id
            }
            
            # Добавляем fuel_cost только если это поездка владельца
            if trip.user_id == car.owner_id:
                trip_data["fuel_cost"] = fuel_cost
            
            trips_response.append(TripResponse(**trip_data))

        # Получаем все доступные месяцы с заработком, исключая поездки механиков
        available_months_query = (
            db.query(
                extract('year', RentalHistory.end_time).label('year'),
                extract('month', RentalHistory.end_time).label('month'),
                func.sum(RentalHistory.total_price).label('total_earnings'),
                func.count(RentalHistory.id).label('trip_count')
            )
            .join(User, RentalHistory.user_id == User.id)
            .filter(
                RentalHistory.car_id == vehicle_id,
                RentalHistory.rental_status == RentalStatus.COMPLETED,
                RentalHistory.total_price.isnot(None),
                User.role != UserRole.MECHANIC  # Исключаем поездки механиков
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

        available_months = []
        for i, row in enumerate(available_months_query):
            # Рассчитываем доступные минуты для каждого месяца
            available_minutes = calculate_month_availability_minutes(
                car_id=vehicle_id,
                year=int(row.year),
                month=int(row.month),
                owner_id=current_user.id,
                db=db
            )
            
            # Рассчитываем корректный заработок с учетом топлива для этого месяца
            month_trips = (
                db.query(RentalHistory)
                .join(User, RentalHistory.user_id == User.id)
                .filter(
                    RentalHistory.car_id == vehicle_id,
                    RentalHistory.rental_status == RentalStatus.COMPLETED,
                    extract('year', RentalHistory.end_time) == int(row.year),
                    extract('month', RentalHistory.end_time) == int(row.month),
                    User.role != UserRole.MECHANIC
                )
                .all()
            )
            
            # Пересчитываем заработок с учетом топлива
            corrected_total_earnings = 0
            for trip in month_trips:
                corrected_total_earnings += calculate_owner_earnings(trip, car, current_user)
            
            # Создаем объект MonthEarnings
            month_earnings = MonthEarnings(
                year=int(row.year),
                month=int(row.month),
                total_earnings=corrected_total_earnings,
                trip_count=int(row.trip_count),
                available_minutes=available_minutes
            )
            available_months.append(month_earnings)
        
        # Заработок за текущий месяц и расчет доступных минут
        current_month_available_minutes = calculate_month_availability_minutes(
            car_id=vehicle_id,
            year=target_year,
            month=target_month,
            owner_id=current_user.id,
            db=db
        )
        # Создаем текущий MonthEarnings объект
        current_month_earnings = MonthEarnings(
            year=target_year,
            month=target_month,
            total_earnings=month_total_earnings,
            trip_count=len(trips),
            available_minutes=current_month_available_minutes
        )
        
        # Создание финального ответа
        
        response = TripsForMonthResponse(
            vehicle_id=vehicle_id,
            vehicle_name=car.name,
            vehicle_plate_number=car.plate_number,
            month_earnings=current_month_earnings,
            trips=trips_response,
            available_months=available_months
        )
        return response
        
    except Exception as e:
        import traceback
        logger.error(f"Ошибка в get_trips_by_month: {e}")
        logger.error(f"Полный трейс: {traceback.format_exc()}")
        raise


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

    # Получаем завершённую поездку 
    trip = db.query(RentalHistory).join(Car, RentalHistory.car_id == Car.id).filter(
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

    # Рассчитываем стоимость топлива и заработок
    fuel_cost = calculate_fuel_cost(trip, car, current_user)
    earnings = calculate_owner_earnings(trip, car, current_user)
    
    # Если есть fuel_cost (поездка владельца), то из заработка вычитаем стоимость топлива
    if fuel_cost > 0:
        earnings = earnings - fuel_cost

    # Фотографии (исключаем селфи клиента)
    client_before_photos = []
    if trip.photos_before:
        client_before_photos = [photo for photo in trip.photos_before if "/selfie/" not in photo and "\\selfie\\" not in photo]
    
    client_after_photos = []
    if trip.photos_after:
        client_after_photos = [photo for photo in trip.photos_after if "/selfie/" not in photo and "\\selfie\\" not in photo]
    
    photos = TripPhotos(
        client_before=PhotoGroup(photos=client_before_photos),
        client_after=PhotoGroup(photos=client_after_photos)
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
            if not route_data:
                route_data = None
        except Exception as e:
            logger.error(f"GPS fetch error: {e}")
            route_data = None
    else:
        # GPS данные недоступны
        route_data = None

    route_map = RouteMapData(
        start_latitude=trip.start_latitude,
        start_longitude=trip.start_longitude,
        end_latitude=trip.end_latitude,
        end_longitude=trip.end_longitude,
        duration_over_24h=duration_over_24h,
        route_data=route_data
    )

    # Получаем отзыв для этой аренды
    review = db.query(RentalReview).filter(RentalReview.rental_id == trip.id).first()
    
    # Информация о доставке механика
    mechanic_delivery = None
    if trip.delivery_mechanic_id:
        # Получаем информацию о механике доставки
        delivery_mechanic = db.query(User).filter(User.id == trip.delivery_mechanic_id).first()
        delivery_mechanic_info = None
        if delivery_mechanic:
            delivery_mechanic_info = {
                "id": delivery_mechanic.id,
                "first_name": delivery_mechanic.first_name or "",
                "last_name": delivery_mechanic.last_name or "",
                "phone_number": delivery_mechanic.phone_number or ""
            }
        
        mechanic_delivery = {
            "mechanic": delivery_mechanic_info,
            "start_time": apply_offset(trip.delivery_start_time),
            "end_time": apply_offset(trip.delivery_end_time),
            "photos_before": trip.delivery_photos_before or [],
            "photos_after": trip.delivery_photos_after or [],
            # Отзыв механика доставки
            "delivery_rating": review.delivery_mechanic_rating if review else None,
            "delivery_comment": review.delivery_mechanic_comment if review else None
        }
    
    # Информация об осмотре механика
    mechanic_inspection = None
    if trip.mechanic_inspector_id:
        # Получаем информацию о механике-инспекторе
        mechanic = db.query(User).filter(User.id == trip.mechanic_inspector_id).first()
        mechanic_info = None
        if mechanic:
            mechanic_info = {
                "id": mechanic.id,
                "first_name": mechanic.first_name or "",
                "last_name": mechanic.last_name or "",
                "phone_number": mechanic.phone_number or ""
            }
        
        mechanic_inspection = {
            "mechanic": mechanic_info,
            "start_time": apply_offset(trip.mechanic_inspection_start_time),
            "end_time": apply_offset(trip.mechanic_inspection_end_time),
            "status": trip.mechanic_inspection_status,
            "comment": trip.mechanic_inspection_comment,
            "photos_before": trip.mechanic_photos_before or [],
            "photos_after": trip.mechanic_photos_after or [],
            # Отзывы
            "client_rating": review.rating if review else None,
            "client_comment": review.comment if review else None,
            "mechanic_rating": review.mechanic_rating if review else None,
            "mechanic_comment": review.mechanic_comment if review else None
        }

    # Создаем базовый словарь для TripDetailResponse
    trip_detail_data = {
        "id": trip.id,
        "vehicle_id": vehicle_id,
        "vehicle_name": car.name,
        "vehicle_plate_number": car.plate_number,
        "duration_minutes": duration_minutes,
        "earnings": earnings,
        "rental_type": trip.rental_type.value,
        "start_time": apply_offset(trip.start_time),
        "end_time": apply_offset(trip.end_time),
        "photos": photos,
        "route_map": route_map,
        "mechanic_delivery": mechanic_delivery,
        "mechanic_inspection": mechanic_inspection
    }
    
    # Добавляем fuel_cost только если это поездка владельца
    if trip.user_id == car.owner_id:
        trip_detail_data["fuel_cost"] = fuel_cost
    
    return TripDetailResponse(**trip_detail_data)

