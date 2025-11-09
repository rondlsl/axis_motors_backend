from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import or_, and_, func
from sqlalchemy.orm import Session
from typing import Dict, Any, List
import asyncio
import logging

from starlette import status

logger = logging.getLogger(__name__)

from app.core.config import GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD, RENTED_CARS_ENDPOINT_KEY
from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.utils.short_id import uuid_to_sid, safe_sid_to_uuid
from app.gps_api.schemas import RentedCar
from app.models.car_model import Car, CarAutoClass, CarStatus
from app.models.history_model import RentalHistory, RentalStatus
from app.models.rental_actions_model import ActionType, RentalAction
from app.models.user_model import User, UserRole
from app.rent.router import get_user_available_auto_classes
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
def get_vehicle_info(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    try:
        if current_user.role == UserRole.REJECTFIRSTCERT:
            return {"vehicles": []}
        
        if current_user.role == UserRole.REJECTFIRST:
            available_classes = get_user_available_auto_classes(current_user, db)
            if not available_classes:
                return {"vehicles": []}
        
        if current_user.role == UserRole.MECHANIC:
            query = db.query(Car)
        else:
            active_rental = db.query(RentalHistory).filter(
                RentalHistory.user_id == current_user.id,
                RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
            ).first()
            
            if active_rental:
                query = db.query(Car).filter(Car.id == active_rental.car_id)
            else:
                query = db.query(Car).filter(Car.status.in_([CarStatus.FREE, CarStatus.OCCUPIED]))

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
        elif current_user.role == UserRole.REJECTFIRST:
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
                    cars = []
            else:
                cars = []
        else:
            cars = query.all()

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
                "photo_before_selfie_uploaded": photo_before_selfie_uploaded,
                "photo_before_car_uploaded": photo_before_car_uploaded,
                "photo_before_interior_uploaded": photo_before_interior_uploaded,
                "photo_after_selfie_uploaded": photo_after_selfie_uploaded,
                "photo_after_car_uploaded": photo_after_car_uploaded,
                "photo_after_interior_uploaded": photo_after_interior_uploaded
            })

        return {"vehicles": vehicles_data}

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
            cars = db.query(Car).filter(
                or_(
                    Car.name.ilike(f"%{query}%"),
                    Car.plate_number.ilike(f"%{query}%")
                )
            ).all()
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
                cars = db.query(Car).filter(
                    or_(
                        Car.name.ilike(f"%{query}%"),
                        Car.plate_number.ilike(f"%{query}%")
                    ),
                    Car.status.in_([CarStatus.FREE, CarStatus.OCCUPIED])
                ).all()

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
    
    # логируем действие
    action = RentalAction(
        rental_id=rental.id,
        user_id=current_user.id,
        action_type=ActionType.OPEN_VEHICLE
    )
    db.add(action)
    
    try:
        # отправляем команду
        cmd = await send_open(car.gps_imei, AUTH_TOKEN)
        db.commit()
        return cmd
    except Exception as e:
        db.rollback()
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
        action_type=ActionType.CLOSE_VEHICLE
    )
    db.add(action)
    
    try:
        cmd = await send_close(car.gps_imei, AUTH_TOKEN)
        db.commit()
        return cmd
    except Exception as e:
        db.rollback()
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
    
    action = RentalAction(rental_id=rental.id, user_id=current_user.id, action_type=ActionType.GIVE_KEY)
    db.add(action)
    
    try:
        cmd = await send_give_key(car.gps_imei, AUTH_TOKEN)
        db.commit()
        return cmd
    except Exception as e:
        db.rollback()
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
    
    action = RentalAction(rental_id=rental.id, user_id=current_user.id, action_type=ActionType.TAKE_KEY)
    db.add(action)
    
    try:
        cmd = await send_take_key(car.gps_imei, AUTH_TOKEN)
        db.commit()
        return cmd
    except Exception as e:
        db.rollback()
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
    
    action = RentalAction(rental_id=rental.id, user_id=current_user.id, action_type=ActionType.LOCK_ENGINE)
    db.add(action)
    
    try:
        cmd = await send_lock_engine(car.gps_imei, AUTH_TOKEN)
        db.commit()
        return cmd
    except Exception as e:
        db.rollback()
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
    
    action = RentalAction(rental_id=rental.id, user_id=current_user.id, action_type=ActionType.UNLOCK_ENGINE)
    db.add(action)
    
    try:
        cmd = await send_unlock_engine(car.gps_imei, AUTH_TOKEN)
        db.commit()
        return cmd
    except Exception as e:
        db.rollback()
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
    statuses = [RentalStatus.IN_USE, RentalStatus.DELIVERING_IN_PROGRESS]

    rows = (
        db.query(Car.name, Car.plate_number)
        .join(RentalHistory, RentalHistory.car_id == Car.id)
        .filter(RentalHistory.rental_status.in_(statuses))
        .distinct(Car.id)
        .all()
    )

    return [RentedCar(name=name, plate_number=plate) for name, plate in rows]


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
                2: "866011056063951",  # Haval F7x  
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
        
        # Записываем действие в rental_actions если есть активная аренда
        if rental:
            action = RentalAction(
                rental_id=rental.id,
                user_id=current_user.id,
                action_type=ActionType.OPEN_VEHICLE
            )
            db.add(action)
            db.commit()
        
        return {"message": "Команда открытия отправлена", "car_name": car.name, "result": cmd}
    except Exception as e:
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
        
        # Записываем действие в rental_actions если есть активная аренда
        if rental:
            action = RentalAction(
                rental_id=rental.id,
                user_id=current_user.id,
                action_type=ActionType.CLOSE_VEHICLE
            )
            db.add(action)
            db.commit()
        
        return {"message": "Команда закрытия отправлена", "car_name": car.name, "result": cmd}
    except Exception as e:
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
        
        # Записываем действие в rental_actions если есть активная аренда
        if rental:
            action = RentalAction(
                rental_id=rental.id,
                user_id=current_user.id,
                action_type=ActionType.LOCK_ENGINE
            )
            db.add(action)
            db.commit()
        
        return {"message": "Команда блокировки двигателя отправлена", "car_name": car.name, "result": cmd}
    except Exception as e:
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
        
        # Записываем действие в rental_actions если есть активная аренда
        if rental:
            action = RentalAction(
                rental_id=rental.id,
                user_id=current_user.id,
                action_type=ActionType.UNLOCK_ENGINE
            )
            db.add(action)
            db.commit()
        
        return {"message": "Команда разблокировки двигателя отправлена", "car_name": car.name, "result": cmd}
    except Exception as e:
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
        
        # Записываем действие в rental_actions если есть активная аренда
        if rental:
            action = RentalAction(
                rental_id=rental.id,
                user_id=current_user.id,
                action_type=ActionType.GIVE_KEY
            )
            db.add(action)
            db.commit()
        
        return {"message": "Команда выдачи ключа отправлена", "car_name": car.name, "result": cmd}
    except Exception as e:
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
            2: "866011056063951",  # Haval F7x  
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
        
        # Записываем действие в rental_actions если есть активная аренда
        if rental:
            action = RentalAction(
                rental_id=rental.id,
                user_id=current_user.id,
                action_type=ActionType.TAKE_KEY
            )
            db.add(action)
            db.commit()
        
        return {"message": "Команда забора ключа отправлена", "car_name": car.name, "result": cmd}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")




