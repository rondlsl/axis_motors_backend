from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import or_, and_, func
from sqlalchemy.orm import Session, joinedload
from typing import Dict, Any, List, Optional
import asyncio
import logging
import random

from starlette import status

logger = logging.getLogger(__name__)

from app.core.config import GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD, RENTED_CARS_ENDPOINT_KEY, POLYGON_COORDS
from app.dependencies.database.database import get_db, SessionLocal
from app.auth.dependencies.get_current_user import get_current_user
from app.utils.short_id import uuid_to_sid, safe_sid_to_uuid
from app.gps_api.schemas import RentedCar
from app.models.car_model import Car, CarAutoClass, CarStatus
from app.models.history_model import RentalHistory, RentalStatus
from app.models.rental_actions_model import ActionType, ActionStatus, RentalAction
from app.models.user_model import User, UserRole
from app.rent.utils.user_utils import get_user_available_auto_classes
from app.models.application_model import Application, ApplicationStatus
from app.gps_api.utils.auth_api import get_auth_token
from app.gps_api.utils.get_active_rental import get_active_rental_car, get_active_rental, get_active_rental_by_car_id
from app.gps_api.utils.car_data import send_command_to_terminal, send_open, send_close, send_give_key, send_take_key, send_lock_engine, send_unlock_engine
from app.rent.utils.calculate_price import get_open_price
from app.gps_api.schemas_telemetry import VehicleTelemetryResponse
from app.gps_api.utils.glonassoft_client import glonassoft_client
from app.gps_api.utils.telemetry_processor import process_glonassoft_data
from app.utils.telegram_logger import log_error_to_telegram
from app.admin.cars.utils import sort_car_photos
from app.gps_api.utils.point_in_polygon import is_point_inside_polygon
from app.push.utils import send_localized_notification_to_user, send_localized_notification_to_user_async, user_has_push_tokens, get_user_push_tokens
from pydantic import BaseModel
from app.models.guarantor_model import Guarantor, GuarantorRequest, GuarantorRequestStatus
from app.utils.action_logger import log_action

# Временно закомментировано: генерация FCM токенов
# from app.utils.fcm_token import ensure_user_has_unique_fcm_token

Vehicle_Router = APIRouter(prefix="/vehicles", tags=["Vehicles"])

AUTH_TOKEN = ""
BASE_URL = "https://regions.glonasssoft.ru"
started = False


def validate_user_can_control_car(current_user: User, db: Session) -> None:
    """
    Валидация прав пользователя на управление автомобилем.
    Проверяет роль и статус заявки пользователя.
    """
    # Админы и механики могут управлять автомобилями
    if current_user.role in [UserRole.ADMIN, UserRole.MECHANIC]:
        return
    
    # Блокированные пользователи не могут управлять
    if current_user.role in [UserRole.REJECTSECOND]:
        raise HTTPException(
            status_code=403, 
            detail="Доступ к управлению автомобилем заблокирован"
        )
    
    # Пользователи без документов не могут управлять
    if current_user.role == UserRole.CLIENT:
        raise HTTPException(
            status_code=403, 
            detail="Для управления автомобилем необходимо загрузить документы"
        )
    
    # Пользователи с неправильными документами не могут управлять
    if current_user.role == UserRole.REJECTFIRSTDOC:
        raise HTTPException(
            status_code=403, 
            detail="Необходимо загрузить документы заново"
        )
    
    # Пользователи без сертификатов не могут управлять
    if current_user.role == UserRole.REJECTFIRSTCERT:
        raise HTTPException(
            status_code=403, 
            detail="Необходимо прикрепить недостающие сертификаты"
        )
    
    # Пользователи с финансовыми проблемами не могут управлять
    if current_user.role == UserRole.REJECTFIRST:        
        active_guarantor = db.query(Guarantor).join(
            GuarantorRequest, Guarantor.request_id == GuarantorRequest.id
        ).options(
            joinedload(Guarantor.guarantor_user)
        ).filter(
            Guarantor.client_id == current_user.id,
            Guarantor.is_active == True,
            GuarantorRequest.status == GuarantorRequestStatus.ACCEPTED
        ).first()
        
        if not active_guarantor or not active_guarantor.guarantor_user or not active_guarantor.guarantor_user.auto_class:
            raise HTTPException(
                status_code=403, 
                detail="Управление недоступно по финансовым причинам"
            )
            
    # Пользователи в процессе верификации не могут управлять
    if current_user.role in [UserRole.PENDINGTOFIRST, UserRole.PENDINGTOSECOND]:
        raise HTTPException(
            status_code=403, 
            detail="Ваша заявка на рассмотрении"
        )
    
    # Для роли USER проверяем полную верификацию
    if current_user.role == UserRole.USER:
        if not bool(current_user.documents_verified):
            raise HTTPException(
                status_code=403, 
                detail="Для управления автомобилем необходимо пройти верификацию"
            )
        
        # Проверяем одобрение финансиста и МВД
        application = (
            db.query(Application)
            .filter(Application.user_id == current_user.id)
            .first()
        )
        if not application or application.financier_status != ApplicationStatus.APPROVED or application.mvd_status != ApplicationStatus.APPROVED:
            raise HTTPException(
                status_code=403, 
                detail="Для управления автомобилем требуется одобрение заявки"
            )


@Vehicle_Router.on_event("startup")
async def start_token_refresh():
    global started
    if not started:
        started = True

        async def refresh_token():
            global AUTH_TOKEN
            while True:
                try:
                    AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
                except Exception as e:
                    print("Ошибка обновления токена: {e}")
                await asyncio.sleep(1800)

        asyncio.create_task(refresh_token())


@Vehicle_Router.get("/get_vehicles")
async def get_vehicle_info(
        user_latitude: float = Query(None, description="Широта пользователя"),
        user_longitude: float = Query(None, description="Долгота пользователя"),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    try:
        # Временно закомментировано: генерация FCM токенов
        # # Проверяем и генерируем FCM токен, если необходимо
        # try:
        #     token_updated = ensure_user_has_unique_fcm_token(db, current_user)
        #     if token_updated:
        #         db.commit()
        #         db.refresh(current_user)
        # except Exception as e:
        #     logger.error(f"Ошибка при генерации FCM токена в get_vehicle: {e}")
        #     # Продолжаем выполнение даже если не удалось сгенерировать токен
        #     db.rollback()
        
        # Специальная обработка для номера 77017347719
        special_user_phone = "77017347719"
        is_special_user = current_user.phone_number == special_user_phone
        
        if current_user.role == UserRole.MECHANIC:
            query = db.query(Car)
            if current_user.phone_number not in ["71011111111", "71234567890", "77057726400", "71234567876", "77766639210", special_user_phone]:
                query = query.filter(Car.plate_number.notin_(["666AZV02"]))
        else:
            active_rental = db.query(RentalHistory).filter(
                RentalHistory.user_id == current_user.id,
                RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
            ).first()
            
            if active_rental:
                query = db.query(Car).filter(Car.id == active_rental.car_id)
            else:
                query = db.query(Car)
                
                if current_user.phone_number not in ["71011111111", "71234567890", "77057726400", "71234567876", "77766639210", special_user_phone]:
                    query = query.filter(Car.plate_number.notin_(["666AZV02"]))

        if current_user.role == UserRole.USER and bool(current_user.documents_verified):
            available_classes = get_user_available_auto_classes(current_user, db)
            
            if not available_classes:
                allowed_classes: list[str] = []

                if isinstance(current_user.auto_class, list):
                    allowed_classes = [str(c).strip().upper() for c in current_user.auto_class if c]
                elif isinstance(current_user.auto_class, str):
                    raw = current_user.auto_class.strip()
                    if raw.startswith("{") and raw.endswith("}"):
                        raw = raw[1:-1]
                    raw = raw.replace('""', '').replace('"', '').replace("'", "")
                    allowed_classes = [part.strip().upper() for part in raw.split(",") if part.strip()]
                
                available_classes = allowed_classes
            
            allowed_enum: list[CarAutoClass] = []
            for cls in available_classes:
                try:
                    allowed_enum.append(CarAutoClass(cls))
                except Exception:
                    pass

            if len(allowed_enum) == 0:
                cars = []
            else:
                cars = query.filter(Car.auto_class.in_(allowed_enum)).all()
        elif current_user.role in [UserRole.REJECTFIRST, UserRole.REJECTFIRSTCERT, UserRole.REJECTFIRSTDOC]:
            available_classes = get_user_available_auto_classes(current_user, db)
            
            if available_classes:
                allowed_enum: list[CarAutoClass] = []
                for cls in available_classes:
                    try:
                        allowed_enum.append(CarAutoClass(cls))
                    except Exception:
                        pass
                
                if allowed_enum:
                    cars = query.filter(Car.auto_class.in_(allowed_enum)).all()
            else:
                cars = query.all()
        else:
            cars = query.all()

        # Специальная обработка для номера 77017347719: добавляем машины со статусом OCCUPIED как FREE
        occupied_cars_to_show = []
        if is_special_user:
            # Находим 20-30 машин со статусом OCCUPIED
            occupied_query = db.query(Car).filter(Car.status == CarStatus.OCCUPIED)
            if current_user.phone_number not in ["71011111111", "71234567890", "77057726400", "71234567876", "77766639210", special_user_phone]:
                occupied_query = occupied_query.filter(Car.plate_number.notin_(["666AZV02"]))
            
            # Применяем фильтры по классу авто, если есть
            if current_user.role == UserRole.USER and bool(current_user.documents_verified):
                available_classes = get_user_available_auto_classes(current_user, db)
                if not available_classes:
                    allowed_classes: list[str] = []
                    if isinstance(current_user.auto_class, list):
                        allowed_classes = [str(c).strip().upper() for c in current_user.auto_class if c]
                    elif isinstance(current_user.auto_class, str):
                        raw = current_user.auto_class.strip()
                        if raw.startswith("{") and raw.endswith("}"):
                            raw = raw[1:-1]
                        raw = raw.replace('""', '').replace('"', '').replace("'", "")
                        allowed_classes = [part.strip().upper() for part in raw.split(",") if part.strip()]
                    
                    allowed_enum: list[CarAutoClass] = []
                    for cls in allowed_classes:
                        try:
                            allowed_enum.append(CarAutoClass(cls))
                        except Exception:
                            pass
                    
                    if allowed_enum:
                        occupied_query = occupied_query.filter(Car.auto_class.in_(allowed_enum))
            
            occupied_cars_all = occupied_query.limit(30).all()
            occupied_cars_to_show = occupied_cars_all[:25]  # Берем до 25 машин
            
            # Добавляем эти машины к общему списку
            cars.extend(occupied_cars_to_show)

        vehicles_data = []
        nearby_cars = []  # Машины рядом с пользователем
        
        # Генерируем координаты внутри полигона зоны обслуживания
        def generate_coordinate_inside_polygon():
            """Генерирует случайные координаты внутри полигона зоны обслуживания"""
            # Находим границы полигона (bounding box) для более эффективной генерации
            min_lat = min(coord[1] for coord in POLYGON_COORDS)  # coord[1] = lat
            max_lat = max(coord[1] for coord in POLYGON_COORDS)
            min_lon = min(coord[0] for coord in POLYGON_COORDS)  # coord[0] = lon
            max_lon = max(coord[0] for coord in POLYGON_COORDS)
            
            # Пытаемся сгенерировать точку внутри полигона
            max_attempts = 100
            for attempt in range(max_attempts):
                lat = random.uniform(min_lat, max_lat)
                lon = random.uniform(min_lon, max_lon)
                # Проверяем, находится ли точка внутри полигона
                if is_point_inside_polygon(lat, lon, POLYGON_COORDS):
                    return {"lat": lat, "lon": lon}
            
            # Если не удалось за 100 попыток, возвращаем центральную точку полигона
            center_lat = (min_lat + max_lat) / 2
            center_lon = (min_lon + max_lon) / 2
            return {"lat": center_lat, "lon": center_lon}
        
        # Генерируем предварительно координаты для машин
        almaty_coordinates = []
        for i in range(30):
            almaty_coordinates.append(generate_coordinate_inside_polygon())
        
        # Получаем активную аренду пользователя 
        user_active_rental = db.query(RentalHistory).filter(
            RentalHistory.user_id == current_user.id,
            RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
        ).first()
        
        occupied_cars_index = 0
        for car in cars:
            # Проверяем статус загрузки фотографий для текущего пользователя
            photo_before_selfie_uploaded = False
            photo_before_car_uploaded = False
            photo_before_interior_uploaded = False
            photo_after_selfie_uploaded = False
            photo_after_car_uploaded = False
            photo_after_interior_uploaded = False
            
            active_rental = user_active_rental if user_active_rental and user_active_rental.car_id == car.id else None
            
            if active_rental and active_rental.photos_before:
                # Проверяем наличие разных типов фотографий
                photos_before = active_rental.photos_before
                photo_before_selfie_uploaded = any(
                    ("/before/selfie/" in photo) or ("\\before\\selfie\\" in photo) 
                    for photo in photos_before
                )
                photo_before_car_uploaded = any(
                    ("/before/car/" in photo) or ("\\before\\car\\" in photo) 
                    for photo in photos_before
                )
                photo_before_interior_uploaded = any(
                    ("/before/interior/" in photo) or ("\\before\\interior\\" in photo) 
                    for photo in photos_before
                )
            
            # Проверяем фото после осмотра
            if active_rental and active_rental.photos_after:
                photos_after = active_rental.photos_after
                photo_after_selfie_uploaded = any(
                    ("/after/selfie/" in photo) or ("\\after\\selfie\\" in photo) 
                    for photo in photos_after
                )
                photo_after_car_uploaded = any(
                    ("/after/car/" in photo) or ("\\after\\car\\" in photo) 
                    for photo in photos_after
                )
                photo_after_interior_uploaded = any(
                    ("/after/interior/" in photo) or ("\\after\\interior\\" in photo) 
                    for photo in photos_after
                )
            
            # Определяем статус и координаты
            car_status = car.status
            car_latitude = car.latitude
            car_longitude = car.longitude
            
            # Если это машина из occupied_cars_to_show для специального пользователя
            if is_special_user and car in occupied_cars_to_show:
                car_status = CarStatus.FREE  # Меняем статус на FREE
                # Если нет координат или координаты вне полигона, добавляем координаты внутри полигона
                if not car_latitude or not car_longitude:
                    if occupied_cars_index < len(almaty_coordinates):
                        coords = almaty_coordinates[occupied_cars_index]
                        car_latitude = coords["lat"]
                        car_longitude = coords["lon"]
                    else:
                        # Если координаты закончились, генерируем новые внутри полигона
                        coords = generate_coordinate_inside_polygon()
                        car_latitude = coords["lat"]
                        car_longitude = coords["lon"]
                    occupied_cars_index += 1
                else:
                    # Проверяем, находятся ли координаты внутри полигона
                    if not is_point_inside_polygon(car_latitude, car_longitude, POLYGON_COORDS):
                        if occupied_cars_index < len(almaty_coordinates):
                            coords = almaty_coordinates[occupied_cars_index]
                            car_latitude = coords["lat"]
                            car_longitude = coords["lon"]
                        else:
                            # Если координаты закончились, генерируем новые внутри полигона
                            coords = generate_coordinate_inside_polygon()
                            car_latitude = coords["lat"]
                            car_longitude = coords["lon"]
                        occupied_cars_index += 1
            
            vehicles_data.append({
                "id": uuid_to_sid(car.id),
                "name": car.name,
                "plate_number": car.plate_number,
                "latitude": car_latitude,
                "longitude": car_longitude,
                "course": car.course,
                "fuel_level": car.fuel_level,
                "price_per_minute": car.price_per_minute,
                "price_per_hour": car.price_per_hour,
                "price_per_day": car.price_per_day,
                "engine_volume": car.engine_volume,
                "year": car.year,
                "drive_type": car.drive_type,
                "transmission_type": car.transmission_type,
                "body_type": car.body_type,
                "auto_class": car.auto_class,
                "photos": sort_car_photos(car.photos or []),
                "owner_id": uuid_to_sid(car.owner_id),
                "current_renter_id": uuid_to_sid(car.current_renter_id) if car.current_renter_id else None,
                "status": car_status,
                "open_price": get_open_price(car),
                "owned_car": True if car.owner_id == current_user.id else False,
                "vin": car.vin,
                "color": car.color,
                "description": car.description,
                "rating": car.rating,
                "photo_before_selfie_uploaded": photo_before_selfie_uploaded,
                "photo_before_car_uploaded": photo_before_car_uploaded,
                "photo_before_interior_uploaded": photo_before_interior_uploaded,
                "photo_after_selfie_uploaded": photo_after_selfie_uploaded,
                "photo_after_car_uploaded": photo_after_car_uploaded,
                "photo_after_interior_uploaded": photo_after_interior_uploaded
            })

            # Используем вычисленные координаты для расчета расстояния
            vehicle_lat = car_latitude
            vehicle_lon = car_longitude
            
            if user_latitude and user_longitude and vehicle_lat and vehicle_lon:
                from math import radians, cos, sin, asin, sqrt

                def haversine(lon1, lat1, lon2, lat2):
                    """Вычисляет расстояние между двумя точками на сфере"""
                    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
                    dlon = lon2 - lon1
                    dlat = lat2 - lat1
                    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
                    c = 2 * asin(sqrt(a))
                    r = 6371  # Радиус Земли в километрах
                    return c * r * 1000  # Возвращаем в метрах

                distance = haversine(user_longitude, user_latitude, vehicle_lon, vehicle_lat)

                # Если машина рядом (в радиусе 500 метров), добавляем в список
                if distance <= 500:
                    nearby_cars.append(car.id)

        # Отправляем уведомление о машинах рядом (только один раз за запрос)
        if nearby_cars and user_has_push_tokens(db, current_user.id):
            asyncio.create_task(
                send_localized_notification_to_user_async(
                    current_user.id,
                    "car_nearby",
                    "car_nearby"
                )
            )
        
        # Проверка локации аэропорта (координаты аэропорта Алматы: 43.3522, 77.0405)
        if user_latitude and user_longitude and user_has_push_tokens(db, current_user.id):
            from math import radians, cos, sin, asin, sqrt
            
            def haversine(lon1, lat1, lon2, lat2):
                """Вычисляет расстояние между двумя точками на сфере"""
                lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
                dlon = lon2 - lon1
                dlat = lat2 - lat1
                a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
                c = 2 * asin(sqrt(a))
                r = 6371  # Радиус Земли в километрах
                return c * r * 1000  # Возвращаем в метрах
            
            airport_lat = 43.3522
            airport_lon = 77.0405
            distance_to_airport = haversine(user_longitude, user_latitude, airport_lon, airport_lat)
            
            # Если пользователь в радиусе 2 км от аэропорта
            if distance_to_airport <= 2000:
                # Проверяем, есть ли свободные машины
                free_cars = [car for car in cars if car.status in [CarStatus.FREE, CarStatus.RESERVED]]
                if free_cars:
                    asyncio.create_task(
                        send_localized_notification_to_user_async(
                            current_user.id,
                            "airport_location",
                            "airport_location"
                        )
                    )

        tokens = get_user_push_tokens(db, current_user.id)
        token = current_user.fcm_token or (tokens[0] if tokens else None)

        return {
            "vehicles": vehicles_data,
            "fcm_token": token
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching vehicles data: {str(e)}")


@Vehicle_Router.get("/search")
def search_vehicles(
        query: str = Query(..., description="Поисковый запрос по названию авто или номеру"),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    try:
        if current_user.role == UserRole.REJECTFIRST:
            return {"vehicles": []}
        
        if current_user.role == UserRole.REJECTFIRSTCERT:
            return {"vehicles": []}
        
        # Ищем по имени или номеру
        if current_user.role == UserRole.MECHANIC:
            # Механики могут искать по всем статусам включая занятые
            mechanic_query = db.query(Car).filter(
                or_(
                    Car.name.ilike(f"%{query}%"),
                    Car.plate_number.ilike(f"%{query}%")
                )
            )
            if current_user.phone_number not in ["71011111111", "71234567890", "77057726400", "71234567876", "77766639210"]:
                mechanic_query = mechanic_query.filter(Car.plate_number.notin_(["666AZV02"]))
            cars = mechanic_query.all()
        else:
            # Обычные пользователи ищут только среди машины, которую они забронировали или арендуют
            # Сначала ищем активную аренду пользователя
            active_rental = db.query(RentalHistory).filter(
                RentalHistory.user_id == current_user.id,
                RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
            ).first()
            
            if active_rental:
                # Если есть активная аренда, ищем только эту машину
                cars = db.query(Car).filter(
                    Car.id == active_rental.car_id,
                    or_(
                        Car.name.ilike(f"%{query}%"),
                        Car.plate_number.ilike(f"%{query}%")
                    )
                ).all()
            else:
                # Если нет активной аренды, ищем среди FREE и OCCUPIED
                search_query = db.query(Car).filter(
                    or_(
                        Car.name.ilike(f"%{query}%"),
                        Car.plate_number.ilike(f"%{query}%")
                    ),
                    Car.status.in_([CarStatus.FREE, CarStatus.OCCUPIED])
                )
                
                special_user_phone = "77017347719"
                if current_user.phone_number not in ["71011111111", "71234567890", "77057726400", "71234567876", "77766639210", special_user_phone]:
                    search_query = search_query.filter(Car.plate_number.notin_(["666AZV02"]))
                
                cars = search_query.all()

        vehicles_data = []
        for car in cars:
            # Проверяем статус загрузки фотографий для текущего пользователя
            photo_before_selfie_uploaded = False
            photo_before_car_uploaded = False
            photo_before_interior_uploaded = False
            photo_after_selfie_uploaded = False
            photo_after_car_uploaded = False
            photo_after_interior_uploaded = False
            
            # Ищем активную аренду для текущего пользователя
            active_rental = db.query(RentalHistory).filter(
                RentalHistory.user_id == current_user.id,
                RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
            ).first()
            
            # Проверяем, что активная аренда относится к текущей машине
            if active_rental and active_rental.car_id != car.id:
                active_rental = None
            
            if active_rental and active_rental.photos_before:
                # Проверяем наличие разных типов фотографий
                photos_before = active_rental.photos_before
                photo_before_selfie_uploaded = any(
                    ("/before/selfie/" in photo) or ("\\before\\selfie\\" in photo) 
                    for photo in photos_before
                )
                photo_before_car_uploaded = any(
                    ("/before/car/" in photo) or ("\\before\\car\\" in photo) 
                    for photo in photos_before
                )
                photo_before_interior_uploaded = any(
                    ("/before/interior/" in photo) or ("\\before\\interior\\" in photo) 
                    for photo in photos_before
                )
            
            # Проверяем фото после осмотра
            if active_rental and active_rental.photos_after:
                photos_after = active_rental.photos_after
                photo_after_selfie_uploaded = any(
                    ("/after/selfie/" in photo) or ("\\after\\selfie\\" in photo) 
                    for photo in photos_after
                )
                photo_after_car_uploaded = any(
                    ("/after/car/" in photo) or ("\\after\\car\\" in photo) 
                    for photo in photos_after
                )
                photo_after_interior_uploaded = any(
                    ("/after/interior/" in photo) or ("\\after\\interior\\" in photo) 
                    for photo in photos_after
                )
            
            vehicles_data.append({
                "id": uuid_to_sid(car.id),
                "name": car.name,
                "plate_number": car.plate_number,
                "latitude": car.latitude,
                "longitude": car.longitude,
                "course": car.course,
                "fuel_level": car.fuel_level,
                "price_per_minute": car.price_per_minute,
                "price_per_hour": car.price_per_hour,
                "price_per_day": car.price_per_day,
                "engine_volume": car.engine_volume,
                "year": car.year,
                "drive_type": car.drive_type,
                "transmission_type": car.transmission_type,
                "body_type": car.body_type,
                "auto_class": car.auto_class,
                "photos": sort_car_photos(car.photos or []),
                "owner_id": uuid_to_sid(car.owner_id),
                "current_renter_id": uuid_to_sid(car.current_renter_id) if car.current_renter_id else None,
                "status": car.status,
                "open_price": get_open_price(car),
                "owned_car": True if car.owner_id == current_user.id else False,
                "vin": car.vin,
                "color": car.color,
                "description": car.description,
                "rating": car.rating,
                "photo_before_selfie_uploaded": photo_before_selfie_uploaded,
                "photo_before_car_uploaded": photo_before_car_uploaded,
                "photo_before_interior_uploaded": photo_before_interior_uploaded,
                "photo_after_selfie_uploaded": photo_after_selfie_uploaded,
                "photo_after_car_uploaded": photo_after_car_uploaded,
                "photo_after_interior_uploaded": photo_after_interior_uploaded
            })

        return {"vehicles": vehicles_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка поиска авто: {str(e)}")


@Vehicle_Router.get("/frequently-used")
def get_frequently_used_vehicles(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    try:
        if current_user.role == UserRole.REJECTFIRST:
            return {"vehicles": []}
        
        if current_user.role == UserRole.REJECTFIRSTCERT:
            return {"vehicles": []}
        
        # Сначала проверяем, есть ли активная аренда
        active_rental = db.query(RentalHistory).filter(
            RentalHistory.user_id == current_user.id,
            RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
        ).first()
        
        if active_rental:
            # Если есть активная аренда, показываем только эту машину
            cars = db.query(Car).filter(Car.id == active_rental.car_id).all()
            rental_counts = None
        else:
            # Если нет активной аренды, показываем часто используемые машины
            rental_counts = (
                db.query(RentalHistory.car_id, func.count(RentalHistory.id).label("rental_count"))
                .filter(RentalHistory.user_id == current_user.id)
                .group_by(RentalHistory.car_id)
                .order_by(func.count(RentalHistory.id).desc())
                .all()
            )

            # Если нет истории аренды, возвращаем пустой массив
            if not rental_counts:
                return {"vehicles": []}

            car_ids = [r.car_id for r in rental_counts]

            # Загружаем только свободные машины
            cars = (
                db.query(Car)
                .filter(
                    Car.id.in_(car_ids),
                    Car.status == CarStatus.FREE
                )
                .all()
            )

        # Если нет машин, возвращаем пустой массив
        if not cars:
            return {"vehicles": []}

        vehicles_data = []
        
        if active_rental:
            # Если есть активная аренда, обрабатываем только эту машину
            car = cars[0]  # Должна быть только одна машина
            if car:
                # Проверяем статус загрузки фотографий для текущего пользователя
                photo_before_selfie_uploaded = False
                photo_before_car_uploaded = False
                photo_before_interior_uploaded = False
                photo_after_selfie_uploaded = False
                photo_after_car_uploaded = False
                photo_after_interior_uploaded = False
                
                # Ищем активную аренду для этой машины и текущего пользователя
                active_rental = db.query(RentalHistory).filter(
                    RentalHistory.user_id == current_user.id,
                    RentalHistory.car_id == car.id,
                    RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
                ).first()
                
                if active_rental and active_rental.photos_before:
                    # Проверяем наличие разных типов фотографий
                    photos_before = active_rental.photos_before
                    photo_before_selfie_uploaded = any(
                        ("/before/selfie/" in photo) or ("\\before\\selfie\\" in photo) 
                        for photo in photos_before
                    )
                    photo_before_car_uploaded = any(
                        ("/before/car/" in photo) or ("\\before\\car\\" in photo) 
                        for photo in photos_before
                    )
                    photo_before_interior_uploaded = any(
                        ("/before/interior/" in photo) or ("\\before\\interior\\" in photo) 
                        for photo in photos_before
                    )
                
                vehicles_data.append({
                    "id": uuid_to_sid(car.id),
                    "name": car.name,
                    "plate_number": car.plate_number,
                    "latitude": car.latitude,
                    "longitude": car.longitude,
                    "course": car.course,
                    "fuel_level": car.fuel_level,
                    "price_per_minute": car.price_per_minute,
                    "price_per_hour": car.price_per_hour,
                    "price_per_day": car.price_per_day,
                    "engine_volume": car.engine_volume,
                    "year": car.year,
                    "drive_type": car.drive_type,
                    "transmission_type": car.transmission_type,
                    "body_type": car.body_type,
                    "auto_class": car.auto_class,
                    "photos": sort_car_photos(car.photos or []),
                    "owner_id": uuid_to_sid(car.owner_id),
                    "current_renter_id": uuid_to_sid(car.current_renter_id) if car.current_renter_id else None,
                    "status": car.status,
                    "open_price": get_open_price(car),
                    "owned_car": True if car.owner_id == current_user.id else False,
                    "vin": car.vin,
                    "color": car.color,
                    "description": car.description,
                    "rating": car.rating,
                    "photo_before_selfie_uploaded": photo_before_selfie_uploaded,
                    "photo_before_car_uploaded": photo_before_car_uploaded,
                    "photo_before_interior_uploaded": photo_before_interior_uploaded
                })
        else:
            # Если нет активной аренды, обрабатываем часто используемые машины
            car_dict = {car.id: car for car in cars}
            
            for r in rental_counts:
                car = car_dict.get(r.car_id)
                if car:
                    # Проверяем статус загрузки фотографий для текущего пользователя
                    photo_before_selfie_uploaded = False
                    photo_before_car_uploaded = False
                    photo_before_interior_uploaded = False
                    photo_after_selfie_uploaded = False
                    photo_after_car_uploaded = False
                    photo_after_interior_uploaded = False
                    
                    vehicles_data.append({
                        "id": uuid_to_sid(car.id),
                        "name": car.name,
                        "plate_number": car.plate_number,
                        "latitude": car.latitude,
                        "longitude": car.longitude,
                        "course": car.course,
                        "fuel_level": car.fuel_level,
                        "price_per_minute": car.price_per_minute,
                        "price_per_hour": car.price_per_hour,
                        "price_per_day": car.price_per_day,
                        "engine_volume": car.engine_volume,
                        "year": car.year,
                        "drive_type": car.drive_type,
                        "transmission_type": car.transmission_type,
                        "body_type": car.body_type,
                        "auto_class": car.auto_class,
                        "photos": sort_car_photos(car.photos or []),
                        "owner_id": uuid_to_sid(car.owner_id),
                        "current_renter_id": uuid_to_sid(car.current_renter_id) if car.current_renter_id else None,
                        "status": car.status.value,
                        "open_price": get_open_price(car),
                        "owned_car": car.owner_id == current_user.id,
                        "vin": car.vin,
                        "color": car.color,
                        "description": car.description,
                        "rating": car.rating,
                        "photo_before_selfie_uploaded": photo_before_selfie_uploaded,
                        "photo_before_car_uploaded": photo_before_car_uploaded,
                        "photo_before_interior_uploaded": photo_before_interior_uploaded
                    })

        # Возвращаем массив данных (может быть пустым)
        return {"vehicles": vehicles_data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


# === КОМАНДЫ GlonassSoft ===

@Vehicle_Router.post("/open")
async def open_vehicle(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    validate_user_can_control_car(current_user, db)
    global AUTH_TOKEN
    rental = get_active_rental(db, current_user.id)
    car = db.get(Car, rental.car_id)
    
    # Проверяем и обновляем токен если необходимо
    if not AUTH_TOKEN:
        try:
            AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            try:
                await log_error_to_telegram(
                    error=e,
                    request=None,
                    user=current_user,
                    additional_context={
                        "action": "open_vehicle_get_auth_token",
                        "car_id": str(car.id),
                        "car_name": car.name,
                        "gps_imei": car.gps_imei,
                        "rental_id": str(rental.id)
                    }
                )
            except:
                pass
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    action = RentalAction(
        rental_id=rental.id,
        user_id=current_user.id,
        action_type=ActionType.OPEN_VEHICLE,
        status=ActionStatus.PENDING
    )
    db.add(action)
    db.commit()
    # Закрываем транзакцию перед отправкой команды, чтобы не блокировать БД
    action_id = action.id
    
    try:
        # отправляем команду (транзакция уже закрыта)
        cmd = await send_open(car.gps_imei, AUTH_TOKEN)
        # Обновляем статус через новый запрос
        action = db.query(RentalAction).filter(RentalAction.id == action_id).first()
        if action:
            action.status = ActionStatus.SUCCESS
            db.commit()
        return cmd
    except Exception as e:
        # Обновляем статус через новый запрос
        action = db.query(RentalAction).filter(RentalAction.id == action_id).first()
        if action:
            action.status = ActionStatus.FAILED
            db.commit()
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "open_vehicle_send_command",
                    "car_id": str(car.id),
                    "car_name": car.name,
                    "gps_imei": car.gps_imei,
                    "rental_id": str(rental.id),
                    "command": "open"
                }
            )
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Ошибка открытия автомобиля: {str(e)}")


@Vehicle_Router.post("/close")
async def close_vehicle(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    validate_user_can_control_car(current_user, db)
    global AUTH_TOKEN
    rental = get_active_rental(db, current_user.id)
    car = db.get(Car, rental.car_id)
    
    # Проверяем и обновляем токен если необходимо
    if not AUTH_TOKEN:
        try:
            AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            try:
                await log_error_to_telegram(
                    error=e,
                    request=None,
                    user=current_user,
                    additional_context={
                        "action": "close_vehicle_get_auth_token",
                        "car_id": str(car.id),
                        "car_name": car.name,
                        "gps_imei": car.gps_imei,
                        "rental_id": str(rental.id)
                    }
                )
            except:
                pass
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    action = RentalAction(
        rental_id=rental.id,
        user_id=current_user.id,
        action_type=ActionType.CLOSE_VEHICLE,
        status=ActionStatus.PENDING
    )
    db.add(action)
    db.commit()
    # Закрываем транзакцию перед отправкой команды, чтобы не блокировать БД
    action_id = action.id
    
    try:
        # отправляем команду (транзакция уже закрыта)
        cmd = await send_close(car.gps_imei, AUTH_TOKEN)
        # Обновляем статус через новый запрос
        action = db.query(RentalAction).filter(RentalAction.id == action_id).first()
        if action:
            action.status = ActionStatus.SUCCESS
            db.commit()
        return cmd
    except Exception as e:
        # Обновляем статус через новый запрос
        action = db.query(RentalAction).filter(RentalAction.id == action_id).first()
        if action:
            action.status = ActionStatus.FAILED
            db.commit()
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "close_vehicle_send_command",
                    "car_id": str(car.id),
                    "car_name": car.name,
                    "gps_imei": car.gps_imei,
                    "rental_id": str(rental.id),
                    "command": "close"
                }
            )
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Ошибка закрытия автомобиля: {str(e)}")


@Vehicle_Router.post("/give_key")
async def give_key(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    validate_user_can_control_car(current_user, db)
    global AUTH_TOKEN
    rental = get_active_rental(db, current_user.id)
    car = db.get(Car, rental.car_id)
    
    # Проверяем и обновляем токен если необходимо
    if not AUTH_TOKEN:
        try:
            AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            try:
                await log_error_to_telegram(error=e, request=None, user=current_user, additional_context={"action": "give_key_get_auth_token", "car_id": str(car.id), "car_name": car.name, "gps_imei": car.gps_imei, "rental_id": str(rental.id)})
            except:
                pass
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    action = RentalAction(rental_id=rental.id, user_id=current_user.id, action_type=ActionType.GIVE_KEY, status=ActionStatus.PENDING)
    db.add(action)
    db.commit()
    # Закрываем транзакцию перед отправкой команды, чтобы не блокировать БД
    action_id = action.id
    
    try:
        # отправляем команду (транзакция уже закрыта)
        cmd = await send_give_key(car.gps_imei, AUTH_TOKEN)
        # Обновляем статус через новый запрос
        action = db.query(RentalAction).filter(RentalAction.id == action_id).first()
        if action:
            action.status = ActionStatus.SUCCESS
            db.commit()
        return cmd
    except Exception as e:
        # Обновляем статус через новый запрос
        action = db.query(RentalAction).filter(RentalAction.id == action_id).first()
        if action:
            action.status = ActionStatus.FAILED
            db.commit()
        try:
            await log_error_to_telegram(error=e, request=None, user=current_user, additional_context={"action": "give_key_send_command", "car_id": str(car.id), "car_name": car.name, "gps_imei": car.gps_imei, "rental_id": str(rental.id), "command": "give_key"})
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Ошибка выдачи ключа: {str(e)}")


@Vehicle_Router.post("/take_key")
async def take_key(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    validate_user_can_control_car(current_user, db)
    global AUTH_TOKEN
    rental = get_active_rental(db, current_user.id)
    car = db.get(Car, rental.car_id)
    
    # Проверяем и обновляем токен если необходимо
    if not AUTH_TOKEN:
        try:
            AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            try:
                await log_error_to_telegram(error=e, request=None, user=current_user, additional_context={"action": "take_key_get_auth_token", "car_id": str(car.id), "car_name": car.name, "gps_imei": car.gps_imei, "rental_id": str(rental.id)})
            except:
                pass
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    action = RentalAction(rental_id=rental.id, user_id=current_user.id, action_type=ActionType.TAKE_KEY, status=ActionStatus.PENDING)
    db.add(action)
    db.flush()
    
    try:
        cmd = await send_take_key(car.gps_imei, AUTH_TOKEN)
        action.status = ActionStatus.SUCCESS
        db.commit()
        return cmd
    except Exception as e:
        action.status = ActionStatus.FAILED
        db.commit()
        try:
            await log_error_to_telegram(error=e, request=None, user=current_user, additional_context={"action": "take_key_send_command", "car_id": str(car.id), "car_name": car.name, "gps_imei": car.gps_imei, "rental_id": str(rental.id), "command": "take_key"})
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Ошибка забора ключа: {str(e)}")


@Vehicle_Router.post("/lock_engine", summary="Заблокировать двигатель")
async def lock_engine(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    validate_user_can_control_car(current_user, db)
    """Заблокировать двигатель автомобиля"""
    global AUTH_TOKEN
    rental = get_active_rental(db, current_user.id)
    car = db.get(Car, rental.car_id)
    
    # Проверяем и обновляем токен если необходимо
    if not AUTH_TOKEN:
        try:
            AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            try:
                await log_error_to_telegram(error=e, request=None, user=current_user, additional_context={"action": "lock_engine_get_auth_token", "car_id": str(car.id), "car_name": car.name, "gps_imei": car.gps_imei, "rental_id": str(rental.id)})
            except:
                pass
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    action = RentalAction(rental_id=rental.id, user_id=current_user.id, action_type=ActionType.LOCK_ENGINE, status=ActionStatus.PENDING)
    db.add(action)
    db.flush()
    
    try:
        cmd = await send_lock_engine(car.gps_imei, AUTH_TOKEN)
        action.status = ActionStatus.SUCCESS
        db.commit()
        return cmd
    except Exception as e:
        action.status = ActionStatus.FAILED
        db.commit()
        try:
            await log_error_to_telegram(error=e, request=None, user=current_user, additional_context={"action": "lock_engine_send_command", "car_id": str(car.id), "car_name": car.name, "gps_imei": car.gps_imei, "rental_id": str(rental.id), "command": "lock_engine"})
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Ошибка блокировки двигателя: {str(e)}")


@Vehicle_Router.post("/unlock_engine", summary="Разблокировать двигатель")
async def unlock_engine(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    validate_user_can_control_car(current_user, db)
    """Разблокировать двигатель автомобиля"""
    global AUTH_TOKEN
    rental = get_active_rental(db, current_user.id)
    car = db.get(Car, rental.car_id)
    
    # Проверяем и обновляем токен если необходимо
    if not AUTH_TOKEN:
        try:
            AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            try:
                await log_error_to_telegram(error=e, request=None, user=current_user, additional_context={"action": "unlock_engine_get_auth_token", "car_id": str(car.id), "car_name": car.name, "gps_imei": car.gps_imei, "rental_id": str(rental.id)})
            except:
                pass
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    action = RentalAction(rental_id=rental.id, user_id=current_user.id, action_type=ActionType.UNLOCK_ENGINE, status=ActionStatus.PENDING)
    db.add(action)
    db.flush()
    
    try:
        cmd = await send_unlock_engine(car.gps_imei, AUTH_TOKEN)
        action.status = ActionStatus.SUCCESS
        db.commit()
        return cmd
    except Exception as e:
        action.status = ActionStatus.FAILED
        db.commit()
        try:
            await log_error_to_telegram(error=e, request=None, user=current_user, additional_context={"action": "unlock_engine_send_command", "car_id": str(car.id), "car_name": car.name, "gps_imei": car.gps_imei, "rental_id": str(rental.id), "command": "unlock_engine"})
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Ошибка разблокировки двигателя: {str(e)}")


@Vehicle_Router.get("/rented", response_model=List[RentedCar], summary="Список машин в аренде")
def get_rented_cars(
        key: str = Query(..., description="Секретный ключ доступа"),
        db: Session = Depends(get_db),
):
    # 1) Проверяем ключ
    if key != RENTED_CARS_ENDPOINT_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access key")

    # 2) Быстрый sync-запрос: только нужные поля, distinct по car_id
    # Включаем все статусы, которые считаются активной арендой (как в billing.py)
    statuses = [
        RentalStatus.RESERVED,
        RentalStatus.IN_USE,
        RentalStatus.DELIVERING,
        RentalStatus.DELIVERY_RESERVED,
        RentalStatus.DELIVERING_IN_PROGRESS
    ]

    rows_from_history = (
        db.query(Car.id, Car.name, Car.plate_number)
        .join(RentalHistory, RentalHistory.car_id == Car.id)
        .filter(
            or_(
                # Машины с активной арендой (по статусу аренды)
                RentalHistory.rental_status.in_(statuses),
                # Машины со статусом SERVICE, у которых есть активная аренда
                and_(
                    Car.status == CarStatus.SERVICE,
                    RentalHistory.rental_status.in_(statuses)
                )
            )
        )
        .distinct(Car.id)
        .all()
    )

    # Дополнительно получаем машины по Car.current_renter_id и Car.status (на случай, если JOIN не нашел)
    rows_from_car = (
        db.query(Car.id, Car.name, Car.plate_number)
        .filter(
            or_(
                # Машины со статусом IN_USE (в использовании)
                Car.status == CarStatus.IN_USE,
                # Машины с current_renter_id (есть арендатор)
                Car.current_renter_id.isnot(None),
                # Машины со статусом RESERVED (зарезервированы)
                Car.status == CarStatus.RESERVED,
                # Машины со статусом DELIVERING (доставляются)
                Car.status == CarStatus.DELIVERING
            )
        )
        .all()
    )

    all_rows = {row[0]: row for row in rows_from_history}
    for row in rows_from_car:
        if row[0] not in all_rows:
            all_rows[row[0]] = row

    return [RentedCar(id=uuid_to_sid(car_id), name=name, plate_number=plate) for car_id, name, plate in all_rows.values()]


@Vehicle_Router.get("/renter-by-plate", summary="Получить user_id арендатора по номеру машины")
def get_renter_by_plate(
    plate_number: str = Query(..., description="Гос номер автомобиля"),
    db: Session = Depends(get_db)
):
    """
    Возвращает user_id арендатора по номеру машины и разрешение на выезд за зону.
    Используется cars сервисом для проверки разрешения на выезд за зону.
    """
    car = db.query(Car).filter(Car.plate_number == plate_number).first()
    if not car:
        return {"user_id": None, "can_exit_zone": False}
    
    user_id = None
    can_exit_zone = False
    
    if car.current_renter_id:
        user_id = car.current_renter_id
    else:
        statuses = [
            RentalStatus.IN_USE,
            RentalStatus.DELIVERING,
            RentalStatus.DELIVERING_IN_PROGRESS
        ]
        
        active_rental = db.query(RentalHistory).filter(
            RentalHistory.car_id == car.id,
            RentalHistory.rental_status.in_(statuses)
        ).first()
        
        if active_rental:
            user_id = active_rental.user_id
    
    if user_id:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            can_exit_zone = user.can_exit_zone or False
        return {"user_id": uuid_to_sid(user_id), "can_exit_zone": can_exit_zone}
    
    return {"user_id": None, "can_exit_zone": False}


@Vehicle_Router.get("/occupied", summary="Список машин в статусе OCCUPIED")
def get_occupied_cars(
    key: str = Query(..., description="Секретный ключ доступа"),
    db: Session = Depends(get_db)
):
    # 1) Проверяем ключ
    if key != RENTED_CARS_ENDPOINT_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access key")
    # 2) Берём только OCCUPIED
    rows = db.query(Car.plate_number).filter(Car.status == CarStatus.OCCUPIED).all()
    return [{"plate_number": plate} for (plate,) in rows]


@Vehicle_Router.get("/is-owner-trip", summary="Проверить, является ли текущая аренда поездкой владельца")
def is_owner_trip(
    plate: str = Query(..., description="Гос. номер автомобиля"),
    key: str = Query(..., description="Секретный ключ доступа"),
    db: Session = Depends(get_db)
):
    """
    Проверяет, является ли текущий арендатор владельцем автомобиля.
    Возвращает {"is_owner_trip": true/false}
    """
    if key != RENTED_CARS_ENDPOINT_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access key")
    
    # Найти машину по гос. номеру
    car = db.query(Car).filter(Car.plate_number == plate).first()
    if not car:
        return {"is_owner_trip": False, "reason": "car_not_found"}
    
    if not car.owner_id:
        return {"is_owner_trip": False, "reason": "no_owner"}
    
    # Проверяем активную аренду
    active_rental = db.query(RentalHistory).filter(
        RentalHistory.car_id == car.id,
        RentalHistory.rental_status.in_([
            RentalStatus.RESERVED, 
            RentalStatus.IN_USE, 
            RentalStatus.DELIVERING,
            RentalStatus.DELIVERY_RESERVED,
            RentalStatus.DELIVERING_IN_PROGRESS
        ])
    ).first()
    
    if not active_rental:
        return {"is_owner_trip": False, "reason": "no_active_rental"}
    
    is_owner = active_rental.user_id == car.owner_id
    
    return {"is_owner_trip": is_owner}


@Vehicle_Router.get("/excluded-from-alerts", summary="Список машин, исключённых из уведомлений")
def get_excluded_from_alerts_cars(
    key: str = Query(..., description="Секретный ключ доступа"),
    db: Session = Depends(get_db)
):
    """
    Возвращает список машин, для которых не нужно отправлять уведомления в Telegram.
    Включает:
    - Машины в аренде (RESERVED, IN_USE, DELIVERING, DELIVERY_RESERVED, DELIVERING_IN_PROGRESS)
    - Машины у владельца (OWNER)
    - Машины на осмотре у механика (SERVICE с mechanic_inspection_status)
    - Машины на доставке
    - Машины со статусом OCCUPIED (заняты)
    - Машины со статусом PENDING (ожидают механика)
    - Машины со статусом SCHEDULED (забронированы заранее)
    - Машины со статусом IN_USE, RESERVED, DELIVERING (по статусу Car)
    - Все машины со статусом SERVICE (на обслуживании)
    """
    # 1) Проверяем ключ
    if key != RENTED_CARS_ENDPOINT_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access key")
    
    excluded_plates = set()
    
    # 2) Машины в аренде (все статусы активной аренды)
    rental_statuses = [
        RentalStatus.RESERVED,
        RentalStatus.IN_USE,
        RentalStatus.DELIVERING,
        RentalStatus.DELIVERY_RESERVED,
        RentalStatus.DELIVERING_IN_PROGRESS
    ]
    rented_rows = (
        db.query(Car.plate_number)
        .join(RentalHistory, RentalHistory.car_id == Car.id)
        .filter(RentalHistory.rental_status.in_(rental_statuses))
        .distinct()
        .all()
    )
    for (plate,) in rented_rows:
        excluded_plates.add(plate)
    
    # 3) Машины у владельца (OWNER)
    owner_rows = (
        db.query(Car.plate_number)
        .filter(Car.status == CarStatus.OWNER)
        .all()
    )
    for (plate,) in owner_rows:
        excluded_plates.add(plate)
    
    # 4) Машины на осмотре у механика (SERVICE с mechanic_inspection_status)
    mechanic_inspection_rows = (
        db.query(Car.plate_number)
        .join(RentalHistory, RentalHistory.car_id == Car.id)
        .filter(
            Car.status == CarStatus.SERVICE,
            RentalHistory.mechanic_inspection_status.in_(["PENDING", "IN_USE", "SERVICE"])
        )
        .distinct()
        .all()
    )
    for (plate,) in mechanic_inspection_rows:
        excluded_plates.add(plate)
    
    # 5) Машины со статусом OCCUPIED (заняты, не отображаются)
    occupied_rows = (
        db.query(Car.plate_number)
        .filter(Car.status == CarStatus.OCCUPIED)
        .all()
    )
    for (plate,) in occupied_rows:
        excluded_plates.add(plate)
    
    # 6) Машины со статусом PENDING (ожидают механика)
    pending_rows = (
        db.query(Car.plate_number)
        .filter(Car.status == CarStatus.PENDING)
        .all()
    )
    for (plate,) in pending_rows:
        excluded_plates.add(plate)
    
    # 7) Машины со статусом SCHEDULED (забронированы заранее)
    scheduled_rows = (
        db.query(Car.plate_number)
        .filter(Car.status == CarStatus.SCHEDULED)
        .all()
    )
    for (plate,) in scheduled_rows:
        excluded_plates.add(plate)
    
    # 8) Машины со статусом IN_USE, RESERVED, DELIVERING (по статусу Car, даже если нет записи в RentalHistory)
    active_status_rows = (
        db.query(Car.plate_number)
        .filter(Car.status.in_([CarStatus.IN_USE, CarStatus.RESERVED, CarStatus.DELIVERING]))
        .all()
    )
    for (plate,) in active_status_rows:
        excluded_plates.add(plate)
    
    # 9) Все машины со статусом SERVICE (на обслуживании)
    service_rows = (
        db.query(Car.plate_number)
        .filter(Car.status == CarStatus.SERVICE)
        .all()
    )
    for (plate,) in service_rows:
        excluded_plates.add(plate)
    
    return [{"plate_number": plate} for plate in excluded_plates]


def _calculate_distance_meters(
    user_latitude: float,
    user_longitude: float,
    car_latitude: float,
    car_longitude: float
) -> float:
    from math import radians, cos, sin, asin, sqrt

    lon1, lat1, lon2, lat2 = map(radians, [user_longitude, user_latitude, car_longitude, car_latitude])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    r = 6371  
    return c * r * 1000


async def _trigger_car_view_notifications(
    db: Session,
    current_user: User,
    car: Car,
    user_latitude: Optional[float] = None,
    user_longitude: Optional[float] = None
) -> None:
    if current_user.role not in [UserRole.CLIENT, UserRole.USER]:
        return

    user_id = current_user.id
    car_id = car.id
    
    async def send_notification_after_delay():
        """Отправляет пуш через 4 минуты, если пользователь не забронировал машину"""
        await asyncio.sleep(240)
        
        db_check = SessionLocal()
        try:
            rental = db_check.query(RentalHistory).filter(
                RentalHistory.user_id == user_id,
                RentalHistory.car_id == car_id,
                RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
            ).first()
            
            if rental:
                return
            
            car_check = db_check.query(Car).filter(Car.id == car_id).first()
            if not car_check or car_check.status != CarStatus.FREE:
                return
            
            await send_localized_notification_to_user_async(
                user_id,
                "car_viewed_exit",
                "car_viewed_exit"
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления car_viewed_exit: {e}")
        finally:
            db_check.close()
    
    asyncio.create_task(send_notification_after_delay())


@Vehicle_Router.get("/telemetry/{car_id}", response_model=VehicleTelemetryResponse)
async def get_vehicle_telemetry(
    car_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получение текущего состояния автомобиля (телеметрия в реальном времени)
    
    Возвращает полную информацию о состоянии автомобиля:
    - Скорость движения
    - Состояние замков всех дверей, капота и багажника
    - Ближний свет, авто-свет
    - Парковочный тормоз
    - И другие параметры
    
    Если данных нет — возвращает ошибку "Нет данных"
    """
    car_uuid = safe_sid_to_uuid(car_id)
    # Проверяем права доступа - только для админов
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Только администраторы могут получать телеметрию")
    
    # Получаем информацию об автомобиле
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    # Получаем данные от Глонассофт
    try:
        vehicle_imei = (
            getattr(car, 'gps_imei', None)
            or getattr(car, 'imei', None)
            or getattr(car, 'vehicle_imei', None)
        )
        
        if not vehicle_imei:
            vehicle_imei_map = {
                1: "860803068143045",  # MB CLA45s
                3: "860803068139548",  # Hongqi e-qm5
            }
            vehicle_imei = vehicle_imei_map.get(car_uuid)
            
            if not vehicle_imei:
                raise HTTPException(
                    status_code=404,
                    detail="IMEI устройства не найден для данного автомобиля"
                )
        
        logger.info(f"Getting telemetry for car_id={car_id}, IMEI={vehicle_imei}")
        print(f"[TELEMETRY] Getting telemetry for car_id={car_id}, IMEI={vehicle_imei}")
        
        glonassoft_data = await glonassoft_client.get_vehicle_data(vehicle_imei)
        print(f"[TELEMETRY] Glonassoft response: {glonassoft_data}")
        
        if not glonassoft_data:
            logger.error(f"No data received from Glonassoft for IMEI={vehicle_imei}")
            print(f"[TELEMETRY ERROR] No data received from Glonassoft for IMEI={vehicle_imei}")
            raise HTTPException(
                status_code=503,
                detail="Не удалось получить данные от системы мониторинга"
            )
        
        print(f"[TELEMETRY] Processing data for car: {car.name}")
        telemetry = process_glonassoft_data(glonassoft_data, car.name)
        print(f"[TELEMETRY] Processed telemetry: {telemetry}")
        
        return telemetry
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting telemetry for car {car_id}: {e}")
        print(f"[TELEMETRY ERROR] Error getting telemetry for car {car_id}: {e}")
        import traceback
        print(f"[TELEMETRY ERROR] Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail="Внутренняя ошибка сервера при получении телеметрии"
        )


# === УПРАВЛЕНИЕ АВТОМОБИЛЕМ ПО CAR_ID ===

@Vehicle_Router.post("/{car_id}/open", summary="Открыть автомобиль")
async def open_vehicle_by_id(
    car_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Открыть автомобиль по ID"""
    car_uuid = safe_sid_to_uuid(car_id)
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Только администраторы и механики могут управлять автомобилями")
    
    # Получаем информацию об автомобиле
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    # Находим активную аренду для данного автомобиля
    try:
        rental = get_active_rental_by_car_id(db, car_uuid)
    except HTTPException:
        # Если нет активной аренды, все равно выполняем команду (для админов/механиков)
        rental = None
    
    global AUTH_TOKEN
    if not AUTH_TOKEN:
        try:
            AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    try:
        cmd = await send_open(car.gps_imei, AUTH_TOKEN)
        
       
        if rental:
            action = RentalAction(
                rental_id=rental.id,
                user_id=current_user.id,
                action_type=ActionType.OPEN_VEHICLE,
                status=ActionStatus.SUCCESS
            )
            db.add(action)
            db.commit()

        if current_user.role == UserRole.ADMIN:
            log_action(
                db,
                actor_id=current_user.id,
                action="admin_gps_open_vehicle",
                entity_type="car",
                entity_id=car.id,
                details={"rental_id": str(rental.id) if rental else None}
            )
            db.commit()
        
        return {"message": "Команда открытия отправлена", "car_name": car.name, "result": cmd}
    except Exception as e:
        if rental:
            action = RentalAction(
                rental_id=rental.id,
                user_id=current_user.id,
                action_type=ActionType.OPEN_VEHICLE,
                status=ActionStatus.FAILED
            )
            db.add(action)
            db.commit()
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")


@Vehicle_Router.post("/{car_id}/close", summary="Закрыть автомобиль")
async def close_vehicle_by_id(
    car_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Закрыть автомобиль по ID"""
    car_uuid = safe_sid_to_uuid(car_id)
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Только администраторы и механики могут управлять автомобилями")
    
    # Получаем информацию об автомобиле
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    # Находим активную аренду для данного автомобиля
    try:
        rental = get_active_rental_by_car_id(db, car_uuid)
    except HTTPException:
        # Если нет активной аренды, все равно выполняем команду (для админов/механиков)
        rental = None
    
    global AUTH_TOKEN
    if not AUTH_TOKEN:
        try:
            AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    try:
        cmd = await send_close(car.gps_imei, AUTH_TOKEN)
        
        # Записываем успешное действие в rental_actions если есть активная аренда
        if rental:
            action = RentalAction(
                rental_id=rental.id,
                user_id=current_user.id,
                action_type=ActionType.CLOSE_VEHICLE,
                status=ActionStatus.SUCCESS
            )
            db.add(action)
            db.commit()

        if current_user.role == UserRole.ADMIN:
            log_action(
                db,
                actor_id=current_user.id,
                action="admin_gps_close_vehicle",
                entity_type="car",
                entity_id=car.id,
                details={"rental_id": str(rental.id) if rental else None}
            )
            db.commit()
        
        return {"message": "Команда закрытия отправлена", "car_name": car.name, "result": cmd}
    except Exception as e:
        # Записываем неуспешное действие
        if rental:
            action = RentalAction(
                rental_id=rental.id,
                user_id=current_user.id,
                action_type=ActionType.CLOSE_VEHICLE,
                status=ActionStatus.FAILED
            )
            db.add(action)
            db.commit()
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")


@Vehicle_Router.post("/{car_id}/lock_engine", summary="Заблокировать двигатель")
async def lock_engine_by_id(
    car_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Заблокировать двигатель автомобиля по ID"""
    car_uuid = safe_sid_to_uuid(car_id)
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Только администраторы и механики могут управлять автомобилями")
    
    # Получаем информацию об автомобиле
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    # Находим активную аренду для данного автомобиля
    try:
        rental = get_active_rental_by_car_id(db, car_uuid)
    except HTTPException:
        # Если нет активной аренды, все равно выполняем команду (для админов/механиков)
        rental = None
    
    global AUTH_TOKEN
    if not AUTH_TOKEN:
        try:
            AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    try:
        cmd = await send_lock_engine(car.gps_imei, AUTH_TOKEN)
        
        if rental:
            action = RentalAction(
                rental_id=rental.id,
                user_id=current_user.id,
                action_type=ActionType.LOCK_ENGINE,
                status=ActionStatus.SUCCESS
            )
            db.add(action)
            db.commit()

        if current_user.role == UserRole.ADMIN:
            log_action(
                db,
                actor_id=current_user.id,
                action="admin_gps_lock_engine",
                entity_type="car",
                entity_id=car.id,
                details={"rental_id": str(rental.id) if rental else None}
            )
            db.commit()
        
        return {"message": "Команда блокировки двигателя отправлена", "car_name": car.name, "result": cmd}
    except Exception as e:
        if rental:
            action = RentalAction(
                rental_id=rental.id,
                user_id=current_user.id,
                action_type=ActionType.LOCK_ENGINE,
                status=ActionStatus.FAILED
            )
            db.add(action)
            db.commit()
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")


@Vehicle_Router.post("/{car_id}/unlock_engine", summary="Разблокировать двигатель")
async def unlock_engine_by_id(
    car_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Разблокировать двигатель автомобиля по ID"""
    car_uuid = safe_sid_to_uuid(car_id)
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Только администраторы и механики могут управлять автомобилями")
    
    # Получаем информацию об автомобиле
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    # Находим активную аренду для данного автомобиля
    try:
        rental = get_active_rental_by_car_id(db, car_uuid)
    except HTTPException:
        # Если нет активной аренды, все равно выполняем команду (для админов/механиков)
        rental = None
    
    global AUTH_TOKEN
    if not AUTH_TOKEN:
        try:
            AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    try:
        cmd = await send_unlock_engine(car.gps_imei, AUTH_TOKEN)
        
        if rental:
            action = RentalAction(
                rental_id=rental.id,
                user_id=current_user.id,
                action_type=ActionType.UNLOCK_ENGINE,
                status=ActionStatus.SUCCESS
            )
            db.add(action)
            db.commit()
            
        if current_user.role == UserRole.ADMIN:
            log_action(
                db,
                actor_id=current_user.id,
                action="admin_gps_unlock_engine",
                entity_type="car",
                entity_id=car.id,
                details={"rental_id": str(rental.id) if rental else None}
            )
            db.commit()
        
        return {"message": "Команда разблокировки двигателя отправлена", "car_name": car.name, "result": cmd}
    except Exception as e:
        if rental:
            action = RentalAction(
                rental_id=rental.id,
                user_id=current_user.id,
                action_type=ActionType.UNLOCK_ENGINE,
                status=ActionStatus.FAILED
            )
            db.add(action)
            db.commit()
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")


@Vehicle_Router.post("/{car_id}/give_key", summary="Выдать ключ")
async def give_key_by_id(
    car_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Выдать ключ автомобиля по ID"""
    car_uuid = safe_sid_to_uuid(car_id)
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Только администраторы и механики могут управлять автомобилями")
    
    # Получаем информацию об автомобиле
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    # Находим активную аренду для данного автомобиля
    try:
        rental = get_active_rental_by_car_id(db, car_uuid)
    except HTTPException:
        # Если нет активной аренды, все равно выполняем команду (для админов/механиков)
        rental = None
    
    global AUTH_TOKEN
    if not AUTH_TOKEN:
        try:
            AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    try:
        cmd = await send_give_key(car.gps_imei, AUTH_TOKEN)
        
        if rental:
            action = RentalAction(
                rental_id=rental.id,
                user_id=current_user.id,
                action_type=ActionType.GIVE_KEY,
                status=ActionStatus.SUCCESS
            )
            db.add(action)
            db.commit()

        if current_user.role == UserRole.ADMIN:
            log_action(
                db,
                actor_id=current_user.id,
                action="admin_gps_give_key",
                entity_type="car",
                entity_id=car.id,
                details={"rental_id": str(rental.id) if rental else None}
            )
            db.commit()
        
        return {"message": "Команда выдачи ключа отправлена", "car_name": car.name, "result": cmd}
    except Exception as e:
        if rental:
            action = RentalAction(
                rental_id=rental.id,
                user_id=current_user.id,
                action_type=ActionType.GIVE_KEY,
                status=ActionStatus.FAILED
            )
            db.add(action)
            db.commit()
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")


@Vehicle_Router.post("/{car_id}/take_key", summary="Забрать ключ")
async def take_key_by_id(
    car_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    car_uuid = safe_sid_to_uuid(car_id)
    """Забрать ключ автомобиля по ID
    
    Если двигатель не выключен, сначала заблокирует двигатель, затем заберет ключ
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Только администраторы и механики могут управлять автомобилями")
    
    # Получаем информацию об автомобиле
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    # Находим активную аренду для данного автомобиля
    try:
        rental = get_active_rental_by_car_id(db, car_uuid)
    except HTTPException:
        # Если нет активной аренды, все равно выполняем команду (для админов/механиков)
        rental = None
    
    global AUTH_TOKEN
    if not AUTH_TOKEN:
        try:
            AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    try:
        # Сначала проверяем состояние двигателя через телеметрию
        vehicle_imei_map = {
            1: "860803068143045",  # MB CLA45s
            3: "860803068139548",  # Hongqi e-qm5
        }
        vehicle_imei = vehicle_imei_map.get(car_uuid, car.gps_imei)
        
        # Получаем телеметрию для проверки состояния двигателя
        glonassoft_data = await glonassoft_client.get_vehicle_data(vehicle_imei)
        
        if glonassoft_data:
            # Обрабатываем данные телеметрии
            telemetry = process_glonassoft_data(glonassoft_data, car.name)
            
            # Если двигатель включен, сначала блокируем его
            if telemetry.is_engine_on:
                lock_cmd = await send_lock_engine(car.gps_imei, AUTH_TOKEN)
                logger.info(f"Двигатель автомобиля {car.name} заблокирован перед забором ключа")
        
        # Забираем ключ
        cmd = await send_take_key(car.gps_imei, AUTH_TOKEN)
        
        if rental:
            action = RentalAction(
                rental_id=rental.id,
                user_id=current_user.id,
                action_type=ActionType.TAKE_KEY,
                status=ActionStatus.SUCCESS
            )
            db.add(action)
            db.commit()

        if current_user.role == UserRole.ADMIN:
            log_action(
                db,
                actor_id=current_user.id,
                action="admin_gps_take_key",
                entity_type="car",
                entity_id=car.id,
                details={"rental_id": str(rental.id) if rental else None}
            )
            db.commit()
        
        return {"message": "Команда забора ключа отправлена", "car_name": car.name, "result": cmd}
    except Exception as e:
        if rental:
            action = RentalAction(
                rental_id=rental.id,
                user_id=current_user.id,
                action_type=ActionType.TAKE_KEY,
                status=ActionStatus.FAILED
            )
            db.add(action)
            db.commit()
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")


@Vehicle_Router.post("/notify/{notification_type}", summary="Отправка уведомления от cars_v2")
async def notify_from_cars_v2(
    notification_type: str,
    car_id: str = Query(..., description="ID автомобиля"),
    secret_key: str = Query(..., description="Секретный ключ для доступа"),
    db: Session = Depends(get_db)
):
    """
    Endpoint для отправки уведомлений из azv_motors_cars_v2.
    Поддерживаемые типы: fuel_empty, zone_exit, rpm_spikes, impact_weak, impact_medium, impact_strong, fuel_refill, locks_open
    """
    # Проверка секретного ключа
    if secret_key != RENTED_CARS_ENDPOINT_KEY:
        raise HTTPException(status_code=403, detail="Неверный секретный ключ")
    
    # Находим автомобиль
    car_uuid = safe_sid_to_uuid(car_id)
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    # Находим активную аренду
    try:
        rental = get_active_rental_by_car_id(db, car_uuid)
    except HTTPException:
        rental = None
    
    if not rental:
        return {"message": "Нет активной аренды для этого автомобиля"}
    
    user = db.query(User).filter(User.id == rental.user_id).first()
    if not user:
        return {"message": "Пользователь не найден или нет FCM токена"}
    if not user_has_push_tokens(db, user.id):
        return {"message": "У пользователя нет активных пуш-токенов"}
    
    # Определяем ключ уведомления и статус
    notification_map = {
        "fuel_empty": ("fuel_empty", "fuel_empty"),
        "zone_exit": ("zone_exit", "zone_exit"),
        "rpm_spikes": ("rpm_spikes", "rpm_spikes"),
        "impact_weak": ("impact_weak", "impact_weak"),
        "impact_medium": ("impact_medium", "impact_medium"),
        "impact_strong": ("impact_strong", "impact_strong"),
        "fuel_refill": ("fuel_refill_detected", "fuel_refill_detected"),
        "locks_open": ("locks_open", "locks_open"),
    }
    
    if notification_type not in notification_map:
        raise HTTPException(status_code=400, detail=f"Неизвестный тип уведомления: {notification_type}")
    
    if notification_type == "zone_exit" and user.can_exit_zone:
        return {
            "message": "Пользователю разрешён выезд за зону (can_exit_zone=True), уведомление не отправлено",
            "user_id": str(user.id),
            "can_exit_zone": True
        }
    
    translation_key, status_key = notification_map[notification_type]
    
    # Отправляем уведомление
    try:
        asyncio.create_task(
            send_localized_notification_to_user_async(
                user.id,
                translation_key,
                status_key
            )
        )
        return {"message": "Уведомление отправлено", "user_id": str(user.id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка отправки уведомления: {str(e)}")


@Vehicle_Router.post("/track-view/{car_id}", summary="Отслеживание просмотра автомобиля")
async def track_car_view(
    car_id: str,
    user_latitude: float = Query(None, description="Широта пользователя"),
    user_longitude: float = Query(None, description="Долгота пользователя"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Отслеживание просмотра автомобиля пользователем.
    Если пользователь просмотрел автомобиль и вышел (не забронировал), отправляется уведомление.
    """
    car_uuid = safe_sid_to_uuid(car_id)
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    # Проверяем, есть ли активная аренда для этого автомобиля
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.car_id == car_uuid,
        RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
    ).first()
    
    # Фиксируем просмотр для пуш-уведомления
    await _trigger_car_view_notifications(
        db,
        current_user,
        car,
        user_latitude=user_latitude,
        user_longitude=user_longitude
    )
    
    return {"message": "Просмотр отслежен"}


@Vehicle_Router.post("/app-start", summary="Отслеживание входа пользователя в приложение")
async def track_app_start(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Endpoint для отслеживания входа пользователя в приложение.
    Принимает запрос когда пользователь открывает приложение.
    """
    try:
        logger.info(f"User {current_user.id} started the application")
        
        # Обновляем время последней активности пользователя
        from app.utils.time_utils import get_local_time
        current_user.last_activity_at = get_local_time()
        db.add(current_user)
        db.commit()
        
        logger.info(f"App start tracked for user {current_user.id} at {current_user.last_activity_at}")
        
        return {"message": "App start tracked successfully", "user_id": str(current_user.id)}
    except Exception as e:
        logger.error(f"Error tracking app start for user {current_user.id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка отслеживания входа в приложение: {str(e)}")


@Vehicle_Router.post("/app-exit", summary="Отслеживание выхода пользователя из приложения")
async def track_app_exit(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Простой endpoint для отслеживания выхода пользователя из приложения.
    Принимает запрос когда пользователь покидает приложение.
    """
    try:
        logger.info(f"User {current_user.id} exited the application")
        
        # Обновляем время последней активности пользователя
        from app.utils.time_utils import get_local_time
        current_user.last_activity_at = get_local_time()
        db.add(current_user)
        db.commit()
        
        logger.info(f"App exit tracked for user {current_user.id} at {current_user.last_activity_at}")
        
        return {"message": "App exit tracked successfully", "user_id": str(current_user.id)}
    except Exception as e:
        logger.error(f"Error tracking app exit for user {current_user.id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка отслеживания выхода из приложения: {str(e)}")
