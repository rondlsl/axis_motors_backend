from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Body, Request
from math import ceil, floor
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy import or_, and_, func
import os
import uuid
from app.utils.short_id import safe_sid_to_uuid, uuid_to_sid
from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.auth.dependencies.save_documents import save_file
from app.models.user_model import User, UserRole
from app.models.car_model import Car, CarStatus, CarBodyType, TransmissionType, CarAutoClass
from app.models.car_comment_model import CarComment
from app.models.history_model import RentalHistory, RentalStatus, RentalReview, RentalType
from app.models.rental_actions_model import RentalAction
from app.models.contract_model import UserContractSignature
from app.models.wallet_transaction_model import WalletTransaction
from app.admin.cars.schemas import (
    CarDetailSchema, CarEditSchema, CarCommentSchema, 
    CarCommentCreateSchema, CarCommentUpdateSchema,
    CarAvailabilityTimerSchema, CarCurrentUserSchema,
    CarListResponseSchema, CarMapResponseSchema, CarStatisticsSchema,
    CarListItemSchema, CarMapItemSchema, OwnerSchema, CurrentRenterSchema,
    CarCreateSchema, CarCreateResponseSchema, CarDeletePhotoSchema,
    DescriptionUpdateSchema,
)
from app.admin.cars.utils import car_to_detail_schema, status_display, _get_drive_type_display, sort_car_photos
from app.gps_api.utils.route_data import get_gps_route_data
from app.gps_api.utils.auth_api import get_auth_token
from app.gps_api.utils.car_data import send_open, send_close, send_give_key, send_take_key, send_lock_engine, send_unlock_engine
from app.gps_api.utils.glonassoft_client import glonassoft_client
from app.gps_api.utils.telemetry_processor import process_glonassoft_data
from app.core.config import GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD
from app.core.logging_config import get_logger

logger = get_logger(__name__)
from app.models.support_action_model import SupportAction
from app.utils.plate_normalizer import normalize_plate_number
from app.utils.telegram_logger import log_error_to_telegram
from app.websocket.notifications import notify_vehicles_list_update, notify_user_status_update
from app.utils.time_utils import get_local_time, parse_datetime_to_local
from app.owner.availability import update_car_availability_snapshot
from app.owner.router import calculate_owner_earnings, calculate_fuel_cost, calculate_delivery_cost
import asyncio
import json
import uuid
import httpx
from app.models.contract_model import UserContractSignature, ContractFile, ContractType
from app.utils.action_logger import log_action

VEHICLE_STATUS_FIELDS = [
    "is_engine_on", "is_ignition_on", "is_hood_open",
    "front_right_door_open", "front_left_door_open", "rear_left_door_open", "rear_right_door_open",
    "front_right_door_locked", "front_left_door_locked", "rear_left_door_locked", "rear_right_door_locked",
    "central_locks_locked",
    "front_left_window_closed", "front_right_window_closed", "rear_left_window_closed", "rear_right_window_closed",
    "is_trunk_open", "is_handbrake_on", "are_lights_on", "is_light_auto_mode_on",
]

from app.core.config import VEHICLES_API_URL
CARS_V2_API_URL = f"{VEHICLES_API_URL}/vehicles"
BASE_URL = "https://regions.glonasssoft.ru"

cars_router = APIRouter(tags=["Admin Cars"])


def get_car_by_id(db: Session, car_id: str) -> Car:
    """Получить автомобиль по id"""
    car_uuid = safe_sid_to_uuid(car_id)
    return db.query(Car).filter(Car.id == car_uuid).first()


def to_utc_for_glonass(dt: datetime) -> str | None:
    """Преобразует время из UTC+5 (хранится в базе) в UTC для отправки в API Глонасса"""
    if dt is None:
        return None
    # Вычитаем 5 часов, чтобы получить UTC время
    utc_time = dt - timedelta(hours=5)
    return utc_time.strftime('%Y-%m-%dT%H:%M:%S.000Z')


@cars_router.patch("/{car_id}", response_model=CarDetailSchema)
async def edit_car(
    car_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Редактировать автомобиль.

    - Не удаляет фотографии. Удаление — только через DELETE /{car_id}/photos/one.
    - Может добавлять новые фото: multipart/form-data с полем «data» (JSON) и «new_photos» (файлы).
      Новые файлы загружаются в MinIO, их URL дописываются в car.photos.
    - Может менять порядок фото: в «data» передать «photos» — массив URL в нужном порядке.

    Если изменяется gps_imei:
    1. Удаляет старую машину из azv_motors_cars_v2 по старому IMEI
    2. Получает данные от Glonass API по новому IMEI
    3. Добавляет машину в azv_motors_cars_v2 с новыми данными
    """
    if current_user.role not in [UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    content_type = request.headers.get("content-type", "")
    new_photos_files: List[UploadFile] = []

    if "multipart/form-data" in content_type:
        form = await request.form()
        data_raw = form.get("data")
        data_dict: dict = {}
        if data_raw is not None:
            try:
                data_dict = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
            except (json.JSONDecodeError, TypeError) as e:
                raise HTTPException(status_code=400, detail=f"Невалидный JSON в «data»: {e}")
        body = CarEditSchema(**data_dict)
        for v in form.getlist("new_photos"):
            if hasattr(v, "read") and hasattr(v, "filename"):
                new_photos_files.append(v)
    else:
        try:
            raw = await request.json()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Ожидается JSON или multipart: {e}")
        body = CarEditSchema(**raw)

    update_fields = body.model_dump(exclude_unset=True)
    logger.info(f"[edit_car] Received update_fields: {list(update_fields.keys())}")
    logger.info(f"[edit_car] Photos in update_fields: {update_fields.get('photos', 'NOT PRESENT')}")

    # Добавление новых фото: загрузка в MinIO и добавление URL в car.photos
    if new_photos_files:
        from app.services.minio_service import get_minio_service
        minio = get_minio_service()
        normalized_plate = normalize_plate_number(car.plate_number) if car.plate_number else str(car.id)
        folder = f"cars/{normalized_plate}"
        saved_urls: List[str] = []
        for f in new_photos_files:
            try:
                url = await minio.upload_file(f, car.id, folder)
                saved_urls.append(url)
            except Exception as e:
                logger.error(f"[edit_car] Ошибка загрузки фото {getattr(f, 'filename', '?')}: {e}")
        if saved_urls:
            base = update_fields.get("photos") if "photos" in update_fields else (car.photos or [])
            update_fields["photos"] = list(base) + saved_urls
            logger.info(f"[edit_car] Загружено в MinIO и добавлено в photos: {len(saved_urls)} файлов")
    
    # Сохраняем старый IMEI для проверки изменений
    old_gps_imei = car.gps_imei
    old_gps_id = car.gps_id
    new_gps_imei = update_fields.get("gps_imei")
    gps_imei_changed = new_gps_imei is not None and new_gps_imei != old_gps_imei
    
    # Обработка owner_id (преобразование из short id в UUID)
    if "owner_id" in update_fields:
        owner_id_value = update_fields.pop("owner_id")
        if owner_id_value:
            owner_uuid = safe_sid_to_uuid(owner_id_value)
            owner = db.query(User).filter(User.id == owner_uuid).first()
            if not owner:
                raise HTTPException(status_code=400, detail=f"Владелец с ID {owner_id_value} не найден")
            update_fields["owner_id"] = owner_uuid
        else:
            update_fields["owner_id"] = None
    
    # Обработка photos: только добавление новых URL и смена порядка. Удаление не выполняем.
    if "photos" in update_fields:
        new_photos = update_fields.pop("photos")
        if new_photos is not None:
            old_photos = car.photos or []
            old_set = set(old_photos)
            added = [u for u in new_photos if u not in old_set]
            reordered = list(old_photos) != new_photos and set(old_photos) == set(new_photos)
            update_fields["photos"] = new_photos
            if added:
                logger.info(f"[edit_car] Добавлены фото: {len(added)}, итого: {len(new_photos)}")
            elif reordered:
                logger.info(f"[edit_car] Изменён порядок фото, итого: {len(new_photos)}")
    
    # Проверяем уникальность нового IMEI
    if gps_imei_changed and new_gps_imei:
        existing_car_by_imei = db.query(Car).filter(
            Car.gps_imei == new_gps_imei,
            Car.id != car.id
        ).first()
        if existing_car_by_imei:
            raise HTTPException(status_code=400, detail=f"Автомобиль с IMEI {new_gps_imei} уже существует")
    
    # Если IMEI изменился, обрабатываем интеграцию с Glonass и azv_motors_cars_v2
    glonass_data_received = False
    vehicle_id = None
    
    if gps_imei_changed:
        # Шаг 1: Удаляем старую машину из azv_motors_cars_v2 по старому IMEI
        if old_gps_imei:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    delete_response = await client.delete(
                        f"{CARS_V2_API_URL}/by-imei/{old_gps_imei}"
                    )
                    if delete_response.status_code == 204:
                        logger.info(f"Удалена старая машина из azv_motors_cars_v2 по IMEI {old_gps_imei}")
                    elif delete_response.status_code == 404:
                        logger.info(f"Машина с IMEI {old_gps_imei} не найдена в azv_motors_cars_v2 (уже удалена или не существовала)")
                    else:
                        logger.warning(f"Не удалось удалить машину из azv_motors_cars_v2: {delete_response.status_code}")
            except Exception as e:
                logger.error(f"Ошибка удаления машины из azv_motors_cars_v2: {e}")
        
        # Шаг 2: Получаем данные от Glonass API по новому IMEI
        if new_gps_imei:
            try:
                auth_token = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
                if auth_token:
                    glonass_response = await glonassoft_client.get_vehicle_data(new_gps_imei)
                    
                    if glonass_response:
                        glonass_data_received = True
                        vehicle_id = str(glonass_response.get("vehicleid"))
                        
                        # Обновляем координаты и данные с Glonass
                        update_fields["gps_id"] = vehicle_id
                        update_fields["latitude"] = glonass_response.get("latitude")
                        update_fields["longitude"] = glonass_response.get("longitude")
                        
                        # Извлекаем данные из RegistredSensors
                        registered_sensors = glonass_response.get("RegistredSensors", [])
                        for sensor in registered_sensors:
                            param_name = sensor.get("parameterName", "")
                            value = sensor.get("value", "")
                            
                            if param_name == "param68":  # Пробег
                                try:
                                    update_fields["mileage"] = int(float(value))
                                except (ValueError, TypeError):
                                    pass
                            
                            if param_name == "param70":  # Уровень топлива
                                try:
                                    fuel_str = value.replace(" l", "").replace(" L", "").strip()
                                    update_fields["fuel_level"] = float(fuel_str)
                                except (ValueError, TypeError):
                                    pass
                        
                        logger.info(f"Получены данные Glonass для нового IMEI {new_gps_imei}: vehicle_id={vehicle_id}")
                else:
                    logger.warning(f"Не удалось получить токен авторизации Glonass для IMEI {new_gps_imei}")
            except Exception as e:
                logger.error(f"Ошибка получения данных Glonass для IMEI {new_gps_imei}: {e}")
        else:
            # Если новый IMEI пустой, сбрасываем gps_id
            update_fields["gps_id"] = None
    
    # Обновляем поля машины
    for field, value in update_fields.items():
        if field == "status" and value is not None:
            setattr(car, "status", value.value if hasattr(value, 'value') else value)
        else:
            setattr(car, field, value)

    db.commit()
    db.refresh(car)
    
    # Шаг 3: Добавляем новую машину в azv_motors_cars_v2 (если IMEI изменился и есть vehicle_id)
    vehicle_added_to_cars_v2 = False
    if gps_imei_changed and new_gps_imei and vehicle_id:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                vehicle_data = {
                    "vehicle_id": int(vehicle_id),
                    "vehicle_imei": new_gps_imei,
                    "name": car.name,
                    "plate_number": car.plate_number
                }
                
                response = await client.post(
                    CARS_V2_API_URL + "/",
                    json=vehicle_data,
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code in [200, 201]:
                    vehicle_added_to_cars_v2 = True
                    logger.info(f"Машина {car.name} добавлена в azv_motors_cars_v2 с новым IMEI {new_gps_imei}")
                else:
                    logger.warning(f"Не удалось добавить машину в azv_motors_cars_v2: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Ошибка добавления машины в azv_motors_cars_v2: {e}")
    
    log_action(
        db,
        actor_id=current_user.id,
        action="edit_car",
        entity_type="car",
        entity_id=car.id,
        details={
            "updated_fields": list(update_fields.keys()), 
            "update_data": str(update_fields),
            "gps_imei_changed": gps_imei_changed,
            "old_gps_imei": old_gps_imei,
            "new_gps_imei": new_gps_imei,
            "glonass_data_received": glonass_data_received,
            "vehicle_added_to_cars_v2": vehicle_added_to_cars_v2
        }
    )
    db.commit()

    return car_to_detail_schema(car, db)


async def get_car_details_response(car_id: str, db: Session) -> CarDetailSchema:
    """Общая логика получения деталей автомобиля (для admin и support)."""
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    update_car_availability_snapshot(car)
    db.flush()
    available_minutes = car.available_minutes or 0

    # Получаем информацию о владельце
    owner_obj = None
    if car.owner_id:
        owner = db.query(User).filter(User.id == car.owner_id).first()
        if owner:
            owner_obj = OwnerSchema(
                owner_id=uuid_to_sid(owner.id),
                first_name=owner.first_name,
                last_name=owner.last_name,
                middle_name=owner.middle_name,
                phone_number=owner.phone_number,
                selfie=owner.selfie_url or owner.selfie_with_license_url
            )
    
    # Получаем информацию о текущем арендаторе
    current_renter_obj = None
    reservation_time_str = None
    if car.current_renter_id:
        renter = db.query(User).filter(User.id == car.current_renter_id).first()
        if renter:
            current_renter_obj = CurrentRenterSchema(
                current_renter_id=uuid_to_sid(renter.id),
                first_name=renter.first_name,
                last_name=renter.last_name,
                middle_name=renter.middle_name,
                phone_number=renter.phone_number,
                role=renter.role.value if renter.role else "client",
                selfie=renter.selfie_url or renter.selfie_with_license_url
            )
            
            # Получаем время бронирования из активной аренды
            active_rental = (
                db.query(RentalHistory)
                .filter(
                    RentalHistory.car_id == car.id,
                    RentalHistory.user_id == renter.id,
                    RentalHistory.rental_status.in_([
                        RentalStatus.RESERVED,
                        RentalStatus.IN_USE,
                        RentalStatus.DELIVERING,
                        RentalStatus.DELIVERING_IN_PROGRESS,
                        RentalStatus.DELIVERY_RESERVED,
                        RentalStatus.SCHEDULED
                    ])
                )
                .order_by(RentalHistory.reservation_time.desc())
                .first()
            )
            if active_rental and active_rental.reservation_time:
                reservation_time_str = active_rental.reservation_time.isoformat()

    vehicle_status = {}
    if car.gps_imei:
        try:
            # Используем короткий timeout (3 сек) и запрашиваем конкретную машину по IMEI
            async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:
                # Используем оптимизированный эндпоинт для одной машины
                single_vehicle_url = f"{CARS_V2_API_URL}/by-imei/{car.gps_imei}"
                response = await client.get(single_vehicle_url)
                if response.status_code == 200:
                    v = response.json()
                    vehicle_status = {field: v.get(field) for field in VEHICLE_STATUS_FIELDS}
        except httpx.TimeoutException:
            # Timeout - продолжаем без данных GPS, не блокируем ответ
            pass
        except Exception:
            pass

    # Обновляем объект из БД, чтобы получить актуальные данные (включая open_fee)
    db.refresh(car)
    return CarDetailSchema(
        id=uuid_to_sid(car.id),
        name=car.name,
        plate_number=car.plate_number,
        engine_volume=car.engine_volume,
        year=car.year,
        drive_type=car.drive_type,
        drive_type_display=_get_drive_type_display(car.drive_type),
        body_type=car.body_type.value if car.body_type else "UNKNOWN",
        body_type_display=car.body_type.value if car.body_type else "Не указан",
        transmission_type=car.transmission_type.value if car.transmission_type else None,
        transmission_type_display=car.transmission_type.value if car.transmission_type else None,
        status=car.status or CarStatus.FREE,
        status_display=status_display(car.status),
        photos=sort_car_photos(car.photos or []),
        description=car.description,
        latitude=car.latitude,
        longitude=car.longitude,
        fuel_level=car.fuel_level,
        mileage=car.mileage,
        course=car.course,
        auto_class=car.auto_class.value if car.auto_class else "UNKNOWN",
        price_per_minute=car.price_per_minute,
        price_per_hour=car.price_per_hour,
        price_per_day=car.price_per_day,
        open_fee=car.open_fee,
        owner_id=uuid_to_sid(car.owner_id) if car.owner_id else None,
        current_renter_id=uuid_to_sid(car.current_renter_id) if car.current_renter_id else None,
        owner=owner_obj,
        current_renter=current_renter_obj,
        available_minutes=available_minutes,
        gps_id=car.gps_id,
        gps_imei=car.gps_imei,
        vehicle_id=car.gps_id,  # Алиас для gps_id
        vehicle_imei=car.gps_imei,  # Алиас для gps_imei
        vin=car.vin,
        color=car.color,
        rating=car.rating,
        reservationtime=reservation_time_str,
        is_engine_on=vehicle_status.get("is_engine_on"),
        is_ignition_on=vehicle_status.get("is_ignition_on"),
        is_hood_open=vehicle_status.get("is_hood_open"),
        front_right_door_open=vehicle_status.get("front_right_door_open"),
        front_left_door_open=vehicle_status.get("front_left_door_open"),
        rear_left_door_open=vehicle_status.get("rear_left_door_open"),
        rear_right_door_open=vehicle_status.get("rear_right_door_open"),
        front_right_door_locked=vehicle_status.get("front_right_door_locked"),
        front_left_door_locked=vehicle_status.get("front_left_door_locked"),
        rear_left_door_locked=vehicle_status.get("rear_left_door_locked"),
        rear_right_door_locked=vehicle_status.get("rear_right_door_locked"),
        central_locks_locked=vehicle_status.get("central_locks_locked"),
        front_left_window_closed=vehicle_status.get("front_left_window_closed"),
        front_right_window_closed=vehicle_status.get("front_right_window_closed"),
        rear_left_window_closed=vehicle_status.get("rear_left_window_closed"),
        rear_right_window_closed=vehicle_status.get("rear_right_window_closed"),
        is_trunk_open=vehicle_status.get("is_trunk_open"),
        is_handbrake_on=vehicle_status.get("is_handbrake_on"),
        are_lights_on=vehicle_status.get("are_lights_on"),
        is_light_auto_mode_on=vehicle_status.get("is_light_auto_mode_on"),
        can_exit_zone=car.can_exit_zone or False,
        notifications_disabled=car.notifications_disabled or False,
    )


@cars_router.get("/{car_id}/details", response_model=CarDetailSchema)
async def get_car_details(
    car_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> CarDetailSchema:
    """Получить детальную информацию об автомобиле"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return await get_car_details_response(car_id, db)


@cars_router.get("", response_model=Dict[str, List[Dict[str, Any]]])
async def get_all_cars_for_admin(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение всех автомобилей для админ панели"""
    
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    cars = db.query(Car).all()
    
    vehicles_data = []
    for car in cars:
        # Определяем статус для отображения
        status_display = {
            "FREE": "Свободно",
            "IN_USE": "В аренде", 
            "SERVICE": "На тех обслуживании",
            "DELIVERING": "Доставляется",
            "DELIVERING_IN_PROGRESS": "Доставлено",
            "DELIVERING": "В доставке",
            "COMPLETED": "Завершено",
            "OWNER": "У владельца"
        }.get(car.status, car.status)
        
        # Получаем данные арендатора если есть
        current_renter_details = None
        if car.current_renter_id:
            renter = db.query(User).filter(User.id == car.current_renter_id).first()
            if renter:
                current_renter_details = {
                    "first_name": renter.first_name,
                    "last_name": renter.last_name,
                    "selfie": renter.selfie_with_license_url
                }
        
        vehicle_data = {
            "id": uuid_to_sid(car.id),
            "name": car.name,
            "status": status_display,
            "lat": car.latitude or 0.0,
            "lng": car.longitude or 0.0,
            "fuel": car.fuel_level or 0,
            "plate": car.plate_number,
            "photos": sort_car_photos(car.photos or []),
            "course": car.course or 0,
            "user": current_renter_details,
            "vin": car.vin,
            "color": car.color,
            "rating": car.rating
        }
        vehicles_data.append(vehicle_data)
    
    return {"cars": vehicles_data}


async def change_car_status_impl(car_id: str, new_status: CarStatus, db: Session, current_user: User):
    """Общая логика изменения статуса автомобиля (для admin и support)."""
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    # Проверяем активные процессы перед изменением статуса на основе текущего статуса
    # 1. Если статус IN_USE (В аренде)
    if car.status == CarStatus.IN_USE:
        active_rental = db.query(RentalHistory).filter(
            RentalHistory.car_id == car.id,
            RentalHistory.rental_status == RentalStatus.IN_USE
        ).first()
        if active_rental:
            raise HTTPException(
                status_code=400,
                detail="Необходимо завершить текущую аренду"
            )
    
    # 2. Если статус RESERVED (Зарезервирован)
    if car.status == CarStatus.RESERVED:
        active_reservation = db.query(RentalHistory).filter(
            RentalHistory.car_id == car.id,
            RentalHistory.rental_status == RentalStatus.RESERVED
        ).first()
        if active_reservation:
            raise HTTPException(
                status_code=400,
                detail="Необходимо отменить бронь"
            )
    
    # 3. Если статус SCHEDULED (Забронирована заранее)
    if car.status == CarStatus.SCHEDULED:
        active_scheduled = db.query(RentalHistory).filter(
            RentalHistory.car_id == car.id,
            RentalHistory.rental_status == RentalStatus.SCHEDULED
        ).first()
        if active_scheduled:
            raise HTTPException(
                status_code=400,
                detail="Необходимо отменить забронированную заранее аренду"
            )
    
    # 4. Если статус DELIVERING (В доставке)
    if car.status == CarStatus.DELIVERING:
        active_delivery = db.query(RentalHistory).filter(
            RentalHistory.car_id == car.id,
            RentalHistory.rental_status.in_([
                RentalStatus.DELIVERING,
                RentalStatus.DELIVERING_IN_PROGRESS
            ])
        ).first()
        if active_delivery:
            raise HTTPException(
                status_code=400,
                detail="Необходимо завершить доставку"
            )
    
    # 5. Если статус SERVICE (У механика)
    if car.status == CarStatus.SERVICE:
        active_inspection = db.query(RentalHistory).filter(
            RentalHistory.car_id == car.id,
            RentalHistory.mechanic_inspector_id.isnot(None),
            RentalHistory.mechanic_inspection_status.isnot(None),
            RentalHistory.mechanic_inspection_status != "COMPLETED",
            RentalHistory.mechanic_inspection_end_time.is_(None)
        ).first()
        if active_inspection:
            raise HTTPException(
                status_code=400,
                detail="Необходимо завершить осмотр"
            )
    
    # 6. Если статус PENDING (Ожидает осмотра)
    if car.status == CarStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail="Необходимо осмотреть машину"
        )
    
    # 7. Если статус OWNER (У владельца)
    if car.status == CarStatus.OWNER:
        raise HTTPException(
            status_code=400,
            detail="Нельзя изменить статус автомобиля у владельца. Необходимо завершить аренду"
        )
    
    # 8. Если статус OCCUPIED (Занята - не отображается)
    if car.status == CarStatus.OCCUPIED:
        # Проверяем наличие активных процессов
        active_process = db.query(RentalHistory).filter(
            RentalHistory.car_id == car.id,
            RentalHistory.rental_status.in_([
                RentalStatus.RESERVED,
                RentalStatus.IN_USE,
                RentalStatus.DELIVERING,
                RentalStatus.DELIVERING_IN_PROGRESS,
                RentalStatus.DELIVERY_RESERVED,
                RentalStatus.SCHEDULED
            ])
        ).first()
        if active_process:
            raise HTTPException(
                status_code=400,
                detail="Необходимо завершить активную аренду перед изменением статуса"
            )
    
    try:
        old_status = car.status
        car.status = new_status
        db.commit()
        # Аудит действий поддержки
        if current_user.role == UserRole.SUPPORT:
            sa = SupportAction(
                user_id=current_user.id,
                action="change_car_status",
                entity_type="car",
                entity_id=car.id
            )
            db.add(sa)
            db.commit()

        log_action(
            db,
            actor_id=current_user.id,
            action="change_car_status",
            entity_type="car",
            entity_id=car.id,
            details={"old_status": old_status.value if old_status else None, "new_status": new_status.value}
        )
        db.commit()
        
        return {
            "message": "Статус автомобиля успешно изменен",
            "car_name": car.name,
            "old_status": old_status.value if old_status else None,
            "new_status": new_status.value
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "admin_change_car_status",
                    "car_id": car_id,
                    "new_status": new_status.value,
                    "admin_id": str(current_user.id)
                }
            )
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Ошибка изменения статуса: {e}")


@cars_router.patch("/{car_id}/status", summary="Изменить статус автомобиля")
async def change_car_status(
    car_id: str,
    new_status: CarStatus,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Изменить статус автомобиля на любой из доступных"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return await change_car_status_impl(car_id, new_status, db, current_user)


@cars_router.get("/{car_id}/status", summary="Получить текущий статус автомобиля")
async def get_car_status(
    car_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Получить текущий статус автомобиля"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Только администраторы или техподдержка могут получать статус автомобилей")
    
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    return {
        "car_id": uuid_to_sid(car.id),
        "car_name": car.name,
        "plate_number": car.plate_number,
        "current_status": car.status.value if car.status else None,
        "available_statuses": [status.value for status in CarStatus]
    }


@cars_router.delete("/{car_id}", summary="Удалить автомобиль")
async def delete_car(
    car_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Удалить автомобиль (необратимая операция)"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Только администраторы или техподдержка могут удалять автомобили")
    
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    try:
        # Проверяем, не используется ли автомобиль в активной аренде
        active_rental = db.query(RentalHistory).filter(
            RentalHistory.car_id == car.id,
            RentalHistory.rental_status.in_([
                RentalStatus.RESERVED,
                RentalStatus.IN_USE,
                RentalStatus.DELIVERING,
                RentalStatus.DELIVERING_IN_PROGRESS,
                RentalStatus.DELIVERY_RESERVED,
                RentalStatus.SCHEDULED
            ])
        ).first()
        
        if active_rental:
            raise HTTPException(
                status_code=400, 
                detail="Нельзя удалить автомобиль, который используется в активной аренде"
            )
        
        car_info = {
            "id": uuid_to_sid(car.id),
            "name": car.name,
            "plate_number": car.plate_number,
            "status": car.status.value if car.status else None
        }

        # Delete related comments
        db.query(CarComment).filter(CarComment.car_id == car.id).delete()
        
        # Delete related rentals cache or similar if needed (skipped here as cascade happens in DB usually or handled below)
        
        db.delete(car)
        
        log_action(
            db,
            actor_id=current_user.id,
            action="delete_car",
            entity_type="car",
            entity_id=car.id, 
            details={"car_info": car_info}
        )
        
        db.commit()
        
        return {"message": "Автомобиль успешно удален", "car": car_info}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "admin_delete_car",
                    "car_id": car_id,
                    "admin_id": str(current_user.id)
                }
            )
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Ошибка удаления автомобиля: {e}")


@cars_router.get("/statuses", summary="Получить список доступных статусов")
async def get_available_statuses(
    current_user: User = Depends(get_current_user)
):
    """Получить список всех доступных статусов автомобилей"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Только администраторы или техподдержка могут получать список статусов")
    
    statuses = []
    for status in CarStatus:
        statuses.append({
            "value": status.value,
            "description": _get_status_description(status)
        })
    
    return {
        "available_statuses": statuses
    }


def _get_status_description(status: CarStatus) -> str:
    """Получить описание статуса на русском языке"""
    descriptions = {
        CarStatus.FREE: "Свободен",
        CarStatus.PENDING: "Ожидает механика", 
        CarStatus.IN_USE: "В аренде",
        CarStatus.DELIVERING: "В доставке",
        CarStatus.SERVICE: "На ремонте",
        CarStatus.RESERVED: "Зарезервирован",
        CarStatus.SCHEDULED: "Забронирован заранее",
        CarStatus.OWNER: "У владельца",
        CarStatus.OCCUPIED: "Занят"
    }
    return descriptions.get(status, status.value)


@cars_router.get("/{car_id}/comments", response_model=List[CarCommentSchema])
async def get_car_comments(
    car_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[CarCommentSchema]:
    """Получить комментарии к автомобилю"""
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    comments = (
        db.query(CarComment)
        .filter(CarComment.car_id == car.id)
        .order_by(CarComment.created_at.desc())
        .all()
    )

    result = []
    for comment in comments:
        result.append(CarCommentSchema(
            id=comment.sid,
            car_id=uuid_to_sid(comment.car_id),
            author_id=comment.author_id,
            author_name=f"{comment.author.first_name or ''} {comment.author.last_name or ''} {comment.author.middle_name or ''}".strip() or comment.author.phone_number,
            author_role=comment.author.role.value,
            comment=comment.comment,
            created_at=comment.created_at.isoformat(),
            is_internal=comment.is_internal
        ))

    return result


@cars_router.post("/{car_id}/comments", response_model=CarCommentSchema)
async def create_car_comment(
    car_id: str,
    comment_data: CarCommentCreateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> CarCommentSchema:
    """Добавить комментарий к автомобилю"""
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    comment = CarComment(
        car_id=car.id,
        author_id=current_user.id,
        comment=comment_data.comment,
        is_internal=comment_data.is_internal
    )

    db.add(comment)
    
    log_action(
        db,
        actor_id=current_user.id,
        action="add_car_comment",
        entity_type="car_comment",
        entity_id=comment.id,
        details={"car_id": car_id, "comment": comment.comment}
    )
    
    db.commit()
    db.refresh(comment)

    # Аудит действий поддержки
    if current_user.role == UserRole.SUPPORT:
        sa = SupportAction(
            user_id=current_user.id,
            action="create_car_comment",
            entity_type="car_comment",
            entity_id=comment.id
        )
        db.add(sa)
        db.commit()

    author_name = f"{current_user.first_name or ''} {current_user.last_name or ''} {current_user.middle_name or ''}".strip()
    if not author_name:
        author_name = current_user.phone_number

    return CarCommentSchema(
        id=comment.sid,
        car_id=uuid_to_sid(comment.car_id),
        author_id=comment.author_id,
        author_name=author_name,
        author_role=current_user.role.value,
        comment=comment.comment,
        created_at=comment.created_at.isoformat(),
        is_internal=comment.is_internal
    )


@cars_router.put("/{car_id}/comments/{comment_id}", response_model=CarCommentSchema)
async def update_car_comment(
    car_id: str,
    comment_id: str,
    comment_data: CarCommentUpdateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> CarCommentSchema:
    """Обновить комментарий к автомобилю"""
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    comment_uuid = safe_sid_to_uuid(comment_id)
    comment = db.query(CarComment).filter(
        CarComment.id == comment_uuid,
        CarComment.car_id == car.id,
        CarComment.author_id == current_user.id  # Только автор может редактировать
    ).first()

    if not comment:
        raise HTTPException(status_code=404, detail="Комментарий не найден")

    comment.comment = comment_data.comment
    comment.updated_at = get_local_time()

    db.commit()
    
    log_action(
        db,
        actor_id=current_user.id,
        action="update_car_comment",
        entity_type="car_comment",
        entity_id=comment.id,
        details={
            "car_id": car_id, 
            "new_comment": comment.comment if comment_data.comment else None
        }
    )
    
    db.commit()
    db.refresh(comment)

    # Аудит действий поддержки
    if current_user.role == UserRole.SUPPORT:
        sa = SupportAction(
            user_id=current_user.id,
            action="update_car_comment",
            entity_type="car_comment",
            entity_id=comment.id
        )
        db.add(sa)
        db.commit()

    author_name = f"{current_user.first_name or ''} {current_user.last_name or ''} {current_user.middle_name or ''}".strip()
    if not author_name:
        author_name = current_user.phone_number

    return CarCommentSchema(
        id=comment.sid,
        car_id=uuid_to_sid(comment.car_id),
        author_id=comment.author_id,
        author_name=author_name,
        author_role=current_user.role.value,
        comment=comment.comment,
        created_at=comment.created_at.isoformat(),
        is_internal=comment.is_internal
    )


@cars_router.delete("/{car_id}/comments/{comment_id}")
async def delete_car_comment(
    car_id: str,
    comment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Удалить комментарий к автомобилю"""
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    comment_uuid = safe_sid_to_uuid(comment_id)
    comment = db.query(CarComment).filter(
        CarComment.id == comment_uuid,
        CarComment.car_id == car.id,
        CarComment.author_id == current_user.id  
    ).first()

    if not comment:
        raise HTTPException(status_code=404, detail="Комментарий не найден")

    db.delete(comment)
    
    log_action(
        db,
        actor_id=current_user.id,
        action="delete_car_comment",
        entity_type="car_comment",
        entity_id=comment_uuid,
        details={"car_id": car_id}
    )
    
    db.commit()

    # Аудит действий поддержки
    if current_user.role == UserRole.SUPPORT:
        sa = SupportAction(
            user_id=current_user.id,
            action="delete_car_comment",
            entity_type="car_comment",
            entity_id=comment_uuid
        )
        db.add(sa)
        db.commit()

    return {"message": "Комментарий удален"}


@cars_router.get("/{car_id}/current-user")
async def get_car_current_user(
    car_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Информация о пользователе автомобиля"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    is_owner_ctx = car.status == CarStatus.OWNER.value and car.owner_id is not None
    is_rented_ctx = car.current_renter_id is not None and car.status in [CarStatus.IN_USE.value, CarStatus.DELIVERING.value, CarStatus.RESERVED.value, CarStatus.SCHEDULED.value]

    if is_owner_ctx:
        owner = db.query(User).filter(User.id == car.owner_id).first()
        return {
            "user_type": "owner",
            "user_info": {
                "id": uuid_to_sid(owner.id) if owner else None,
                "first_name": owner.first_name if owner else None,
                "last_name": owner.last_name if owner else None,
                "phone_number": owner.phone_number if owner else None,
                "selfie_url": owner.selfie_url if owner else None
            }
        }
    elif is_rented_ctx:
        renter = db.query(User).filter(User.id == car.current_renter_id).first()
        return {
            "user_type": "renter",
            "user_info": {
                "id": uuid_to_sid(renter.id) if renter else None,
                "first_name": renter.first_name if renter else None,
                "last_name": renter.last_name if renter else None,
                "phone_number": renter.phone_number if renter else None,
                "selfie_url": renter.selfie_url if renter else None
            }
        }
    else:
        return {"user_type": "none", "user_info": None}


@cars_router.get("/{car_id}/availability-timer", response_model=CarAvailabilityTimerSchema)
async def get_car_availability_timer(
    car_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> CarAvailabilityTimerSchema:
    """Получить таймер доступности автомобиля"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    # Берем значение напрямую из таблицы без пересчета
    available_minutes = car.available_minutes or 0

    last_rental = db.query(RentalHistory).filter(
        RentalHistory.car_id == car.id,
        RentalHistory.rental_status == RentalStatus.COMPLETED,
        RentalHistory.end_time.isnot(None)
    ).order_by(RentalHistory.end_time.desc()).first()

    return CarAvailabilityTimerSchema(
            car_id=uuid_to_sid(car.id),
        available_minutes=available_minutes,
        last_rental_end=last_rental.end_time.isoformat() if last_rental else None,
        current_status=car.status.value if car.status else "FREE"
    )


@cars_router.get("/{car_id}/history/summary")
async def get_car_history_summary(
    car_id: str,
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(12, ge=1, le=60, description="Количество месяцев на странице"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Агрегированные данные по месяцам для автомобиля.
    Возвращает информацию по всем месяцам, в которых были поездки (все статусы).
    """
    from calendar import monthrange
    from collections import defaultdict
    
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    # Получаем все поездки для машины со всеми статусами
    rentals = db.query(RentalHistory).filter(
        RentalHistory.car_id == car.id
    ).all()
    
    print(f"[car_history/summary] car_id={car_id}, total_rentals={len(rentals)}", flush=True)
    
    # Группируем поездки по месяцам
    # owner_income по поездке = int((base_price + overtime_fee + waiting_fee) * 0.5 * 0.97) - вычеты
    monthly_data = defaultdict(lambda: {
        "total_income": 0,
        "owner_earnings": 0,  # сумма int((base_price + overtime_fee + waiting_fee) * 0.5 * 0.97) по поездкам
        "deductions": 0.0,
        "trips_count": 0,
        "_trip_details": []  # для отладки: список (rental_id, base_price, overtime_fee, waiting_fee, owner_part | deductions)
    })
    
    for r in rentals:
        # Используем end_time если есть, иначе start_time, иначе reservation_time
        date_for_grouping = r.end_time or r.start_time or r.reservation_time
        if not date_for_grouping:
            print(f"[car_history/summary] SKIP rental_id={r.id} (no date)", flush=True)
            continue
        month_key = (date_for_grouping.year, date_for_grouping.month)
        monthly_data[month_key]["trips_count"] += 1
        monthly_data[month_key]["total_income"] += int(r.total_price or 0)
        
        base_price = r.base_price or 0
        overtime_fee = r.overtime_fee or 0
        waiting_fee = r.waiting_fee or 0
        
        if r.user_id == car.owner_id:
            fuel_cost = calculate_fuel_cost(r, car, current_user)
            delivery_cost = calculate_delivery_cost(r, car, current_user)
            ded = (fuel_cost or 0) + (delivery_cost or 0)
            monthly_data[month_key]["deductions"] += ded
            monthly_data[month_key]["_trip_details"].append({
                "rental_id": str(r.id),
                "date": str(date_for_grouping),
                "is_owner": True,
                "base_price": base_price,
                "overtime_fee": overtime_fee,
                "waiting_fee": waiting_fee,
                "deductions": ded,
                "total_price": r.total_price,
            })
        else:
            # (base_price + overtime_fee + waiting_fee) * 0.5 * 0.97 — как в calculate_owner_earnings
            base_earnings = base_price + overtime_fee + waiting_fee
            owner_part = int(base_earnings * 0.5 * 0.97)
            monthly_data[month_key]["owner_earnings"] += owner_part
            monthly_data[month_key]["_trip_details"].append({
                "rental_id": str(r.id),
                "date": str(date_for_grouping),
                "is_owner": False,
                "base_price": base_price,
                "overtime_fee": overtime_fee,
                "waiting_fee": waiting_fee,
                "base_earnings_sum": base_earnings,
                "owner_part": owner_part,
                "total_price": r.total_price,
            })
    
    from app.models.car_model import CarAvailabilityHistory
    availability_history = db.query(CarAvailabilityHistory).filter(
        CarAvailabilityHistory.car_id == car.id
    ).all()
    
    availability_by_month = {}
    for ah in availability_history:
        availability_by_month[(ah.year, ah.month)] = ah.available_minutes
    
    now = get_local_time()
    current_month_key = (now.year, now.month)
    
    update_car_availability_snapshot(car)
    db.flush()
    availability_by_month[current_month_key] = car.available_minutes or 0
    
    sorted_months = sorted(monthly_data.keys(), reverse=True)
    total_months = len(sorted_months)
    paginated_months = sorted_months[(page - 1) * limit : page * limit]
    
    months_result = []
    for year, month in paginated_months:
        data = monthly_data[(year, month)]
        # owner_earnings уже = сумма int((base_price + overtime_fee + waiting_fee) * 0.5 * 0.97) по поездкам
        owner_income = data["owner_earnings"] - int(data["deductions"])
        
        # Отладка: итоги по месяцу и поездки
        print(
            f"[car_history/summary] MONTH {year}-{month:02d}: trips={data['trips_count']}, "
            f"total_income={data['total_income']}, owner_earnings={data['owner_earnings']}, "
            f"deductions={int(data['deductions'])}, owner_income={owner_income}",
            flush=True
        )
        for i, t in enumerate(data.get("_trip_details", [])[:10]):
            print(
                f"[car_history/summary]   trip[{i}] rental_id={t.get('rental_id', '')[:8]}... "
                f"base_price={t.get('base_price')} overtime_fee={t.get('overtime_fee')} waiting_fee={t.get('waiting_fee')} "
                f"owner_part={t.get('owner_part')} deductions={t.get('deductions')} total_price={t.get('total_price')}",
                flush=True
            )
        if len(data.get("_trip_details", [])) > 10:
            print(f"[car_history/summary]   ... и ещё {len(data['_trip_details']) - 10} поездок", flush=True)
        
        months_result.append({
            "year": year,
            "month": month,
            "available_minutes": availability_by_month.get((year, month), 0),
            "total_income": data["total_income"],
            "owner_income": owner_income,
            "trips_count": data["trips_count"],
            "is_current_month": (year, month) == current_month_key
        })


    return {
        "car_id": uuid_to_sid(car.id),
        "car_name": car.name,
        "plate_number": car.plate_number,
        "current_month": {
            "year": now.year,
            "month": now.month
        },
        "months": months_result,
        "total": total_months,
        "page": page,
        "limit": limit,
        "pages": ceil(total_months / limit) if limit > 0 else 0
    }



@cars_router.get("/{car_id}/history/trips")
async def get_car_trips_list(
    car_id: str,
    month: int = Query(..., ge=1, le=12, description="Месяц (1-12)"),
    year: int = Query(..., description="Год"),

    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(50, ge=1, le=200, description="Количество элементов на странице"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Список поездок автомобиля за выбранный месяц с пагинацией (все статусы)"""
    from calendar import monthrange
    
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    start_dt = datetime(year, month, 1)
    end_dt = datetime(year, month, monthrange(year, month)[1], 23, 59, 59)

    base_query = (
        db.query(RentalHistory, User)
        .outerjoin(User, User.id == RentalHistory.user_id)  # LEFT JOIN чтобы показать все поездки даже без user
        .filter(
            RentalHistory.car_id == car.id,
            or_(
                and_(RentalHistory.reservation_time >= start_dt, RentalHistory.reservation_time <= end_dt),
                and_(RentalHistory.start_time >= start_dt, RentalHistory.start_time <= end_dt),
                and_(RentalHistory.end_time >= start_dt, RentalHistory.end_time <= end_dt),
            )
        )
        .order_by(RentalHistory.reservation_time.desc())
    )
    

    total = base_query.count()
    
    rentals = base_query.offset((page - 1) * limit).limit(limit).all()

    def get_status_display(status, has_inspection=True, is_mechanic_inspecting=False, inspection_status=None):
        # Если идет осмотр механиком, возвращаем соответствующий статус
        if is_mechanic_inspecting or inspection_status == "IN_USE":
            if inspection_status == "PENDING":
                return "Требует осмотра"
            elif inspection_status == "IN_PROGRESS" or inspection_status == "IN_USE":
                return "Осмотр в процессе"
            else:
                return inspection_status or "Требует осмотра"
        
        status_map = {
            "reserved": "Забронирована",
            "in_use": "В аренде",
            "in_progress": "Осмотр в процессе",
            "completed": "Завершена" if has_inspection else "Требует осмотра",
            "cancelled": "Отменена",
            "delivering": "Доставка",
            "delivering_in_progress": "Доставляется",
            "delivery_reserved": "Доставка забронирована",
            "scheduled": "Запланирована",
            "pending": "Требует осмотра",
            "service": "Осмотр в процессе",
        }
        return status_map.get(status, status)

    items = []
    for r, renter in rentals:
        duration_minutes = 0
        if r.start_time and r.end_time:
            duration_minutes = int((r.end_time - r.start_time).total_seconds() // 60)
        
        tariff_display = ""
        if r.rental_type:
            tariff_value = r.rental_type.value if hasattr(r.rental_type, 'value') else str(r.rental_type)
            if tariff_value == "minutes":
                tariff_display = "Минутный"
            elif tariff_value == "hours":
                tariff_display = "Часовой"
            elif tariff_value == "days":
                tariff_display = "Суточный"
            else:
                tariff_display = tariff_value
        
        rental_status_value = r.rental_status.value if r.rental_status else None
        
        has_inspection = (
            r.mechanic_inspection_status == "COMPLETED" or 
            r.mechanic_inspector_id is not None or
            (r.mechanic_photos_after and len(r.mechanic_photos_after) > 0)
        )
        
        # Проверяем, идет ли осмотр механиком (машина в статусе SERVICE)
        is_mechanic_inspecting = (
            car.status == CarStatus.SERVICE and 
            r.mechanic_inspector_id is not None and
            r.mechanic_inspection_status is not None and
            r.mechanic_inspection_status != "COMPLETED" and
            r.mechanic_inspection_status != "CANCELLED"
        )
        
        # Если статус осмотра "IN_USE", возвращаем статус "in_progress"
        if r.mechanic_inspection_status == "IN_USE":
            display_rental_status = "in_progress"
        # Если идет осмотр механиком, возвращаем статус "in_progress"
        elif is_mechanic_inspecting:
            display_rental_status = "in_progress"
        else:
            display_rental_status = rental_status_value if has_inspection or rental_status_value != "completed" else "pending"
        
        items.append({
            "rental_id": uuid_to_sid(r.id),
            "rental_status": display_rental_status,
            "status_display": get_status_display(display_rental_status, has_inspection, is_mechanic_inspecting, r.mechanic_inspection_status),
            "reservation_time": r.reservation_time.isoformat() if r.reservation_time else None,
            "start_date": r.start_time.isoformat() if r.start_time else None,
            "end_date": r.end_time.isoformat() if r.end_time else None,
            "duration_minutes": duration_minutes,
            "tariff": r.rental_type.value if r.rental_type else None,
            "tariff_display": tariff_display,
            "total_price": r.total_price,
            "owner_earnings": int(((r.base_price or 0) + (r.waiting_fee or 0) + (r.overtime_fee or 0)) * 0.5 * 0.97),
            "base_price_owner": int((r.base_price or 0) * 0.5 * 0.97),
            "waiting_fee_owner": int((r.waiting_fee or 0) * 0.5 * 0.97),
            "overtime_fee_owner": int((r.overtime_fee or 0) * 0.5 * 0.97),
            "renter": {
                "id": uuid_to_sid(renter.id) if renter else None,
                "first_name": renter.first_name if renter else None,
                "last_name": renter.last_name if renter else None,
                "phone_number": renter.phone_number if renter else None,
                "selfie": renter.selfie_url if renter else None,
            } if renter else None
        })


    return {
        "trips": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": ceil(total / limit) if limit > 0 else 0
    }



@cars_router.get("/{car_id}/history/trips/{rental_id}")
async def get_trip_detail(
    car_id: str,
    rental_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Детальная информация о поездке"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    rental_uuid = safe_sid_to_uuid(rental_id)
    car = get_car_by_id(db, car_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid, RentalHistory.car_id == car.id).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Поездка не найдена")
    renter = db.query(User).filter(User.id == rental.user_id).first()

    # Группы фотографий
    photos = {
        "client_before": rental.photos_before or [],
        "client_after": rental.photos_after or [],
        "mechanic_before": rental.mechanic_photos_before or [],
        "mechanic_after": rental.mechanic_photos_after or [],
    }

    review = db.query(RentalReview).filter(RentalReview.rental_id == rental.id).first()

    from app.rent.utils.calculate_price import FUEL_PRICE_PER_LITER, ELECTRIC_FUEL_PRICE_PER_LITER
    
    fuel_fee = 0
    if rental.fuel_before is not None and rental.fuel_after is not None and rental.fuel_after < rental.fuel_before:
        fuel_consumed = ceil(rental.fuel_before) - floor(rental.fuel_after)
        if fuel_consumed > 0:
            fuel_price = ELECTRIC_FUEL_PRICE_PER_LITER if car.body_type == CarBodyType.ELECTRIC else FUEL_PRICE_PER_LITER
            fuel_fee = int(fuel_consumed * fuel_price)
    
    total_price_without_fuel = (
        (rental.base_price or 0) +
        (rental.open_fee or 0) +
        (rental.delivery_fee or 0) +
        (rental.waiting_fee or 0) +
        (rental.overtime_fee or 0) +
        (rental.distance_fee or 0)
    )

    tariff_display = ""
    if rental.rental_type:
        tariff_value = rental.rental_type.value if hasattr(rental.rental_type, 'value') else str(rental.rental_type)
        if tariff_value == "minutes":
            tariff_display = "Минутный"
        elif tariff_value == "hours":
            tariff_display = "Часовой"
        elif tariff_value == "days":
            tariff_display = "Суточный"
        else:
            tariff_display = tariff_value

    has_inspection = (
        rental.mechanic_inspection_status == "COMPLETED" or 
        rental.mechanic_inspector_id is not None or
        (rental.mechanic_photos_after and len(rental.mechanic_photos_after) > 0)
    )
    
    rental_status_value = rental.rental_status.value if rental.rental_status else None
    
    # Проверяем, идет ли осмотр механиком (машина в статусе SERVICE)
    is_mechanic_inspecting = (
        car.status == CarStatus.SERVICE and 
        rental.mechanic_inspector_id is not None and
        rental.mechanic_inspection_status is not None and
        rental.mechanic_inspection_status != "COMPLETED" and
        rental.mechanic_inspection_status != "CANCELLED"
    )
    
    # Если назначен механик, возвращаем статус "service"
    if rental.mechanic_inspector_id is not None:
        display_rental_status = "service"
    # Если статус осмотра "IN_USE", возвращаем статус "in_progress"
    elif rental.mechanic_inspection_status == "IN_USE":
        display_rental_status = "in_progress"
    # Если идет осмотр механиком, возвращаем статус "in_progress"
    elif is_mechanic_inspecting:
        display_rental_status = "in_progress"
    else:
        display_rental_status = rental_status_value if has_inspection or rental_status_value != "completed" else "pending"

    result = {
        "rental_id": uuid_to_sid(rental.id),
        "car_name": car.name,
        "plate_number": car.plate_number,
        "car_status": car.status.value if car.status else None,  # Статус машины (SERVICE, FREE, etc.)
        "reservation_time": rental.reservation_time.isoformat() if rental.reservation_time else None,
        "start_time": rental.start_time.isoformat() if rental.start_time else None,
        "end_time": rental.end_time.isoformat() if rental.end_time else None,
        "duration": rental.duration,  # Длительность аренды в часах/днях
        "duration_minutes": int((rental.end_time - rental.start_time).total_seconds() // 60) if rental.start_time and rental.end_time else 0,
        "already_payed": rental.already_payed,
        "total_price": rental.total_price,
        "total_price_without_fuel": total_price_without_fuel,
        "rental_status": display_rental_status,
        "status_display": (
            "Требует осмотра" if display_rental_status == "pending" 
            else "Осмотр в процессе" if display_rental_status == "in_progress"
            else "На сервисе" if display_rental_status == "service"
            else "Завершена" if display_rental_status == "completed" 
            else display_rental_status
        ),
        "rental_type": rental.rental_type.value,
        "tariff": rental.rental_type.value,
        "tariff_display": tariff_display,
        "base_price": rental.base_price or 0,
        "open_fee": rental.open_fee or 0,
        "delivery_fee": rental.delivery_fee or 0,
        "fuel_fee": fuel_fee,
        "waiting_fee": rental.waiting_fee or 0,
        "overtime_fee": rental.overtime_fee or 0,
        "distance_fee": rental.distance_fee or 0,
        "with_driver": rental.with_driver,
        "driver_fee": rental.driver_fee or 0,
        "rebooking_fee": rental.rebooking_fee or 0,
        
        "base_price_owner": int((rental.base_price or 0) * 0.5 * 0.97),
        "waiting_fee_owner": int((rental.waiting_fee or 0) * 0.5 * 0.97),
        "overtime_fee_owner": int((rental.overtime_fee or 0) * 0.5 * 0.97),
        "total_owner_earnings": int(((rental.base_price or 0) + (rental.waiting_fee or 0) + (rental.overtime_fee or 0)) * 0.5 * 0.97),
        
        "fuel_before": rental.fuel_before,
        "fuel_after": rental.fuel_after,
        "fuel_after_main_tariff": rental.fuel_after_main_tariff,
        "mileage_before": rental.mileage_before,
        "mileage_after": rental.mileage_after,
        
        "renter": {
            "id": uuid_to_sid(renter.id),
            "first_name": renter.first_name,
            "last_name": renter.last_name,
            "phone_number": renter.phone_number,
            "selfie": renter.selfie_url,
            "is_owner": car.owner_id == renter.id if car.owner_id else False,
        },
        "photos": photos,
        "client_rating": review.rating if review else None,
        "client_comment": review.comment if review else None,
        "mechanic_rating": review.mechanic_rating if review else None,
        "mechanic_comment": review.mechanic_comment if review else None,
        "rating": rental.rating,
        "delivery_route": {
            "start_latitude": rental.delivery_start_latitude,
            "start_longitude": rental.delivery_start_longitude,
            "end_latitude": rental.delivery_end_latitude,
            "end_longitude": rental.delivery_end_longitude,
        },
        "mechanic_inspection_route": {
            "start_latitude": rental.mechanic_inspection_start_latitude,
            "start_longitude": rental.mechanic_inspection_start_longitude,
            "end_latitude": rental.mechanic_inspection_end_latitude,
            "end_longitude": rental.mechanic_inspection_end_longitude,
        },
    }

    if rental.mechanic_inspector_id:
        mechanic_inspector = db.query(User).filter(User.id == rental.mechanic_inspector_id).first()
        result["mechanic_inspector"] = {
            "id": uuid_to_sid(mechanic_inspector.id) if mechanic_inspector else None,
            "first_name": mechanic_inspector.first_name if mechanic_inspector else None,
            "last_name": mechanic_inspector.last_name if mechanic_inspector else None,
            "phone_number": mechanic_inspector.phone_number if mechanic_inspector else None,
            "selfie": mechanic_inspector.selfie_url if mechanic_inspector else None,
        }
    else:
        result["mechanic_inspector"] = None
    
    if rental.delivery_mechanic_id:
        delivery_mechanic = db.query(User).filter(User.id == rental.delivery_mechanic_id).first()
        result["delivery_mechanic"] = {
            "id": uuid_to_sid(delivery_mechanic.id) if delivery_mechanic else None,
            "first_name": delivery_mechanic.first_name if delivery_mechanic else None,
            "last_name": delivery_mechanic.last_name if delivery_mechanic else None,
            "phone_number": delivery_mechanic.phone_number if delivery_mechanic else None,
            "selfie": delivery_mechanic.selfie_url if delivery_mechanic else None,
        }
    else:
        result["delivery_mechanic"] = None
    
    result["mechanic_inspection"] = {
        "status": rental.mechanic_inspection_status,
        "status_display": {
            "PENDING": "Ожидает осмотра",
            "IN_PROGRESS": "Осмотр в процессе",
            "IN_USE": "Осмотр в процессе",
            "COMPLETED": "Осмотр завершён",
            "CANCELLED": "Осмотр отменён",
        }.get(rental.mechanic_inspection_status, rental.mechanic_inspection_status),
        "start_time": rental.mechanic_inspection_start_time.isoformat() if rental.mechanic_inspection_start_time else None,
        "end_time": rental.mechanic_inspection_end_time.isoformat() if rental.mechanic_inspection_end_time else None,
        "comment": rental.mechanic_inspection_comment,
        "photos_before": rental.mechanic_photos_before or [],
        "photos_after": rental.mechanic_photos_after or [],
    }

    has_delivery = (
        rental.delivery_start_time is not None or 
        rental.delivery_end_time is not None or 
        rental.delivery_mechanic_id is not None or
        (rental.delivery_photos_before and len(rental.delivery_photos_before) > 0) or
        (rental.delivery_photos_after and len(rental.delivery_photos_after) > 0)
    )
    
    if has_delivery:
        result["reservation_time"] = rental.reservation_time.isoformat() if rental.reservation_time else None
        result["delivery_start_time"] = rental.delivery_start_time.isoformat() if rental.delivery_start_time else None
        result["delivery_end_time"] = rental.delivery_end_time.isoformat() if rental.delivery_end_time else None
        result["delivery_photos_before"] = rental.delivery_photos_before or []
        result["delivery_photos_after"] = rental.delivery_photos_after or []
    
    signed_contracts = db.query(UserContractSignature).join(ContractFile).filter(
        UserContractSignature.rental_id == rental.id
    ).all()
    
    signed_types = set()
    for sig in signed_contracts:
        if sig.contract_file:
            signed_types.add(sig.contract_file.contract_type)
    
    result["contracts"] = {
        "main_contract": ContractType.RENTAL_MAIN_CONTRACT in signed_types or ContractType.MAIN_CONTRACT in signed_types,
        "appendix_7_1": ContractType.APPENDIX_7_1 in signed_types,
        "appendix_7_2": ContractType.APPENDIX_7_2 in signed_types,
    }
    
    mechanic_signed_types = set()
    if rental.mechanic_inspector_id:
        mechanic_contracts = db.query(UserContractSignature).join(ContractFile).filter(
            UserContractSignature.rental_id == rental.id,
            UserContractSignature.user_id == rental.mechanic_inspector_id
        ).all()
        for sig in mechanic_contracts:
            if sig.contract_file:
                mechanic_signed_types.add(sig.contract_file.contract_type)
    
    result["mechanic_contracts"] = {
        "main_contract": ContractType.RENTAL_MAIN_CONTRACT in mechanic_signed_types or ContractType.MAIN_CONTRACT in mechanic_signed_types,
        "appendix_7_1": ContractType.APPENDIX_7_1 in mechanic_signed_types,
        "appendix_7_2": ContractType.APPENDIX_7_2 in mechanic_signed_types,
    }
    
    photos_before = rental.photos_before or []
    photos_after = rental.photos_after or []
    
    has_car_before = any("car" in p.lower() for p in photos_before) if photos_before else False
    has_interior_before = any("interior" in p.lower() or "salon" in p.lower() for p in photos_before) if photos_before else False
    has_car_after = any("car" in p.lower() for p in photos_after) if photos_after else False
    has_interior_after = any("interior" in p.lower() or "salon" in p.lower() for p in photos_after) if photos_after else False
    
    result["photo_status"] = {
        "photo_before_car": has_car_before,
        "photo_before_interior": has_interior_before,
        "photo_after_car": has_car_after,
        "photo_after_interior": has_interior_after,
    }
    
    mechanic_photos_before = rental.mechanic_photos_before or []
    mechanic_photos_after = rental.mechanic_photos_after or []
    
    mechanic_has_car_before = any("car" in p.lower() for p in mechanic_photos_before) if mechanic_photos_before else False
    mechanic_has_interior_before = any("interior" in p.lower() or "salon" in p.lower() for p in mechanic_photos_before) if mechanic_photos_before else False
    mechanic_has_car_after = any("car" in p.lower() for p in mechanic_photos_after) if mechanic_photos_after else False
    mechanic_has_interior_after = any("interior" in p.lower() or "salon" in p.lower() for p in mechanic_photos_after) if mechanic_photos_after else False
    
    result["mechanic_photo_status"] = {
        "photo_before_car": mechanic_has_car_before,
        "photo_before_interior": mechanic_has_interior_before,
        "photo_after_car": mechanic_has_car_after,
        "photo_after_interior": mechanic_has_interior_after,
    }

    return result


@cars_router.patch("/{car_id}/history/trips/{rental_id}/time", summary="Исправить время аренды")
async def update_rental_time(
    car_id: str,
    rental_id: str,
    reservation_time: Optional[str] = Query(None, description="Время бронирования (ISO format)"),
    start_time: Optional[str] = Query(None, description="Время начала (ISO format)"),
    end_time: Optional[str] = Query(None, description="Время окончания (ISO format)"),
    duration: Optional[int] = Query(None, description="Длительность аренды в минутах"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Исправить время аренды (reservation_time, start_time, end_time, duration) с логированием в БД"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    rental_uuid = safe_sid_to_uuid(rental_id)
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    rental = db.query(RentalHistory).filter(
        RentalHistory.id == rental_uuid,
        RentalHistory.car_id == car.id
    ).first()
    
    if not rental:
        raise HTTPException(status_code=404, detail="Поездка не найдена")
    
    # Сохраняем старые значения для логирования
    old_values = {
        "reservation_time": rental.reservation_time.isoformat() if rental.reservation_time else None,
        "start_time": rental.start_time.isoformat() if rental.start_time else None,
        "end_time": rental.end_time.isoformat() if rental.end_time else None,
        "duration": rental.duration
    }
    
    # Обновляем поля
    changes = {}
    
    if reservation_time is not None:
        try:
            new_reservation_time = parse_datetime_to_local(reservation_time)
            if (rental.reservation_time is None and new_reservation_time is not None) or \
               (rental.reservation_time is not None and new_reservation_time != rental.reservation_time):
                changes["reservation_time"] = {
                    "old": old_values["reservation_time"],
                    "new": new_reservation_time.isoformat()
                }
                rental.reservation_time = new_reservation_time
        except (ValueError, Exception) as e:
            raise HTTPException(status_code=400, detail=f"Неверный формат reservation_time (ожидается ISO format): {str(e)}")
    
    if start_time is not None:
        try:
            new_start_time = parse_datetime_to_local(start_time)
            if (rental.start_time is None and new_start_time is not None) or \
               (rental.start_time is not None and new_start_time != rental.start_time):
                changes["start_time"] = {
                    "old": old_values["start_time"],
                    "new": new_start_time.isoformat()
                }
                rental.start_time = new_start_time
        except (ValueError, Exception) as e:
            raise HTTPException(status_code=400, detail=f"Неверный формат start_time (ожидается ISO format): {str(e)}")
    
    if end_time is not None:
        try:
            new_end_time = parse_datetime_to_local(end_time)
            if (rental.end_time is None and new_end_time is not None) or \
               (rental.end_time is not None and new_end_time != rental.end_time):
                changes["end_time"] = {
                    "old": old_values["end_time"],
                    "new": new_end_time.isoformat()
                }
                rental.end_time = new_end_time
        except (ValueError, Exception) as e:
            raise HTTPException(status_code=400, detail=f"Неверный формат end_time (ожидается ISO format): {str(e)}")
    
    if duration is not None:
        if rental.duration != duration:
            changes["duration"] = {
                "old": old_values["duration"],
                "new": duration
            }
            rental.duration = duration
    
    if not changes:
        raise HTTPException(status_code=400, detail="Не было указано ни одного поля для обновления")
    
    # Логируем изменения
    log_action(
        db,
        actor_id=current_user.id,
        action="update_rental_time",
        entity_type="rental",
        entity_id=rental.id,
        details={
            "rental_id": rental_id,
            "car_id": car_id,
            "car_name": car.name,
            "changes": changes,
            "updated_by": {
                "user_id": uuid_to_sid(current_user.id),
                "user_name": f"{current_user.first_name or ''} {current_user.last_name or ''}".strip() or current_user.phone_number,
                "role": current_user.role.value
            }
        }
    )
    
    db.commit()
    db.refresh(rental)
    
    return {
        "message": "Время аренды успешно обновлено",
        "rental_id": rental_id,
        "car_id": car_id,
        "car_name": car.name,
        "changes": changes,
        "updated_by": {
            "user_id": uuid_to_sid(current_user.id),
            "user_name": f"{current_user.first_name or ''} {current_user.last_name or ''}".strip() or current_user.phone_number,
            "role": current_user.role.value
        },
        "current_values": {
            "reservation_time": rental.reservation_time.isoformat() if rental.reservation_time else None,
            "start_time": rental.start_time.isoformat() if rental.start_time else None,
            "end_time": rental.end_time.isoformat() if rental.end_time else None,
            "duration": rental.duration
        }
    }


@cars_router.patch("/{car_id}/history/trips/{rental_id}/price", summary="Исправить сумму аренды")
async def update_rental_price(
    car_id: str,
    rental_id: str,
    base_price: Optional[int] = Query(None, description="Базовая цена"),
    open_fee: Optional[int] = Query(None, description="Плата за открытие"),
    delivery_fee: Optional[int] = Query(None, description="Плата за доставку"),
    waiting_fee: Optional[int] = Query(None, description="Плата за ожидание"),
    overtime_fee: Optional[int] = Query(None, description="Плата за перерасход времени"),
    distance_fee: Optional[int] = Query(None, description="Плата за расстояние"),
    driver_fee: Optional[int] = Query(None, description="Плата за водителя"),
    rebooking_fee: Optional[int] = Query(None, description="Плата за повторное бронирование"),
    already_payed: Optional[int] = Query(None, description="Уже оплачено"),
    total_price: Optional[int] = Query(None, description="Общая сумма"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Исправить сумму аренды (base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee, driver_fee, rebooking_fee, already_payed, total_price) с логированием в БД"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    rental_uuid = safe_sid_to_uuid(rental_id)
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    rental = db.query(RentalHistory).filter(
        RentalHistory.id == rental_uuid,
        RentalHistory.car_id == car.id
    ).first()
    
    if not rental:
        raise HTTPException(status_code=404, detail="Поездка не найдена")
    
    # Сохраняем старые значения для логирования
    old_values = {
        "base_price": rental.base_price,
        "open_fee": rental.open_fee,
        "delivery_fee": rental.delivery_fee,
        "waiting_fee": rental.waiting_fee,
        "overtime_fee": rental.overtime_fee,
        "distance_fee": rental.distance_fee,
        "driver_fee": rental.driver_fee,
        "rebooking_fee": rental.rebooking_fee,
        "already_payed": rental.already_payed,
        "total_price": rental.total_price
    }
    
    # Обновляем поля
    changes = {}
    
    if base_price is not None:
        if rental.base_price != base_price:
            changes["base_price"] = {
                "old": old_values["base_price"],
                "new": base_price
            }
            rental.base_price = base_price
    
    if open_fee is not None:
        if rental.open_fee != open_fee:
            changes["open_fee"] = {
                "old": old_values["open_fee"],
                "new": open_fee
            }
            rental.open_fee = open_fee
    
    if delivery_fee is not None:
        if rental.delivery_fee != delivery_fee:
            changes["delivery_fee"] = {
                "old": old_values["delivery_fee"],
                "new": delivery_fee
            }
            rental.delivery_fee = delivery_fee
    
    if waiting_fee is not None:
        if rental.waiting_fee != waiting_fee:
            changes["waiting_fee"] = {
                "old": old_values["waiting_fee"],
                "new": waiting_fee
            }
            rental.waiting_fee = waiting_fee
    
    if overtime_fee is not None:
        if rental.overtime_fee != overtime_fee:
            changes["overtime_fee"] = {
                "old": old_values["overtime_fee"],
                "new": overtime_fee
            }
            rental.overtime_fee = overtime_fee
    
    if distance_fee is not None:
        if rental.distance_fee != distance_fee:
            changes["distance_fee"] = {
                "old": old_values["distance_fee"],
                "new": distance_fee
            }
            rental.distance_fee = distance_fee
    
    if driver_fee is not None:
        if rental.driver_fee != driver_fee:
            changes["driver_fee"] = {
                "old": old_values["driver_fee"],
                "new": driver_fee
            }
            rental.driver_fee = driver_fee
    
    if rebooking_fee is not None:
        if rental.rebooking_fee != rebooking_fee:
            changes["rebooking_fee"] = {
                "old": old_values["rebooking_fee"],
                "new": rebooking_fee
            }
            rental.rebooking_fee = rebooking_fee
    
    if already_payed is not None:
        if rental.already_payed != already_payed:
            changes["already_payed"] = {
                "old": old_values["already_payed"],
                "new": already_payed
            }
            rental.already_payed = already_payed
    
    if total_price is not None:
        if rental.total_price != total_price:
            changes["total_price"] = {
                "old": old_values["total_price"],
                "new": total_price
            }
            rental.total_price = total_price
    
    if not changes:
        raise HTTPException(status_code=400, detail="Не было указано ни одного поля для обновления")
    
    # Логируем изменения
    log_action(
        db,
        actor_id=current_user.id,
        action="update_rental_price",
        entity_type="rental",
        entity_id=rental.id,
        details={
            "rental_id": rental_id,
            "car_id": car_id,
            "car_name": car.name,
            "changes": changes,
            "updated_by": {
                "user_id": uuid_to_sid(current_user.id),
                "user_name": f"{current_user.first_name or ''} {current_user.last_name or ''}".strip() or current_user.phone_number,
                "role": current_user.role.value
            }
        }
    )
    
    db.commit()
    db.refresh(rental)
    
    # Вычисляем total_price_without_fuel для ответа
    total_price_without_fuel = (
        (rental.base_price or 0) +
        (rental.open_fee or 0) +
        (rental.delivery_fee or 0) +
        (rental.waiting_fee or 0) +
        (rental.overtime_fee or 0) +
        (rental.distance_fee or 0) +
        (rental.driver_fee or 0) +
        (rental.rebooking_fee or 0)
    )
    
    return {
        "message": "Сумма аренды успешно обновлена",
        "rental_id": rental_id,
        "car_id": car_id,
        "car_name": car.name,
        "changes": changes,
        "updated_by": {
            "user_id": uuid_to_sid(current_user.id),
            "user_name": f"{current_user.first_name or ''} {current_user.last_name or ''}".strip() or current_user.phone_number,
            "role": current_user.role.value
        },
        "current_values": {
            "base_price": rental.base_price,
            "open_fee": rental.open_fee,
            "delivery_fee": rental.delivery_fee,
            "waiting_fee": rental.waiting_fee,
            "overtime_fee": rental.overtime_fee,
            "distance_fee": rental.distance_fee,
            "driver_fee": rental.driver_fee,
            "rebooking_fee": rental.rebooking_fee,
            "already_payed": rental.already_payed,
            "total_price": rental.total_price,
            "total_price_without_fuel": total_price_without_fuel
        }
    }


@cars_router.patch("/{car_id}/history/trips/{rental_id}/fuel", summary="Исправить топливо аренды")
async def update_rental_fuel(
    car_id: str,
    rental_id: str,
    fuel_before: Optional[float] = Query(None, description="Топливо до аренды"),
    fuel_after: Optional[float] = Query(None, description="Топливо после аренды"),
    fuel_after_main_tariff: Optional[float] = Query(None, description="Топливо после основного тарифа (только для почасового/посуточного)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Исправить топливо аренды с логированием в БД.
    
    Для поминутного тарифа (MINUTES): доступны только fuel_before и fuel_after (2 атрибута).
    Для почасового/посуточного тарифа (HOURS/DAYS): доступны fuel_before, fuel_after и fuel_after_main_tariff (3 атрибута).
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    rental_uuid = safe_sid_to_uuid(rental_id)
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    rental = db.query(RentalHistory).filter(
        RentalHistory.id == rental_uuid,
        RentalHistory.car_id == car.id
    ).first()
    
    if not rental:
        raise HTTPException(status_code=404, detail="Поездка не найдена")
    
    # Проверяем тип аренды и валидируем параметры
    is_minute_rental = rental.rental_type == RentalType.MINUTES
    is_hourly_or_daily = rental.rental_type in (RentalType.HOURS, RentalType.DAYS)
    
    # Для поминутного тарифа не должно быть fuel_after_main_tariff
    if is_minute_rental and fuel_after_main_tariff is not None:
        raise HTTPException(
            status_code=400, 
            detail="Для поминутного тарифа параметр fuel_after_main_tariff не используется. Используйте только fuel_before и fuel_after."
        )
    
    # Для почасового/посуточного тарифа можно использовать все три параметра
    if not is_hourly_or_daily and not is_minute_rental:
        raise HTTPException(
            status_code=400,
            detail=f"Неизвестный тип аренды: {rental.rental_type}"
        )
    
    # Сохраняем старые значения для логирования
    old_values = {
        "fuel_before": rental.fuel_before,
        "fuel_after": rental.fuel_after,
        "fuel_after_main_tariff": rental.fuel_after_main_tariff
    }
    
    # Обновляем поля
    changes = {}
    
    if fuel_before is not None:
        # Проверяем, что значение изменилось (с учетом возможного None)
        if (rental.fuel_before is None and fuel_before is not None) or \
           (rental.fuel_before is not None and fuel_before is not None and abs(rental.fuel_before - fuel_before) > 0.001):
            changes["fuel_before"] = {
                "old": old_values["fuel_before"],
                "new": fuel_before
            }
            rental.fuel_before = fuel_before
    
    if fuel_after is not None:
        # Проверяем, что значение изменилось (с учетом возможного None)
        if (rental.fuel_after is None and fuel_after is not None) or \
           (rental.fuel_after is not None and fuel_after is not None and abs(rental.fuel_after - fuel_after) > 0.001):
            changes["fuel_after"] = {
                "old": old_values["fuel_after"],
                "new": fuel_after
            }
            rental.fuel_after = fuel_after
    
    if fuel_after_main_tariff is not None:
        # Этот параметр доступен только для почасового/посуточного тарифа
        if is_minute_rental:
            raise HTTPException(
                status_code=400,
                detail="Параметр fuel_after_main_tariff доступен только для почасового/посуточного тарифа"
            )
        
        # Проверяем, что значение изменилось (с учетом возможного None)
        if (rental.fuel_after_main_tariff is None and fuel_after_main_tariff is not None) or \
           (rental.fuel_after_main_tariff is not None and fuel_after_main_tariff is not None and abs(rental.fuel_after_main_tariff - fuel_after_main_tariff) > 0.001):
            changes["fuel_after_main_tariff"] = {
                "old": old_values["fuel_after_main_tariff"],
                "new": fuel_after_main_tariff
            }
            rental.fuel_after_main_tariff = fuel_after_main_tariff
    
    if not changes:
        raise HTTPException(status_code=400, detail="Не было указано ни одного поля для обновления или значения не изменились")
    
    # Логируем изменения
    log_action(
        db,
        actor_id=current_user.id,
        action="update_rental_fuel",
        entity_type="rental",
        entity_id=rental.id,
        details={
            "rental_id": rental_id,
            "car_id": car_id,
            "car_name": car.name,
            "rental_type": rental.rental_type.value,
            "changes": changes,
            "updated_by": {
                "user_id": uuid_to_sid(current_user.id),
                "user_name": f"{current_user.first_name or ''} {current_user.last_name or ''}".strip() or current_user.phone_number,
                "role": current_user.role.value
            }
        }
    )
    
    db.commit()
    db.refresh(rental)
    
    # Формируем ответ в зависимости от типа аренды
    current_values = {
        "fuel_before": rental.fuel_before,
        "fuel_after": rental.fuel_after
    }
    
    if is_hourly_or_daily:
        current_values["fuel_after_main_tariff"] = rental.fuel_after_main_tariff
    
    return {
        "message": "Топливо аренды успешно обновлено",
        "rental_id": rental_id,
        "car_id": car_id,
        "car_name": car.name,
        "rental_type": rental.rental_type.value,
        "changes": changes,
        "updated_by": {
            "user_id": uuid_to_sid(current_user.id),
            "user_name": f"{current_user.first_name or ''} {current_user.last_name or ''}".strip() or current_user.phone_number,
            "role": current_user.role.value
        },
        "current_values": current_values
    }


@cars_router.get("/{car_id}/history/trips/{rental_id}/get_maps")
async def get_trip_maps(
    car_id: str,
    rental_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение координат маршрута поездки для отображения на карте"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    rental_uuid = safe_sid_to_uuid(rental_id)
    car = get_car_by_id(db, car_id)
    rental = db.query(RentalHistory).filter(
        RentalHistory.id == rental_uuid,
        RentalHistory.car_id == car.id
    ).first()

    if not rental:
        raise HTTPException(status_code=404, detail="Поездка не найдена")

    route_data = None
    try:
        if car.gps_id and rental.start_time and rental.end_time:
            route = await get_gps_route_data(
                device_id=car.gps_id,
                start_date=rental.start_time.isoformat(),
                end_date=rental.end_time.isoformat()
            )
            route_data = route.dict() if route else None
    except Exception:
        route_data = None

    return {
        "start_latitude": rental.start_latitude,
        "start_longitude": rental.start_longitude,
        "end_latitude": rental.end_latitude,
        "end_longitude": rental.end_longitude,
        "route_data": route_data
    }


@cars_router.get("/map", response_model=CarMapResponseSchema)
async def get_cars_map(
    status: Optional[CarStatus] = None,
    search_query: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> CarMapResponseSchema:
    """Карта автопарка: вернуть все машины с координатами и статусами"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    base_query = db.query(Car)

    if status is not None:
        base_query = base_query.filter(Car.status == status.value)
    else:
        # По умолчанию исключаем занятые и забронированные машины
        base_query = base_query.filter(Car.status.notin_([CarStatus.OCCUPIED, CarStatus.SCHEDULED]))

    if search_query:
        like = f"%{search_query}%"
        base_query = base_query.filter(or_(Car.plate_number.ilike(like), Car.name.ilike(like)))

    cars = base_query.all()

    def _status_display(s: Optional[str]) -> str:
        return {
            "FREE": "Свободно",
            "PENDING": "Ожидает механика",
            "IN_USE": "В аренде",
            "SERVICE": "На тех обслуживании",
            "DELIVERING": "В доставке",
            "DELIVERING_IN_PROGRESS": "Доставлено",
            "DELIVERING": "В доставке",
            "COMPLETED": "Завершено",
            "SERVICE": "На обслуживании",
            "RESERVED": "Зарезервирована",
            "SCHEDULED": "Забронирована заранее",
            "OWNER": "У владельца",
            "OCCUPIED": "Занята",
        }.get(s or "", s or "")

    items: List[CarMapItemSchema] = []
    for car in cars:
        renter_info = None
        if car.current_renter_id:
            renter = db.query(User).filter(User.id == car.current_renter_id).first()
            if renter:
                renter_info = {
                    "first_name": renter.first_name,
                    "last_name": renter.last_name,
                    "selfie": renter.selfie_with_license_url,
                }
        items.append(CarMapItemSchema(
            id=uuid_to_sid(car.id),
            name=car.name,
            plate_number=car.plate_number,
            status=car.status,
            status_display=_status_display(car.status),
            latitude=car.latitude,
            longitude=car.longitude,
            fuel_level=car.fuel_level,
            course=car.course,
            photos=sort_car_photos(car.photos or []),
            current_renter=renter_info,
            vin=car.vin,
            color=car.color,
        ))

    return CarMapResponseSchema(cars=items, total_count=len(items))


@cars_router.get("/list", response_model=CarListResponseSchema)
async def get_cars_list(
    status: Optional[CarStatus] = None,
    search_query: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> CarListResponseSchema:
    """Список автомобилей с фильтрами/поиском для боковой панели"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    total_count = db.query(Car).count()

    query = db.query(Car)
    if status is not None:
        query = query.filter(Car.status == status.value)
    if search_query:
        like = f"%{search_query}%"
        query = query.filter(or_(Car.plate_number.ilike(like), Car.name.ilike(like)))

    filtered_cars = query.all()

    def _status_display(s: Optional[str]) -> str:
        return {
            "FREE": "Свободно",
            "PENDING": "Ожидает механика",
            "IN_USE": "В аренде",
            "SERVICE": "На тех обслуживании",
            "DELIVERING": "В доставке",
            "DELIVERY_RESERVED": "Доставка зарезервирована",
            "DELIVERING_IN_PROGRESS": "Доставлено",
            "COMPLETED": "Завершено",
            "RESERVED": "Зарезервирована",
            "SCHEDULED": "Забронирована заранее",
            "OWNER": "У владельца",
            "OCCUPIED": "Занята",
        }.get(s or "", s or "")

    items: List[CarListItemSchema] = []
    for car in filtered_cars:
        owner_obj = None
        if car.owner_id:
            owner = db.query(User).filter(User.id == car.owner_id).first()
            if owner:
                owner_obj = OwnerSchema(
                    owner_id=uuid_to_sid(owner.id),
                    first_name=owner.first_name,
                    last_name=owner.last_name,
                    middle_name=owner.middle_name,
                    phone_number=owner.phone_number,
                    selfie=owner.selfie_url or owner.selfie_with_license_url
                )
        
        current_renter_obj = None
        if car.current_renter_id:
            renter = db.query(User).filter(User.id == car.current_renter_id).first()
            if renter:
                current_renter_obj = CurrentRenterSchema(
                    current_renter_id=uuid_to_sid(renter.id),
                    first_name=renter.first_name,
                    last_name=renter.last_name,
                    middle_name=renter.middle_name,
                    phone_number=renter.phone_number,
                    role=renter.role.value if renter.role else "client",
                    selfie=renter.selfie_url or renter.selfie_with_license_url
                )

        car_status = car.status.value if isinstance(car.status, CarStatus) else str(car.status)
        
        if car.status == CarStatus.DELIVERING:
            car_status = "DELIVERY_RESERVED"
            
        if current_renter_obj and current_renter_obj.role == "mechanic":
            car_status = "SERVICE"
        
        has_gps = car.gps_id is not None and car.gps_id.strip() != ""
        latitude = -1.0 if not has_gps else car.latitude
        longitude = -1.0 if not has_gps else car.longitude

        items.append(CarListItemSchema(
            id=uuid_to_sid(car.id),
            name=car.name,
            plate_number=car.plate_number,
            status=car_status,
            status_display=_status_display(car_status),
            latitude=latitude,
            longitude=longitude,
            fuel_level=car.fuel_level,
            mileage=car.mileage,
            speed=car.speed if hasattr(car, 'speed') else None,
            auto_class=car.auto_class.value if car.auto_class else "",
            body_type=car.body_type.value if car.body_type else "",
            year=car.year,
            owner=owner_obj,
            current_renter=current_renter_obj,
            photos=sort_car_photos(car.photos or []),
            vin=car.vin,
            color=car.color,
            rating=car.rating,
        ))

    return CarListResponseSchema(
        cars=items,
        total_count=total_count,
        filtered_count=len(items),
    )


@cars_router.get("/statistics", response_model=CarStatisticsSchema)
async def get_cars_statistics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> CarStatisticsSchema:
    """Статистика автопарка"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    total_cars = db.query(Car).count()
    free_cars = db.query(Car).filter(Car.status == CarStatus.FREE).count()
    in_use_cars = db.query(Car).filter(Car.status == CarStatus.IN_USE).count()
    service_cars = db.query(Car).filter(Car.status == CarStatus.SERVICE).count()

    # Активные аренды
    active_rentals = db.query(RentalHistory).filter(
        RentalHistory.rental_status.in_([
            RentalStatus.RESERVED,
            RentalStatus.IN_USE,
            RentalStatus.DELIVERING,
            RentalStatus.DELIVERING_IN_PROGRESS
        ])
    ).count()

    available_cars = free_cars + service_cars

    return CarStatisticsSchema(
        total_cars=total_cars,
        free_cars=free_cars,
        in_use_cars=in_use_cars,
        active_rentals=active_rentals,
        available_cars=available_cars,
        service_cars=service_cars,
    )


@cars_router.put("/{car_id}")
async def update_car(
    car_id: str,
    car_data: CarEditSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Редактировать автомобиль"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    # Обновляем поля
    update_data = car_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        if hasattr(car, field):
            setattr(car, field, value)

    db.commit()

    log_action(
        db,
        actor_id=current_user.id,
        action="update_car",
        entity_type="car",
        entity_id=car.id,
        details={"updated_fields": list(update_data.keys()), "update_data": str(update_data)}
    )

    db.refresh(car)

    return {
        "message": "Автомобиль успешно обновлен",
        "car_id": uuid_to_sid(car.id),
        "updated_fields": list(update_data.keys())
    }


@cars_router.patch("/{car_id}/description", summary="Изменить описание автомобиля")
async def update_car_description_admin(
    car_id: str,
    body: DescriptionUpdateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Изменить описание автомобиля (admin)."""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    car.description = body.description
    db.commit()
    db.refresh(car)
    log_action(
        db=db,
        actor_id=current_user.id,
        action="update_car_description",
        entity_type="car",
        entity_id=car.id,
        details={"car_name": car.name, "plate_number": car.plate_number},
    )
    return {"success": True, "car_id": uuid_to_sid(car.id), "description": car.description}


@cars_router.post("/{car_id}/photos")
async def upload_car_photos(
    car_id: str,
    photos: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Загрузка фотографий автомобиля в MinIO (append к существующим car.photos)"""
    from app.services.minio_service import get_minio_service
    
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    saved_urls: List[str] = []
    # Используем plate_number для создания папки в MinIO
    normalized_plate = normalize_plate_number(car.plate_number) if car.plate_number else str(car.id)
    folder = f"cars/{normalized_plate}"
    
    minio = get_minio_service()

    for f in photos:
        # Загружаем файл в MinIO
        url = await minio.upload_file(f, car.id, folder)
        saved_urls.append(url)

    existing = car.photos or []
    car.photos = existing + saved_urls
    
    log_action(
        db,
        actor_id=current_user.id,
        action="upload_car_photos",
        entity_type="car",
        entity_id=car.id,
        details={"added_count": len(saved_urls), "total_count": len(car.photos)}
    )

    db.commit()
    db.refresh(car)

    return {
        "message": "Фотографии добавлены",
        "car_id": uuid_to_sid(car.id),
        "added": saved_urls,
        "total_photos": len(car.photos or [])
    }


def normalize_photo_url_for_comparison(url: str) -> str:
    """Нормализует URL фотографии для сравнения (извлекает путь без домена)"""
    if not url:
        return url
    # Удаляем домен MinIO, если есть
    minio_domains = [
        "https://msmain.azvmotors.kz",
        "http://msmain.azvmotors.kz",
        "https://msmain.azvmotors.kz/",
        "http://msmain.azvmotors.kz/",
    ]
    for domain in minio_domains:
        if url.startswith(domain):
            url = url[len(domain):]
            break
    # Убираем ведущий слеш если есть
    url = url.lstrip("/")
    return url


@cars_router.delete("/{car_id}/photos/one", summary="Удалить одну фотографию автомобиля")
async def delete_car_photo_one(
    car_id: str,
    body: CarDeletePhotoSchema = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Удалить одну фотографию автомобиля из MinIO и из списка photos при редактировании"""
    from app.services.minio_service import get_minio_service

    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    photo_url = body.photo_url.strip()
    if not photo_url:
        raise HTTPException(status_code=400, detail="photo_url не может быть пустым")

    photos = car.photos or []
    
    # Нормализуем URL для сравнения
    normalized_input = normalize_photo_url_for_comparison(photo_url)
    
    # Ищем соответствующее фото в списке (сравниваем нормализованные URL)
    matching_photo = None
    for p in photos:
        if normalize_photo_url_for_comparison(p) == normalized_input:
            matching_photo = p
            break
    
    if not matching_photo:
        logger.warning(f"[delete_car_photo_one] Photo not found. Input: {photo_url}, Normalized: {normalized_input}")
        logger.warning(f"[delete_car_photo_one] Available photos: {photos}")
        raise HTTPException(
            status_code=404,
            detail="Фотография не найдена среди фотографий этого автомобиля"
        )
    
    # Используем оригинальный URL из базы для удаления
    photo_url = matching_photo

    try:
        minio = get_minio_service()
        ok = minio.delete_file(photo_url)
        if not ok:
            logger.warning(f"Не удалось удалить файл из MinIO: {photo_url}")

        car.photos = [p for p in photos if p != photo_url]

        log_action(
            db,
            actor_id=current_user.id,
            action="delete_car_photo_one",
            entity_type="car",
            entity_id=car.id,
            details={"photo_url": photo_url, "remaining_count": len(car.photos or [])},
        )
        db.commit()
        db.refresh(car)

        return {
            "message": "Фотография удалена",
            "car_id": uuid_to_sid(car.id),
            "deleted_url": photo_url,
            "remaining_count": len(car.photos or []),
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка удаления фотографии: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка удаления фотографии: {e}")


@cars_router.delete("/{car_id}/photos", summary="Удалить все фотографии автомобиля")
async def delete_car_photos(
    car_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Удалить все фотографии автомобиля из базы данных и MinIO"""
    from app.services.minio_service import get_minio_service
    
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    try:
        minio = get_minio_service()
        deleted_files = []
        
        # Удаляем файлы из MinIO по URL
        if car.photos:
            minio.delete_files(car.photos)
            deleted_files = [url.split("/")[-1] for url in car.photos]
        
        # Также удаляем всю папку с фотографиями автомобиля в MinIO
        normalized_plate = normalize_plate_number(car.plate_number) if car.plate_number else str(car.id)
        folder = f"cars/{normalized_plate}"
        minio.delete_folder(folder)
        
        # Очищаем поле photos в базе данных
        deleted_count = len(car.photos or [])
        car.photos = []
        db.commit()
        db.refresh(car)

        log_action(
            db,
            actor_id=current_user.id,
            action="delete_car_photos",
            entity_type="car",
            entity_id=car.id,
            details={"deleted_count": deleted_count, "deleted_files": deleted_files}
        )
        
        return {
            "message": "Все фотографии автомобиля успешно удалены",
            "car_id": uuid_to_sid(car.id),
            "deleted_count": deleted_count,
            "deleted_files": deleted_files
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка удаления фотографий: {e}")


@cars_router.delete("/{car_id}/rentals", summary="Удалить все поездки автомобиля")
async def delete_car_rentals(
    car_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Удалить все поездки автомобиля из базы данных (включая связанные данные)"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    try:
        # Получаем все поездки для этого автомобиля
        rentals = db.query(RentalHistory).filter(RentalHistory.car_id == car.id).all()
        
        if not rentals:
            return {
                "message": "Поездки не найдены",
                "car_id": uuid_to_sid(car.id),
                "deleted_count": 0
            }

        deleted_rentals_count = len(rentals)
        deleted_actions_count = 0
        
        for rental in rentals:
             db.delete(rental)
        
        log_action(
            db,
            actor_id=current_user.id,
            action="delete_car_rentals",
            entity_type="car",
            entity_id=car.id,
            details={"deleted_rentals_count": deleted_rentals_count}
        )
        
        db.commit()
        
        return {
            "message": "Поездки автомобиля удалены",
            "car_id": uuid_to_sid(car.id),
            "deleted_count": deleted_rentals_count
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка удаления поездок: {str(e)}")
        deleted_signatures_count = 0
        deleted_transactions_count = 0
        deleted_reviews_count = 0

        # Для каждой поездки удаляем связанные данные в правильном порядке
        for rental in rentals:
            rental_uuid = rental.id

            # 1. Удаляем wallet_transactions (related_rental_id)
            transactions = db.query(WalletTransaction).filter(
                WalletTransaction.related_rental_id == rental_uuid
            ).all()
            for transaction in transactions:
                db.delete(transaction)
                deleted_transactions_count += 1

            # 2. Удаляем user_contract_signatures (rental_id)
            signatures = db.query(UserContractSignature).filter(
                UserContractSignature.rental_id == rental_uuid
            ).all()
            for signature in signatures:
                db.delete(signature)
                deleted_signatures_count += 1

            # 3. Удаляем rental_actions (rental_id)
            actions = db.query(RentalAction).filter(
                RentalAction.rental_id == rental_uuid
            ).all()
            for action in actions:
                db.delete(action)
                deleted_actions_count += 1

            # 4. Удаляем rental_reviews (rental_id через relationship)
            review = db.query(RentalReview).filter(
                RentalReview.rental_id == rental_uuid
            ).first()
            if review:
                db.delete(review)
                deleted_reviews_count += 1

        # 5. Удаляем rental_history
        for rental in rentals:
            db.delete(rental)

        db.commit()

        return {
            "message": "Все поездки автомобиля успешно удалены",
            "car_id": uuid_to_sid(car.id),
            "car_name": car.name,
            "deleted_rentals": deleted_rentals_count,
            "deleted_wallet_transactions": deleted_transactions_count,
            "deleted_contract_signatures": deleted_signatures_count,
            "deleted_rental_actions": deleted_actions_count,
            "deleted_rental_reviews": deleted_reviews_count
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка удаления поездок: {e}")


@cars_router.put("/{car_id}/status")
async def update_car_status(
    car_id: str,
    new_status: str,
    reason: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Изменить статус автомобиля"""
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    old_status = car.status
    car.status = new_status
    db.commit()
    db.refresh(car)

    if new_status in ["IN_USE", "DELIVERING", "DELIVERING_IN_PROGRESS", "COMPLETED"]:
        active_rental = (
            db.query(RentalHistory)
            .filter(
                RentalHistory.car_id == car.id,
                RentalHistory.rental_status.in_([
                    RentalStatus.RESERVED,
                    RentalStatus.IN_USE,
                    RentalStatus.DELIVERING,
                    RentalStatus.DELIVERING_IN_PROGRESS
                ])
            )
            .first()
        )
        
        if active_rental:
            status_mapping = {
                "IN_USE": RentalStatus.IN_USE,
                "DELIVERING": RentalStatus.DELIVERING,
                "DELIVERING_IN_PROGRESS": RentalStatus.DELIVERING_IN_PROGRESS,
                "COMPLETED": RentalStatus.COMPLETED
            }
            
            if new_status in status_mapping:
                active_rental.rental_status = status_mapping[new_status]
                if new_status == "COMPLETED":
                    active_rental.end_time = get_local_time()
                
                db.commit()
                
                asyncio.create_task(notify_vehicles_list_update())
                asyncio.create_task(notify_user_status_update(str(active_rental.user_id)))
                if car.owner_id:
                    asyncio.create_task(notify_user_status_update(str(car.owner_id)))
    else:
        asyncio.create_task(notify_vehicles_list_update())
        if car.owner_id:
            asyncio.create_task(notify_user_status_update(str(car.owner_id)))
        if car.current_renter_id:
            asyncio.create_task(notify_user_status_update(str(car.current_renter_id)))

    return {
        "message": "Статус автомобиля изменен",
        "car_id": uuid_to_sid(car.id),
        "old_status": old_status,
        "new_status": new_status,
        "reason": reason
    }


@cars_router.get("/{car_id}/rental-history")
async def get_car_rental_history(
    car_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получить историю аренды автомобиля (включая изменения статуса)"""
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    # Получаем историю аренды
    rentals = (
        db.query(RentalHistory)
        .filter(RentalHistory.car_id == car.id)
        .order_by(RentalHistory.reservation_time.desc())
        .all()
    )

    result = []
    for rental in rentals:
        # Получаем отзыв для этой аренды
        review = db.query(RentalReview).filter(RentalReview.rental_id == rental.id).first()
        
        # Доставка: данные механика доставки (если есть)
        delivery_mechanic = getattr(rental, "delivery_mechanic", None)
        delivery_mechanic_info = None
        if delivery_mechanic:
            delivery_mechanic_info = {
                "id": uuid_to_sid(delivery_mechanic.id),
                "first_name": delivery_mechanic.first_name or "",
                "last_name": delivery_mechanic.last_name or "",
                "phone_number": delivery_mechanic.phone_number or "",
            }

        # Осмотр: данные механика-инспектора (если есть)
        inspection_mechanic = None
        inspection_mechanic_info = None
        if rental.mechanic_inspector_id:
            inspection_mechanic = db.query(User).filter(User.id == rental.mechanic_inspector_id).first()
            if inspection_mechanic:
                inspection_mechanic_info = {
                    "id": uuid_to_sid(inspection_mechanic.id),
                    "first_name": inspection_mechanic.first_name or "",
                    "last_name": inspection_mechanic.last_name or "",
                    "phone_number": inspection_mechanic.phone_number or "",
                }

        # Получаем данные арендатора
        renter = db.query(User).filter(User.id == rental.user_id).first()
        renter_info = None
        if renter:
            renter_info = {
                "id": uuid_to_sid(renter.id),
                "first_name": renter.first_name or "",
                "last_name": renter.last_name or "",
                "phone_number": renter.phone_number or "",
                "selfie_url": renter.selfie_url,
                "license_front_url": renter.drivers_license_url,
                "license_back_url": None,
            }

        result.append({
            "rental_id": uuid_to_sid(rental.id),
            "car_id": uuid_to_sid(rental.car_id),
            "user_id": uuid_to_sid(rental.user_id),
            "renter": renter_info,
            "reservation_time": rental.reservation_time.isoformat() if rental.reservation_time else None,
            "start_time": rental.start_time.isoformat() if rental.start_time else None,
            "end_time": rental.end_time.isoformat() if rental.end_time else None,
            "rental_status": rental.rental_status.value if rental.rental_status else None,
            "rental_type": rental.rental_type.value if rental.rental_type else None,
            "total_price": rental.total_price,
            "base_price": rental.base_price,
            "waiting_fee": rental.waiting_fee,
            "overtime_fee": rental.overtime_fee,
            "distance_fee": rental.distance_fee,
            "delivery_fee": rental.delivery_fee,
            "delivery_mechanic": delivery_mechanic_info,
            "inspection_mechanic": inspection_mechanic_info,
            "photos_before": rental.photos_before or [],
            "photos_after": rental.photos_after or [],
            "mechanic_photos_before": rental.mechanic_photos_before or [],
            "mechanic_photos_after": rental.mechanic_photos_after or [],
            "rating": rental.rating,  
            "review": {
                "rating": review.rating if review else None,
                "comment": review.comment if review else None,
                "mechanic_rating": review.mechanic_rating if review else None,
                "mechanic_comment": review.mechanic_comment if review else None,
            } if review else None,
            "created_at": rental.reservation_time.isoformat() if rental.reservation_time else None,
            "updated_at": rental.end_time.isoformat() if rental.end_time else None,
        })

    return {
        "car_id": uuid_to_sid(car.id),
        "car_name": car.name,
        "plate_number": car.plate_number,
        "rental_history": result,
        "total_rentals": len(result)
    }


@cars_router.post("/{car_id}/open", summary="Открыть автомобиль")
async def admin_open_vehicle(
    car_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Открыть автомобиль (разблокировать двери)"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    if not car.gps_imei:
        raise HTTPException(status_code=400, detail="У автомобиля не настроен GPS IMEI")
    
    try:
        auth_token = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        if not auth_token:
            raise HTTPException(status_code=500, detail="Не удалось получить токен авторизации GPS")
        
        result = await send_open(car.gps_imei, auth_token)

        log_action(
            db,
            actor_id=current_user.id,
            action="open_vehicle",
            entity_type="car",
            entity_id=car.id,
            details={"gps_imei": car.gps_imei, "command_id": result.get("command_id")}
        )
        db.commit()
        
        return {
            "message": "Команда на открытие отправлена",
            "car_id": uuid_to_sid(car.id),
            "car_name": car.name,
            "command_id": result.get("command_id")
        }
    except HTTPException:
        raise
    except Exception as e:
        await log_error_to_telegram(error=e, request=None, user=current_user, additional_context={
            "action": "admin_open_vehicle", "car_id": car_id, "gps_imei": car.gps_imei
        })
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")


@cars_router.post("/{car_id}/close", summary="Закрыть автомобиль")
async def admin_close_vehicle(
    car_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Закрыть автомобиль (заблокировать двери)"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    if not car.gps_imei:
        raise HTTPException(status_code=400, detail="У автомобиля не настроен GPS IMEI")
    
    try:
        auth_token = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        if not auth_token:
            raise HTTPException(status_code=500, detail="Не удалось получить токен авторизации GPS")
        
        result = await send_close(car.gps_imei, auth_token)

        log_action(
            db,
            actor_id=current_user.id,
            action="close_vehicle",
            entity_type="car",
            entity_id=car.id,
            details={"gps_imei": car.gps_imei, "command_id": result.get("command_id")}
        )
        db.commit()
        
        return {
            "message": "Команда на закрытие отправлена",
            "car_id": uuid_to_sid(car.id),
            "car_name": car.name,
            "command_id": result.get("command_id")
        }
    except HTTPException:
        raise
    except Exception as e:
        await log_error_to_telegram(error=e, request=None, user=current_user, additional_context={
            "action": "admin_close_vehicle", "car_id": car_id, "gps_imei": car.gps_imei
        })
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")


@cars_router.post("/{car_id}/lock_engine", summary="Заблокировать двигатель")
async def admin_lock_engine(
    car_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Заблокировать двигатель автомобиля"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    if not car.gps_imei:
        raise HTTPException(status_code=400, detail="У автомобиля не настроен GPS IMEI")
    
    try:
        auth_token = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        if not auth_token:
            raise HTTPException(status_code=500, detail="Не удалось получить токен авторизации GPS")
        
        result = await send_lock_engine(car.gps_imei, auth_token)

        log_action(
            db,
            actor_id=current_user.id,
            action="lock_engine",
            entity_type="car",
            entity_id=car.id,
            details={"gps_imei": car.gps_imei, "command_id": result.get("command_id"), "skipped": False}
        )
        db.commit()
        
        if result.get("skipped"):
            return {
                "message": "Блокировка двигателя отключена для этого автомобиля",
                "car_id": uuid_to_sid(car.id),
                "car_name": car.name,
                "skipped": True,
                "reason": result.get("reason")
            }
        
        return {
            "message": "Команда на блокировку двигателя отправлена",
            "car_id": uuid_to_sid(car.id),
            "car_name": car.name,
            "command_id": result.get("command_id")
        }
    except HTTPException:
        raise
    except Exception as e:
        await log_error_to_telegram(error=e, request=None, user=current_user, additional_context={
            "action": "admin_lock_engine", "car_id": car_id, "gps_imei": car.gps_imei
        })
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")


@cars_router.post("/{car_id}/unlock_engine", summary="Разблокировать двигатель")
async def admin_unlock_engine(
    car_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Разблокировать двигатель автомобиля"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    if not car.gps_imei:
        raise HTTPException(status_code=400, detail="У автомобиля не настроен GPS IMEI")
    
    try:
        auth_token = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        if not auth_token:
            raise HTTPException(status_code=500, detail="Не удалось получить токен авторизации GPS")
        
        result = await send_unlock_engine(car.gps_imei, auth_token)

        log_action(
            db,
            actor_id=current_user.id,
            action="unlock_engine",
            entity_type="car",
            entity_id=car.id,
            details={"gps_imei": car.gps_imei, "command_id": result.get("command_id")}
        )
        db.commit()
        
        return {
            "message": "Команда на разблокировку двигателя отправлена",
            "car_id": uuid_to_sid(car.id),
            "car_name": car.name,
            "command_id": result.get("command_id")
        }
    except HTTPException:
        raise
    except Exception as e:
        await log_error_to_telegram(error=e, request=None, user=current_user, additional_context={
            "action": "admin_unlock_engine", "car_id": car_id, "gps_imei": car.gps_imei
        })
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")


@cars_router.post("/{car_id}/give_key", summary="Выдать ключ")
async def admin_give_key(
    car_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Выдать ключ автомобиля"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    if not car.gps_imei:
        raise HTTPException(status_code=400, detail="У автомобиля не настроен GPS IMEI")
    
    try:
        auth_token = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        if not auth_token:
            raise HTTPException(status_code=500, detail="Не удалось получить токен авторизации GPS")
        
        result = await send_give_key(car.gps_imei, auth_token)

        log_action(
            db,
            actor_id=current_user.id,
            action="give_key",
            entity_type="car",
            entity_id=car.id,
            details={"gps_imei": car.gps_imei, "command_id": result.get("command_id")}
        )
        db.commit()
        
        return {
            "message": "Команда на выдачу ключа отправлена",
            "car_id": uuid_to_sid(car.id),
            "car_name": car.name,
            "command_id": result.get("command_id")
        }
    except HTTPException:
        raise
    except Exception as e:
        await log_error_to_telegram(error=e, request=None, user=current_user, additional_context={
            "action": "admin_give_key", "car_id": car_id, "gps_imei": car.gps_imei
        })
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")


@cars_router.post("/{car_id}/take_key", summary="Забрать ключ")
async def admin_take_key(
    car_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Забрать ключ автомобиля.
    Если двигатель включен, сначала заблокирует его, затем заберет ключ.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    if not car.gps_imei:
        raise HTTPException(status_code=400, detail="У автомобиля не настроен GPS IMEI")
    
    try:
        auth_token = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        if not auth_token:
            raise HTTPException(status_code=500, detail="Не удалось получить токен авторизации GPS")
        
        engine_was_locked = False
        try:
            glonassoft_data = await glonassoft_client.get_vehicle_data(car.gps_imei)
            if glonassoft_data:
                telemetry = process_glonassoft_data(glonassoft_data, car.name)
                if telemetry.is_engine_on:
                    await send_lock_engine(car.gps_imei, auth_token)
                    engine_was_locked = True
                    logger.info(f"Двигатель автомобиля {car.name} заблокирован перед забором ключа")
        except Exception as e:
            logger.warning(f"Не удалось проверить состояние двигателя: {e}")
        
        result = await send_take_key(car.gps_imei, auth_token)

        log_action(
            db,
            actor_id=current_user.id,
            action="take_key",
            entity_type="car",
            entity_id=car.id,
            details={"gps_imei": car.gps_imei, "command_id": result.get("command_id"), "engine_was_locked": engine_was_locked}
        )
        db.commit()
        
        return {
            "message": "Команда на забор ключа отправлена",
            "car_id": uuid_to_sid(car.id),
            "car_name": car.name,
            "command_id": result.get("command_id"),
            "engine_was_locked": engine_was_locked
        }
    except HTTPException:
        raise
    except Exception as e:
        await log_error_to_telegram(error=e, request=None, user=current_user, additional_context={
            "action": "admin_take_key", "car_id": car_id, "gps_imei": car.gps_imei
        })
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")


@cars_router.post("/", response_model=CarCreateResponseSchema, summary="Создать новый автомобиль")
async def create_car(
    car_data: CarCreateSchema,
    photos: List[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Создать новый автомобиль.
    
    1. Получает данные о машине от Glonass API по IMEI
    2. Создает машину в основной БД
    3. Отправляет данные в azv_motors_cars_v2 для мониторинга
    """
    if current_user.role not in [UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Недостаточно прав для создания автомобиля")
    
    # Проверяем, не существует ли уже машина с таким plate_number
    existing_car = db.query(Car).filter(
        Car.plate_number == car_data.plate_number
    ).first()
    
    if existing_car:
        raise HTTPException(status_code=400, detail=f"Автомобиль с номером {car_data.plate_number} уже существует")
    
    # Проверяем IMEI только если он указан
    if car_data.gps_imei:
        existing_car_by_imei = db.query(Car).filter(
            Car.gps_imei == car_data.gps_imei
        ).first()
        
        if existing_car_by_imei:
            raise HTTPException(status_code=400, detail=f"Автомобиль с IMEI {car_data.gps_imei} уже существует")
    
    glonass_data_received = False
    vehicle_id = None
    latitude = None
    longitude = None
    fuel_level = None
    mileage = None
    
    # Шаг 1: Получаем данные от Glonass API (только если указан gps_imei)
    if car_data.gps_imei:
        try:
            # Аутентификация в Glonass
            auth_token = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            if auth_token:
                # Получаем данные о машине по IMEI
                glonass_response = await glonassoft_client.get_vehicle_data(car_data.gps_imei)
                
                if glonass_response:
                    glonass_data_received = True
                    vehicle_id = str(glonass_response.get("vehicleid"))
                    latitude = glonass_response.get("latitude")
                    longitude = glonass_response.get("longitude")
                    
                    # Извлекаем данные из RegistredSensors
                    registered_sensors = glonass_response.get("RegistredSensors", [])
                    for sensor in registered_sensors:
                        param_name = sensor.get("parameterName", "")
                        value = sensor.get("value", "")
                        
                        # Пробег (param68)
                        if param_name == "param68":
                            try:
                                mileage = int(float(value))
                            except (ValueError, TypeError):
                                pass
                        
                        # Уровень топлива (param70)
                        if param_name == "param70":
                            try:
                                # Значение может быть "19 l", извлекаем число
                                fuel_str = value.replace(" l", "").replace(" L", "").strip()
                                fuel_level = float(fuel_str)
                            except (ValueError, TypeError):
                                pass
                    
                    logger.info(f"Получены данные Glonass для IMEI {car_data.gps_imei}: vehicle_id={vehicle_id}, lat={latitude}, lon={longitude}")
            else:
                logger.warning(f"Не удалось получить токен авторизации Glonass для IMEI {car_data.gps_imei}")
        except Exception as e:
            logger.error(f"Ошибка получения данных Glonass для IMEI {car_data.gps_imei}: {e}")
            # Продолжаем создание машины даже без данных Glonass
    else:
        logger.info("GPS IMEI не указан, пропускаем запрос к Glonass API")
    
    # Шаг 2: Обработка owner_id
    owner_uuid = None
    if car_data.owner_id:
        owner_uuid = safe_sid_to_uuid(car_data.owner_id)
        # Проверяем, что владелец существует
        owner = db.query(User).filter(User.id == owner_uuid).first()
        if not owner:
            raise HTTPException(status_code=400, detail=f"Владелец с ID {car_data.owner_id} не найден")
    
    # Шаг 3: Обработка фотографий
    photo_urls = []
    if photos:
        for i, photo in enumerate(photos):
            try:
                # Используем plate_number для создания папки
                folder_name = car_data.plate_number.replace(" ", "").replace("/", "").upper()
                file_extension = photo.filename.split(".")[-1] if "." in photo.filename else "jpg"
                
                # Определяем тип фото по индексу
                if i == 0:
                    file_name = f"front_1.{file_extension}"
                elif i == 1:
                    file_name = f"interior_1.{file_extension}"
                elif i == 2:
                    file_name = f"rear_1.{file_extension}"
                else:
                    file_name = f"photo_{i+1}.{file_extension}"
                
                saved_url = await save_file(photo, f"cars/{folder_name}", file_name)
                if saved_url:
                    photo_urls.append(saved_url)
            except Exception as e:
                logger.error(f"Ошибка сохранения фото {photo.filename}: {e}")
    
    # Шаг 4: Создаем машину в БД
    new_car = Car(
        name=car_data.name,
        plate_number=car_data.plate_number,
        gps_id=vehicle_id,
        gps_imei=car_data.gps_imei,
        latitude=latitude,
        longitude=longitude,
        fuel_level=fuel_level,
        mileage=mileage,
        price_per_minute=car_data.price_per_minute,
        price_per_hour=car_data.price_per_hour,
        price_per_day=car_data.price_per_day,
        open_fee=car_data.open_fee,
        auto_class=car_data.auto_class,
        engine_volume=car_data.engine_volume,
        year=car_data.year,
        drive_type=car_data.drive_type,
        transmission_type=car_data.transmission_type,
        body_type=car_data.body_type,
        vin=car_data.vin,
        color=car_data.color,
        photos=photo_urls if photo_urls else None,
        description=car_data.description,
        owner_id=owner_uuid,
        status=CarStatus.FREE,
        created_at=get_local_time(),
        updated_at=get_local_time()
    )
    
    try:
        db.add(new_car)
        db.commit()
        db.refresh(new_car)
        logger.info(f"Автомобиль {new_car.name} ({new_car.plate_number}) успешно создан с ID {new_car.id}")
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка создания автомобиля в БД: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка создания автомобиля: {e}")
    
    # Шаг 5: Отправляем данные в azv_motors_cars_v2 (только если есть vehicle_id и gps_imei)
    vehicle_added_to_cars_v2 = False
    if vehicle_id and car_data.gps_imei:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                vehicle_data = {
                    "vehicle_id": int(vehicle_id),
                    "vehicle_imei": car_data.gps_imei,
                    "name": car_data.name,
                    "plate_number": car_data.plate_number
                }
                
                response = await client.post(
                    CARS_V2_API_URL + "/",
                    json=vehicle_data,
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code in [200, 201]:
                    vehicle_added_to_cars_v2 = True
                    logger.info(f"Автомобиль {new_car.name} успешно добавлен в azv_motors_cars_v2")
                else:
                    logger.warning(f"Не удалось добавить автомобиль в azv_motors_cars_v2: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Ошибка отправки данных в azv_motors_cars_v2: {e}")
            # Не прерываем процесс, машина уже создана в основной БД
    else:
        if not car_data.gps_imei:
            logger.info("GPS IMEI не указан, пропускаем отправку в azv_motors_cars_v2")
        elif not vehicle_id:
            logger.info("Vehicle ID не получен от Glonass, пропускаем отправку в azv_motors_cars_v2")
    
    # Логируем действие
    log_action(
        db,
        actor_id=current_user.id,
        action="create_car",
        entity_type="car",
        entity_id=new_car.id,
        details={
            "name": new_car.name,
            "plate_number": new_car.plate_number,
            "gps_imei": new_car.gps_imei,
            "glonass_data_received": glonass_data_received,
            "vehicle_added_to_cars_v2": vehicle_added_to_cars_v2
        }
    )
    db.commit()
    
    # # Уведомляем о обновлении списка машин
    # try:
    #     await notify_vehicles_list_update()
    # except Exception as e:
    #     logger.warning(f"Не удалось отправить уведомление об обновлении списка машин: {e}")
    
    return CarCreateResponseSchema(
        id=uuid_to_sid(new_car.id),
        name=new_car.name,
        plate_number=new_car.plate_number,
        gps_id=new_car.gps_id,
        gps_imei=new_car.gps_imei,
        latitude=new_car.latitude,
        longitude=new_car.longitude,
        fuel_level=new_car.fuel_level,
        mileage=new_car.mileage,
        status=new_car.status.value if new_car.status else "FREE",
        auto_class=new_car.auto_class.value if new_car.auto_class else "A",
        body_type=new_car.body_type.value if new_car.body_type else "SEDAN",
        price_per_minute=new_car.price_per_minute,
        price_per_hour=new_car.price_per_hour,
        price_per_day=new_car.price_per_day,
        open_fee=new_car.open_fee,
        vehicle_added_to_cars_v2=vehicle_added_to_cars_v2,
        glonass_data_received=glonass_data_received
    )


@cars_router.post("/with-photos", response_model=CarCreateResponseSchema, summary="Создать новый автомобиль с фотографиями")
async def create_car_with_photos(
    name: str = Query(..., description="Название автомобиля"),
    plate_number: str = Query(..., description="Номерной знак"),
    gps_imei: Optional[str] = Query(None, description="IMEI GPS-трекера"),
    price_per_minute: int = Query(..., description="Цена за минуту"),
    price_per_hour: int = Query(..., description="Цена за час"),
    price_per_day: int = Query(..., description="Цена за день"),
    open_fee: int = Query(default=4000, description="Стоимость открытия дверей"),
    auto_class: str = Query(default="A", description="Класс автомобиля (A, B, C)"),
    engine_volume: Optional[float] = Query(None, description="Объем двигателя"),
    year: Optional[int] = Query(None, description="Год выпуска"),
    drive_type: Optional[int] = Query(None, description="Тип привода"),
    transmission_type: Optional[str] = Query(None, description="Тип трансмиссии"),
    body_type: str = Query(default="SEDAN", description="Тип кузова"),
    vin: Optional[str] = Query(None, description="VIN номер"),
    color: Optional[str] = Query(None, description="Цвет"),
    description: Optional[str] = Query(None, description="Описание"),
    owner_id: Optional[str] = Query(None, description="ID владельца (SID)"),
    photos: List[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Создать новый автомобиль с загрузкой фотографий.
    Этот эндпоинт принимает данные через query параметры и файлы через multipart/form-data.
    """
    # Конвертируем строковые значения в enum
    try:
        auto_class_enum = CarAutoClass(auto_class)
    except ValueError:
        auto_class_enum = CarAutoClass.A
    
    try:
        body_type_enum = CarBodyType(body_type)
    except ValueError:
        body_type_enum = CarBodyType.SEDAN
    
    transmission_type_enum = None
    if transmission_type:
        try:
            transmission_type_enum = TransmissionType(transmission_type)
        except ValueError:
            pass
    
    car_data = CarCreateSchema(
        name=name,
        plate_number=plate_number,
        gps_imei=gps_imei,
        price_per_minute=price_per_minute,
        price_per_hour=price_per_hour,
        price_per_day=price_per_day,
        open_fee=open_fee,
        auto_class=auto_class_enum,
        engine_volume=engine_volume,
        year=year,
        drive_type=drive_type,
        transmission_type=transmission_type_enum,
        body_type=body_type_enum,
        vin=vin,
        color=color,
        description=description,
        owner_id=owner_id
    )
    
    return await create_car(car_data=car_data, photos=photos, current_user=current_user, db=db)

from pydantic import BaseModel, Field as PydanticField


class AssignOwnerRequest(BaseModel):
    """Запрос на назначение владельца машине"""
    owner_id: str = PydanticField(..., description="ID владельца (SID)")


class AssignOwnerResponse(BaseModel):
    """Ответ на назначение владельца"""
    message: str
    car_id: str
    owner_id: Optional[str]
    previous_owner_id: Optional[str]


class ReleaseOwnerResponse(BaseModel):
    """Ответ на освобождение машины от владельца"""
    message: str
    car_id: str
    released_owner_id: Optional[str]
    car_status: str


class CarOwnershipStatus(BaseModel):
    """Статус владения машиной"""
    car_id: str
    car_name: str
    plate_number: str
    has_owner: bool
    owner_id: Optional[str]
    owner_name: Optional[str]
    owner_phone: Optional[str]
    status: str


@cars_router.post(
    "/{car_id}/assign-owner",
    response_model=AssignOwnerResponse,
    summary="Назначение владельца машине"
)
async def assign_owner_to_car(
    car_id: str,
    request: AssignOwnerRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Назначение владельца машине.

    - Если машина уже имеет владельца, возвращается ошибка 409 (Conflict)
    - Для переназначения владельца сначала используйте release-owner
    - Машина должна существовать
    - Владелец должен существовать и быть активным

    **HTTP коды:**
    - 200: Владелец успешно назначен
    - 400: Некорректный запрос
    - 404: Машина или владелец не найден
    - 409: Машина уже имеет владельца
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    # Получаем машину
    car_uuid = safe_sid_to_uuid(car_id)
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Машина не найдена")

    # Проверяем, что машина ещё не имеет владельца
    if car.owner_id is not None:
        existing_owner = db.query(User).filter(User.id == car.owner_id).first()
        owner_info = f"{existing_owner.first_name} {existing_owner.last_name}" if existing_owner else "Unknown"
        raise HTTPException(
            status_code=409,
            detail=f"Машина уже имеет владельца: {owner_info}. Сначала освободите машину через release-owner"
        )

    # Получаем нового владельца
    owner_uuid = safe_sid_to_uuid(request.owner_id)
    new_owner = db.query(User).filter(User.id == owner_uuid).first()
    if not new_owner:
        raise HTTPException(status_code=404, detail="Владелец не найден")

    if new_owner.is_deleted:
        raise HTTPException(status_code=400, detail="Нельзя назначить удалённого пользователя владельцем")

    # Назначаем владельца
    previous_owner_id = None
    car.owner_id = new_owner.id

    db.commit()

    # Логируем действие
    log_action(
        db,
        actor_id=current_user.id,
        action="assign_car_owner",
        entity_type="car",
        entity_id=car.id,
        details={
            "owner_id": str(new_owner.id),
            "owner_name": f"{new_owner.first_name} {new_owner.last_name}",
            "plate_number": car.plate_number
        }
    )
    db.commit()

    # Уведомляем об обновлении списка машин
    try:
        asyncio.create_task(notify_vehicles_list_update())
    except Exception as e:
        logger.error(f"Error notifying vehicles update: {e}")

    return AssignOwnerResponse(
        message=f"Владелец {new_owner.first_name} {new_owner.last_name} успешно назначен машине {car.plate_number}",
        car_id=uuid_to_sid(car.id),
        owner_id=uuid_to_sid(new_owner.id),
        previous_owner_id=previous_owner_id
    )


@cars_router.post(
    "/{car_id}/release-owner",
    response_model=ReleaseOwnerResponse,
    summary="Освобождение машины от владельца"
)
async def release_owner_from_car(
    car_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Освобождение машины от владельца.

    - Машина становится "свободной" (FREE)
    - Если машина была в статусе OWNER, статус меняется на FREE
    - Машина продолжает существовать и отображается в системе
    - Возможно последующее назначение нового владельца

    **HTTP коды:**
    - 200: Машина успешно освобождена
    - 400: Машина не имеет владельца
    - 404: Машина не найдена
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    # Получаем машину
    car_uuid = safe_sid_to_uuid(car_id)
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Машина не найдена")

    # Проверяем, что машина имеет владельца
    if car.owner_id is None:
        raise HTTPException(status_code=400, detail="Машина не имеет владельца")

    # Запоминаем старого владельца для логирования
    old_owner_id = car.owner_id
    old_owner = db.query(User).filter(User.id == old_owner_id).first()
    old_owner_name = f"{old_owner.first_name} {old_owner.last_name}" if old_owner else "Unknown"

    # Освобождаем машину
    car.owner_id = None

    # Если машина была в статусе OWNER, переводим в FREE
    old_status = car.status
    if car.status == CarStatus.OWNER:
        car.status = CarStatus.FREE

    db.commit()

    # Логируем действие
    log_action(
        db,
        actor_id=current_user.id,
        action="release_car_owner",
        entity_type="car",
        entity_id=car.id,
        details={
            "released_owner_id": str(old_owner_id),
            "released_owner_name": old_owner_name,
            "plate_number": car.plate_number,
            "old_status": old_status.value if old_status else None,
            "new_status": car.status.value if car.status else None
        }
    )
    db.commit()

    # Уведомляем об обновлении списка машин
    try:
        asyncio.create_task(notify_vehicles_list_update())
    except Exception as e:
        logger.error(f"Error notifying vehicles update: {e}")

    return ReleaseOwnerResponse(
        message=f"Машина {car.plate_number} освобождена от владельца {old_owner_name}",
        car_id=uuid_to_sid(car.id),
        released_owner_id=uuid_to_sid(old_owner_id),
        car_status=car.status.value if car.status else "FREE"
    )


@cars_router.post(
    "/{car_id}/reassign-owner",
    response_model=AssignOwnerResponse,
    summary="Переназначение владельца машины (принудительное)"
)
async def reassign_owner_to_car(
    car_id: str,
    request: AssignOwnerRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Принудительное переназначение владельца машины.

    В отличие от assign-owner, этот эндпоинт:
    - Автоматически отвязывает текущего владельца (если есть)
    - Назначает нового владельца за одну операцию
    - Используется когда нужно быстро сменить владельца

    **HTTP коды:**
    - 200: Владелец успешно переназначен
    - 404: Машина или новый владелец не найден
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    # Получаем машину
    car_uuid = safe_sid_to_uuid(car_id)
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Машина не найдена")

    # Запоминаем предыдущего владельца
    previous_owner_id = None
    if car.owner_id:
        previous_owner_id = uuid_to_sid(car.owner_id)

    # Получаем нового владельца
    owner_uuid = safe_sid_to_uuid(request.owner_id)
    new_owner = db.query(User).filter(User.id == owner_uuid).first()
    if not new_owner:
        raise HTTPException(status_code=404, detail="Владелец не найден")

    if new_owner.is_deleted:
        raise HTTPException(status_code=400, detail="Нельзя назначить удалённого пользователя владельцем")

    # Переназначаем владельца
    car.owner_id = new_owner.id

    db.commit()

    # Логируем действие
    log_action(
        db,
        actor_id=current_user.id,
        action="reassign_car_owner",
        entity_type="car",
        entity_id=car.id,
        details={
            "new_owner_id": str(new_owner.id),
            "new_owner_name": f"{new_owner.first_name} {new_owner.last_name}",
            "previous_owner_id": previous_owner_id,
            "plate_number": car.plate_number
        }
    )
    db.commit()

    # Уведомляем об обновлении списка машин
    try:
        asyncio.create_task(notify_vehicles_list_update())
    except Exception as e:
        logger.error(f"Error notifying vehicles update: {e}")

    return AssignOwnerResponse(
        message=f"Владелец машины {car.plate_number} переназначен на {new_owner.first_name} {new_owner.last_name}",
        car_id=uuid_to_sid(car.id),
        owner_id=uuid_to_sid(new_owner.id),
        previous_owner_id=previous_owner_id
    )


@cars_router.get(
    "/{car_id}/ownership",
    response_model=CarOwnershipStatus,
    summary="Статус владения машиной"
)
async def get_car_ownership_status(
    car_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получение статуса владения машиной.

    Возвращает информацию о текущем владельце машины или указывает,
    что машина свободна (без владельца).
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.FINANCIER]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car_uuid = safe_sid_to_uuid(car_id)
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Машина не найдена")

    owner_id = None
    owner_name = None
    owner_phone = None
    has_owner = False

    if car.owner_id:
        owner = db.query(User).filter(User.id == car.owner_id).first()
        if owner and not owner.is_deleted:
            has_owner = True
            owner_id = uuid_to_sid(owner.id)
            owner_name = f"{owner.first_name or ''} {owner.last_name or ''}".strip() or None
            owner_phone = owner.phone_number

    return CarOwnershipStatus(
        car_id=uuid_to_sid(car.id),
        car_name=car.name,
        plate_number=car.plate_number,
        has_owner=has_owner,
        owner_id=owner_id,
        owner_name=owner_name,
        owner_phone=owner_phone,
        status=car.status.value if car.status else "FREE"
    )


@cars_router.get(
    "/free",
    summary="Список свободных машин (без владельца)"
)
async def get_free_cars(
    page: int = Query(1, ge=1, description="Номер страницы"),
    page_size: int = Query(20, ge=1, le=100, description="Количество на странице"),
    search: Optional[str] = Query(None, description="Поиск по названию или номеру"),
    status: Optional[str] = Query(None, description="Фильтр по статусу (FREE, SERVICE, etc)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получение списка машин без владельца с пагинацией.

    Возвращает машины, которым можно назначить владельца.
    Сортировка: сначала FREE, потом остальные статусы.

    **Параметры:**
    - page: номер страницы (начиная с 1)
    - page_size: количество записей на странице (1-100)
    - search: поиск по названию или номеру машины
    - status: фильтр по статусу машины
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    # Базовый запрос - машины без владельца
    query = db.query(Car).filter(Car.owner_id == None)

    # Фильтр по поиску
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Car.name.ilike(search_term),
                Car.plate_number.ilike(search_term),
                Car.vin.ilike(search_term)
            )
        )

    # Фильтр по статусу
    if status:
        try:
            status_enum = CarStatus(status.upper())
            query = query.filter(Car.status == status_enum)
        except ValueError:
            pass  # Игнорируем невалидный статус

    # Общее количество
    total = query.count()

    # Сортировка: FREE первыми, потом по имени
    query = query.order_by(
        (Car.status != CarStatus.FREE).asc(),
        Car.name.asc()
    )

    # Пагинация
    offset = (page - 1) * page_size
    cars = query.offset(offset).limit(page_size).all()

    # Формируем полную информацию о машинах
    result = []
    for car in cars:
        car_data = {
            "id": uuid_to_sid(car.id),
            "name": car.name,
            "plate_number": car.plate_number,
            "vin": car.vin,
            "color": car.color,
            "status": car.status.value if car.status else "FREE",
            "status_display": status_display(car.status),
            "has_owner": False,
            "owner_id": None,
            # Цены
            "price_per_minute": car.price_per_minute,
            "price_per_hour": car.price_per_hour,
            "price_per_day": car.price_per_day,
            "open_fee": car.open_fee,
            # Характеристики
            "auto_class": car.auto_class.value if car.auto_class else None,
            "body_type": car.body_type.value if car.body_type else None,
            "transmission_type": car.transmission_type.value if car.transmission_type else None,
            "engine_volume": car.engine_volume,
            "year": car.year,
            "drive_type": car.drive_type,
            # GPS и местоположение
            "latitude": car.latitude,
            "longitude": car.longitude,
            "gps_id": car.gps_id,
            "gps_imei": car.gps_imei,
            "fuel_level": car.fuel_level,
            "mileage": car.mileage,
            # Медиа
            "photos": sort_car_photos(car.photos or []),
            "description": car.description,
            "rating": car.rating,
            # Аренда
            "current_renter_id": uuid_to_sid(car.current_renter_id) if car.current_renter_id else None,
            "available_minutes": car.available_minutes or 0,
            # Даты
            "created_at": car.created_at.isoformat() if car.created_at else None,
            "updated_at": car.updated_at.isoformat() if car.updated_at else None,
        }
        result.append(car_data)

    total_pages = ceil(total / page_size) if total > 0 else 1

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
        "cars": result
    }


async def toggle_car_notifications_impl(car_id: str, db: Session, current_user: User):
    """Общая логика включения/выключения уведомлений для машины (для admin и support)."""
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    # Toggle the flag
    new_value = not car.notifications_disabled
    car.notifications_disabled = new_value
    db.commit()
    db.refresh(car)

    # Sync with car_api (azv_motors_cars_v2) if IMEI exists
    car_api_sync_details = {
        "attempted": False,
        "success": False,
        "has_imei": bool(car.gps_imei),
        "imei": car.gps_imei,
        "url": None,
        "status_code": None,
        "response_body": None,
        "error": None
    }

    if car.gps_imei:
        car_api_sync_details["attempted"] = True
        car_api_sync_details["url"] = f"{CARS_V2_API_URL}/by-imei/{car.gps_imei}/exclude-from-alerts"
        
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.patch(
                    car_api_sync_details["url"],
                    json={"excluded_from_alerts": new_value}
                )
                car_api_sync_details["status_code"] = response.status_code
                car_api_sync_details["success"] = response.status_code == 200
                
                try:
                    car_api_sync_details["response_body"] = response.json()
                except:
                    car_api_sync_details["response_body"] = response.text[:500]  # Первые 500 символов
                
                if not car_api_sync_details["success"]:
                    car_api_sync_details["error"] = f"HTTP {response.status_code}: {car_api_sync_details['response_body']}"
                    logger.warning(
                        f"Failed to sync excluded_from_alerts with car_api for IMEI {car.gps_imei}: "
                        f"Status {response.status_code}, Response: {car_api_sync_details['response_body']}"
                    )
        except httpx.TimeoutException as e:
            car_api_sync_details["error"] = f"Timeout: {str(e)}"
            logger.warning(f"Timeout syncing excluded_from_alerts with car_api for IMEI {car.gps_imei}: {e}")
        except httpx.RequestError as e:
            car_api_sync_details["error"] = f"Request error: {str(e)}"
            logger.warning(f"Request error syncing excluded_from_alerts with car_api for IMEI {car.gps_imei}: {e}")
        except Exception as e:
            car_api_sync_details["error"] = f"Unexpected error: {str(e)}"
            logger.warning(f"Failed to sync excluded_from_alerts with car_api for IMEI {car.gps_imei}: {e}")
    else:
        car_api_sync_details["error"] = "GPS IMEI не указан для этой машины"

    log_action(
        db=db,
        actor_id=current_user.id,
        action="toggle_notifications",
        entity_type="car",
        entity_id=car.id,
        details={
            "notifications_disabled": new_value,
            "car_name": car.name,
            "plate_number": car.plate_number,
            "car_api_synced": car_api_sync_details["success"],
            "car_api_sync_details": car_api_sync_details
        }
    )

    status_text = "отключены" if new_value else "включены"
    
    # Формируем детальное сообщение
    message_parts = [f"Уведомления для {car.name} ({car.plate_number}) {status_text}"]
    
    if not car.gps_imei:
        message_parts.append("⚠️ GPS IMEI не указан — синхронизация с car_api не выполнена")
    elif car_api_sync_details["success"]:
        message_parts.append("✅ Синхронизация с car_api выполнена успешно")
    else:
        message_parts.append(f"❌ Ошибка синхронизации с car_api: {car_api_sync_details.get('error', 'Неизвестная ошибка')}")

    return {
        "success": True,
        "car_id": uuid_to_sid(car.id),
        "car_name": car.name,
        "plate_number": car.plate_number,
        "notifications_disabled": new_value,
        "notifications_status": status_text,
        "car_api_sync": car_api_sync_details,
        "message": ". ".join(message_parts),
        "warnings": [] if car_api_sync_details["success"] or not car.gps_imei else [
            f"Синхронизация с car_api не удалась: {car_api_sync_details.get('error', 'Неизвестная ошибка')}"
        ]
    }


@cars_router.post("/{car_id}/toggle-notifications")
async def toggle_car_notifications(
    car_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Включить/выключить уведомления для машины.
    Обновляет флаг в локальной БД и в car_api (azv_motors_cars_v2).
    Доступно для ADMIN и SUPPORT.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Access denied")
    return await toggle_car_notifications_impl(car_id, db, current_user)


@cars_router.post("/{car_id}/toggle-exit-zone")
async def toggle_car_exit_zone(
    car_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Включить/выключить разрешение на выезд за зону карты для машины.
    Доступно для ADMIN и SUPPORT.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Access denied")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    # Toggle the flag
    new_value = not car.can_exit_zone
    car.can_exit_zone = new_value
    db.commit()
    db.refresh(car)

    log_action(
        db=db,
        actor_id=current_user.id,
        action="toggle_exit_zone",
        entity_type="car",
        entity_id=car.id,
        details={
            "can_exit_zone": new_value,
            "car_name": car.name,
            "plate_number": car.plate_number
        }
    )

    status_text = "разрешён" if new_value else "запрещён"

    return {
        "success": True,
        "car_id": uuid_to_sid(car.id),
        "can_exit_zone": new_value,
        "message": f"Выезд за зону для {car.name} ({car.plate_number}) {status_text}"
    }


@cars_router.get("/{car_id}/exit-zone-status")
async def get_car_exit_zone_status(
    car_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получить текущий статус разрешения на выезд за зону для машины.
    Доступно для ADMIN и SUPPORT.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Access denied")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    return {
        "car_id": uuid_to_sid(car.id),
        "can_exit_zone": car.can_exit_zone
    }


@cars_router.post("/{car_id}/toggle-exit-zone")
async def toggle_car_exit_zone(
    car_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Включить/выключить разрешение на выезд за зону карты для машины.
    Доступно для ADMIN и SUPPORT.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Access denied")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    # Toggle the flag
    new_value = not car.can_exit_zone
    car.can_exit_zone = new_value
    db.commit()
    db.refresh(car)

    log_action(
        db=db,
        actor_id=current_user.id,
        action="toggle_exit_zone",
        entity_type="car",
        entity_id=car.id,
        details={
            "can_exit_zone": new_value,
            "car_name": car.name,
            "plate_number": car.plate_number
        }
    )

    status_text = "разрешён" if new_value else "запрещён"

    return {
        "success": True,
        "car_id": uuid_to_sid(car.id),
        "can_exit_zone": new_value,
        "message": f"Выезд за зону для {car.name} ({car.plate_number}) {status_text}"
    }


@cars_router.get("/{car_id}/exit-zone-status")
async def get_car_exit_zone_status(
    car_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получить текущий статус разрешения на выезд за зону для машины.
    Доступно для ADMIN и SUPPORT.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Access denied")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    return {
        "car_id": uuid_to_sid(car.id),
        "can_exit_zone": car.can_exit_zone
    }
