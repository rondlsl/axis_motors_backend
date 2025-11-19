from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, constr, Field, conint
from sqlalchemy import or_
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Dict, Any, Optional
import asyncio
from app.utils.short_id import uuid_to_sid, safe_sid_to_uuid

from app.auth.dependencies.get_current_user import get_current_mechanic
from app.dependencies.database.database import get_db
from app.mechanic.utils import isoformat_or_none, _handle_photos, add_review_if_exists
from app.auth.dependencies.save_documents import validate_photos, save_file
from app.services.face_verify import verify_user_upload_against_profile
from app.models.history_model import RentalType, RentalStatus, RentalHistory, RentalReview
from app.models.car_model import Car, CarStatus
from app.models.user_model import User
from app.rent.utils.calculate_price import get_open_price
from app.gps_api.utils.auth_api import get_auth_token
from app.gps_api.utils.car_data import auto_lock_vehicle_after_rental, execute_gps_sequence
from app.core.config import GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD
from app.utils.atomic_operations import delete_uploaded_files
from app.utils.telegram_logger import log_error_to_telegram
from app.guarantor.sms_utils import send_rental_start_sms, send_rental_complete_sms
from app.admin.cars.utils import sort_car_photos

MechanicRouter = APIRouter(tags=["Mechanic"], prefix="/mechanic")


@MechanicRouter.get(
    "/all_vehicles",
    summary="Список всех автомобилей со всеми статусами (без схем)"
)
def get_all_vehicles_plain(
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic),
) -> Dict[str, Any]:
    try:
        from app.models.user_model import UserRole
        cars: List[Car] = db.query(Car).all()
        vehicles_data: List[Dict[str, Any]] = []

        for car in cars:
            # Проверяем статус загрузки фотографий для текущего механика
            photo_before_selfie_uploaded = False
            photo_before_car_uploaded = False
            photo_before_interior_uploaded = False
            photo_after_selfie_uploaded = False
            photo_after_car_uploaded = False
            photo_after_interior_uploaded = False
            
            # Ищем аренду где текущий механик является инспектором для этой машины
            mechanic_rental = db.query(RentalHistory).filter(
                RentalHistory.car_id == car.id,
                RentalHistory.mechanic_inspector_id == current_mechanic.id,
                RentalHistory.mechanic_inspection_status.in_(["PENDING", "IN_USE", "SERVICE"])
            ).first()
            
            if mechanic_rental and mechanic_rental.mechanic_photos_before:
                # Проверяем наличие разных типов фотографий механика
                photos_before = mechanic_rental.mechanic_photos_before
                photo_before_selfie_uploaded = any(
                    ("/mechanic/before/selfie/" in photo) or ("\\mechanic\\before\\selfie\\" in photo) 
                    for photo in photos_before
                )
                photo_before_car_uploaded = any(
                    ("/mechanic/before/car/" in photo) or ("\\mechanic\\before\\car\\" in photo) 
                    for photo in photos_before
                )
                photo_before_interior_uploaded = any(
                    ("/mechanic/before/interior/" in photo) or ("\\mechanic\\before\\interior\\" in photo) 
                    for photo in photos_before
                )
            
            # Проверяем фото после осмотра механиком
            if mechanic_rental and mechanic_rental.mechanic_photos_after:
                photos_after = mechanic_rental.mechanic_photos_after
                photo_after_selfie_uploaded = any(
                    ("/mechanic/after/selfie/" in photo) or ("\\mechanic\\after\\selfie\\" in photo) 
                    for photo in photos_after
                )
                photo_after_car_uploaded = any(
                    ("/mechanic/after/car/" in photo) or ("\\mechanic\\after\\car\\" in photo) 
                    for photo in photos_after
                )
                photo_after_interior_uploaded = any(
                    ("/mechanic/after/interior/" in photo) or ("\\mechanic\\after\\interior\\" in photo) 
                    for photo in photos_after
                )

            # по умолчанию нет активной аренды
            car_dict: Dict[str, Any] = {
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
                "description": car.description,
                "owner_id": uuid_to_sid(car.owner_id),
                "current_renter_id": uuid_to_sid(car.current_renter_id) if car.current_renter_id else None,
                "status": car.status,
                "open_price": get_open_price(car),
                "owned_car": False,
                "photo_before_selfie_uploaded": photo_before_selfie_uploaded,
                "photo_before_car_uploaded": photo_before_car_uploaded,
                "photo_before_interior_uploaded": photo_before_interior_uploaded,
                "photo_after_selfie_uploaded": photo_after_selfie_uploaded,
                "photo_after_car_uploaded": photo_after_car_uploaded,
                "photo_after_interior_uploaded": photo_after_interior_uploaded,
                "current_renter_details": None,
                "rental_id": None,
                "last_client_review": None,
                "reservation_details": None,
            }

            # ищем последнюю активную аренду (IN_USE или DELIVERING)
            if car.status.lower() in (
                    "in_use",
                    "delivering"
            ):
                active = (
                    db.query(RentalHistory)
                    .filter(
                        RentalHistory.car_id == car.id,
                        RentalHistory.rental_status.in_([
                            RentalStatus.IN_USE,
                            RentalStatus.DELIVERING
                        ])
                    )
                    .order_by(RentalHistory.start_time.desc())
                    .first()
                )
                if active:
                    car_dict["rental_id"] = uuid_to_sid(active.id)

            reservation_statuses = [
                RentalStatus.RESERVED,
                RentalStatus.DELIVERING,
                RentalStatus.DELIVERING_IN_PROGRESS,
                RentalStatus.DELIVERY_RESERVED,
                RentalStatus.SCHEDULED,
            ]
            car_statuses_with_reservation = {
                CarStatus.RESERVED,
                CarStatus.DELIVERING,
                CarStatus.PENDING,
                CarStatus.SCHEDULED,
            }
            if car.status in car_statuses_with_reservation:
                reservation = (
                    db.query(RentalHistory)
                    .filter(
                        RentalHistory.car_id == car.id,
                        RentalHistory.rental_status.in_(reservation_statuses),
                    )
                    .order_by(RentalHistory.reservation_time.desc())
                    .first()
                )
                if reservation:
                    renter = db.query(User).filter(User.id == reservation.user_id).first()
                    if renter:
                        car_dict["reservation_details"] = {
                            "rental_id": uuid_to_sid(reservation.id),
                            "first_name": renter.first_name,
                            "last_name": renter.last_name,
                            "middle_name": renter.middle_name,
                            "phone_number": renter.phone_number,
                            "selfie_url": renter.selfie_url or renter.selfie_with_license_url,
                            "tariff": reservation.rental_type.value if reservation.rental_type else None,
                            "reservation_time": reservation.reservation_time.isoformat() if reservation.reservation_time else None,
                            "duration": reservation.duration,
                        }

            # если машина в использовании — добавляем детали арендатора
            if car.status == CarStatus.IN_USE and car.current_renter_id:
                renter: Optional[User] = db.query(User).get(car.current_renter_id)
                if renter:
                    last_rent = (
                        db.query(RentalHistory)
                        .filter(
                            RentalHistory.car_id == car.id,
                            RentalHistory.user_id == renter.id,
                            RentalHistory.rental_status == RentalStatus.IN_USE,
                        )
                        .order_by(RentalHistory.start_time.desc())
                        .first()
                    )
                    rent_selfie_url: Optional[str] = None
                    if last_rent and last_rent.photos_before:
                        rent_selfie_url = next(
                            (p for p in last_rent.photos_before if "/selfie/" in p or "\\selfie\\" in p),
                            last_rent.photos_before[0],
                        )

                    car_dict["current_renter_details"] = {
                        "id": uuid_to_sid(renter.id),
                        "first_name": renter.first_name,
                        "last_name": renter.last_name,
                        "middle_name": renter.middle_name,
                        "phone_number": renter.phone_number,
                        "selfie_url": renter.selfie_url or renter.selfie_with_license_url,
                        "tariff": last_rent.rental_type.value if last_rent and last_rent.rental_type else None,
                        "rent_selfie_url": rent_selfie_url,
                    }
                    
                    # Для механика в IN_USE прикладываем фото клиента ПОСЛЕ (interior/exterior) и последний отзыв клиента
                    if last_rent and current_mechanic:
                        after_photos = last_rent.photos_after or []
                        if after_photos:
                            car_dict["last_client_after_photos"] = {
                                "interior": [p for p in after_photos if ("/after/interior/" in p) or ("\\after\\interior\\" in p)],
                                "exterior": [p for p in after_photos if ("/after/car/" in p) or ("\\after\\car\\" in p)],
                            }
                        # Последний отзыв клиента по этой аренде
                        review = (
                            db.query(RentalReview)
                            .filter(RentalReview.rental_id == last_rent.id)
                            .order_by(RentalReview.id.desc())
                            .first()
                        )
                        if review and (review.rating or review.comment):
                            # Получаем фото после аренды (салон и кузов)
                            after_photos = last_rent.photos_after or []
                            interior_photos = [p for p in after_photos if ("/after/interior/" in p) or ("\\after\\interior\\" in p)]
                            exterior_photos = [p for p in after_photos if ("/after/car/" in p) or ("\\after\\car\\" in p)]
                            
                            car_dict["last_client_review"] = {
                                "rating": review.rating,
                                "comment": review.comment,
                                "photos_after": {
                                    "interior": interior_photos,
                                    "exterior": exterior_photos
                                }
                            }
            
            # Добавляем информацию о последнем клиенте (для всех статусов)
            # Ищем последнюю завершенную аренду от обычного клиента (не механика)
            last_completed_rental = (
                db.query(RentalHistory)
                .join(User, RentalHistory.user_id == User.id)
                .filter(
                    RentalHistory.car_id == car.id,
                    RentalHistory.rental_status == RentalStatus.COMPLETED,
                    User.role != UserRole.MECHANIC  # Исключаем аренды от механиков
                )
                .order_by(RentalHistory.end_time.desc())
                .first()
            )
            
            if last_completed_rental:
                # Получаем отзыв клиента
                client_review = (
                    db.query(RentalReview)
                    .filter(RentalReview.rental_id == last_completed_rental.id)
                    .first()
                )
                
                if client_review:
                    # Получаем фото после аренды (салон и кузов)
                    after_photos = last_completed_rental.photos_after or []
                    interior_photos = [p for p in after_photos if ("/after/interior/" in p) or ("\\after\\interior\\" in p)]
                    exterior_photos = [p for p in after_photos if ("/after/car/" in p) or ("\\after\\car\\" in p)]
                    
                    car_dict["last_client_review"] = {
                        "rating": client_review.rating,
                        "comment": client_review.comment,
                        "photos_after": {
                            "interior": interior_photos,
                            "exterior": exterior_photos
                        }
                    }

            vehicles_data.append(car_dict)

        return {"vehicles": vehicles_data}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при получении всех автомобилей: {e}"
        )


@MechanicRouter.get("/get_pending_vehicles")
def get_pending_vehicles(
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Возвращает список машин со статусом PENDING с информацией о последнем клиенте,
    который водил автомобиль, включая его комментарии и оценку.
    """
    try:
        cars = db.query(Car).filter(Car.status == CarStatus.PENDING).all()
        vehicles_data = []
        
        for car in cars:
            # Находим последнюю завершенную аренду этого автомобиля
            last_rental = (
                db.query(RentalHistory)
                .filter(
                    RentalHistory.car_id == car.id,
                    RentalHistory.rental_status.in_([
                        RentalStatus.COMPLETED,
                        RentalStatus.CANCELLED
                    ])
                )
                .order_by(RentalHistory.end_time.desc())
                .first()
            )
            
            # Получаем информацию о последнем клиенте
            last_client_info = None
            if last_rental and last_rental.user_id:
                last_client = db.query(User).filter(User.id == last_rental.user_id).first()
                if last_client:
                    # Получаем оценку и комментарий клиента за эту аренду
                    client_review = (
                        db.query(RentalReview)
                        .filter(RentalReview.rental_id == last_rental.id)
                        .first()
                    )
                    
                    last_client_info = {
                        "id": uuid_to_sid(last_client.id),
                        "first_name": last_client.first_name,
                        "last_name": last_client.last_name,
                        "middle_name": last_client.middle_name,
                        "phone_number": last_client.phone_number,
                        "rental_id": uuid_to_sid(last_rental.id),
                        "rental_start": last_rental.start_time.isoformat() if last_rental.start_time else None,
                        "rental_end": last_rental.end_time.isoformat() if last_rental.end_time else None,
                        "rental_status": last_rental.rental_status.value if last_rental.rental_status else None,
                        # Отзыв клиента
                        "client_rating": client_review.rating if client_review else None,
                        "client_comment": client_review.comment if client_review else None,
                        # Отзыв механика осмотра
                        "mechanic_rating": client_review.mechanic_rating if client_review else None,
                        "mechanic_comment": client_review.mechanic_comment if client_review else None,
                        # Отзыв механика доставки
                        "delivery_mechanic_rating": client_review.delivery_mechanic_rating if client_review else None,
                        "delivery_mechanic_comment": client_review.delivery_mechanic_comment if client_review else None
                    }
            
            vehicle_data = {
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
                "owned_car": False,  # для механика это не имеет значения
                "last_client": last_client_info  # Информация о последнем клиенте
            }
            
            vehicles_data.append(vehicle_data)
        
        return {"vehicles": vehicles_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при получении данных об автомобилях: {str(e)}")


@MechanicRouter.get("/get_in_use_vehicles")
def get_in_use_vehicles(
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Список машин со статусом IN_USE.
    Дополнительно:
      • current_renter_details:
          - first_name
          - last_name
          - phone_number
          - selfie_url              (профильное селфи пользователя)
          - rent_selfie_url         (селфи, снятое перед арендой - из photos_before)
    """
    try:
        cars = db.query(Car).filter(Car.status == CarStatus.IN_USE).all()
        vehicles_data: list[dict[str, Any]] = []

        for car in cars:
            car_data = {
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
                "owned_car": False,
                "vin": car.vin,
                "color": car.color
            }

            # --- данные арендатора + селфи перед арендой -------------------
            renter_info = None
            if car.current_renter_id:
                current_renter: User | None = (
                    db.query(User).filter(User.id == car.current_renter_id).first()
                )

                if current_renter:
                    # ищем последнюю активную аренду этого авто
                    last_rental = (
                        db.query(RentalHistory)
                        .filter(
                            RentalHistory.car_id == car.id,
                            RentalHistory.user_id == current_renter.id,
                            RentalHistory.rental_status == RentalStatus.IN_USE,
                        )
                        .order_by(RentalHistory.start_time.desc())  # на случай нескольких аренд подряд
                        .first()
                    )

                    rent_selfie_url: str | None = None
                    if last_rental and last_rental.photos_before:
                        rent_selfie_url = next(
                            (
                                p
                                for p in last_rental.photos_before
                                if "/selfie/" in p or "\\selfie\\" in p
                            ),
                            last_rental.photos_before[0],
                        )

                    renter_info = {
                        "first_name": current_renter.first_name,
                        "last_name": current_renter.last_name,
                        "middle_name": current_renter.middle_name,
                        "phone_number": current_renter.phone_number,
                        "selfie_url": current_renter.selfie_with_license_url,
                        "rent_selfie_url": rent_selfie_url,
                    }

            car_data["current_renter_details"] = renter_info
            vehicles_data.append(car_data)

        return {"vehicles": vehicles_data}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при получении данных об автомобилях: {e}",
        )


@MechanicRouter.get("/get_service_vehicles")
def get_service_vehicles(
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Список машин со статусом SERVICE, закрепленных за текущим механиком.
    Эти машины готовы к началу осмотра через endpoint /mechanic/start/{car_id}.
    """
    try:
        # Получаем только машины в статусе SERVICE, закрепленные за текущим механиком
        cars = db.query(Car).filter(
            Car.status == CarStatus.SERVICE,
            Car.current_renter_id == current_mechanic.id
        ).all()
        
        vehicles_data: list[dict[str, Any]] = []

        for car in cars:
            # Находим последнюю завершенную аренду для получения информации о клиенте
            last_rental = (
                db.query(RentalHistory)
                .filter(
                    RentalHistory.car_id == car.id,
                    RentalHistory.rental_status == RentalStatus.COMPLETED
                )
                .order_by(RentalHistory.end_time.desc())
                .first()
            )
            
            last_client_info = None
            if last_rental and last_rental.user_id:
                last_client = db.query(User).filter(User.id == last_rental.user_id).first()
                if last_client:
                    # Получаем оценку и комментарий клиента
                    client_review = (
                        db.query(RentalReview)
                        .filter(RentalReview.rental_id == last_rental.id)
                        .first()
                    )
                    
                    last_client_info = {
                        "id": uuid_to_sid(last_client.id),
                        "first_name": last_client.first_name,
                        "last_name": last_client.last_name,
                        "middle_name": last_client.middle_name,
                        "phone_number": last_client.phone_number,
                        "rental_id": uuid_to_sid(last_rental.id),
                        "client_rating": client_review.rating if client_review else None,
                        "client_comment": client_review.comment if client_review else None
                    }
            
            car_data = {
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
                "owned_car": False,
                "last_client": last_client_info
            }

            vehicles_data.append(car_data)

        return {"vehicles": vehicles_data}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при получении машин со статусом SERVICE: {e}",
        )


@MechanicRouter.get("/search")
def search_vehicles(
        query: str = Query(..., description="Поисковый запрос по названию авто или номеру"),
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Ищет автомобили по имени или номеру, но возвращает только машины со статусом IN_USE, PENDING или SERVICE.
    Для автомобилей со статусом IN_USE дополнительно возвращаются данные текущего арендатора (first_name, last_name, phone_number, URL селфи).
    """
    try:
        cars = db.query(Car).filter(
            or_(
                Car.name.ilike(f"%{query}%"),
                Car.plate_number.ilike(f"%{query}%")
            ),
            Car.status.in_([CarStatus.IN_USE, CarStatus.PENDING, CarStatus.SERVICE])
        ).all()

        vehicles_data = []
        for car in cars:
            car_data = {
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
                "owned_car": False,
                "vin": car.vin,
                "color": car.color
            }
            if car.status == CarStatus.IN_USE and car.current_renter_id:
                current_renter = db.query(User).filter(User.id == car.current_renter_id).first()
                if current_renter:
                    car_data["current_renter_details"] = {
                        "first_name": current_renter.first_name,
                        "last_name": current_renter.last_name,
                        "middle_name": current_renter.middle_name,
                        "phone_number": current_renter.phone_number,
                        "selfie_url": current_renter.selfie_with_license_url
                    }
                else:
                    car_data["current_renter_details"] = None
            else:
                car_data["current_renter_details"] = None

            vehicles_data.append(car_data)

        return {"vehicles": vehicles_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка поиска авто: {str(e)}")

@MechanicRouter.post("/check-car/{car_id}")
async def check_car(
        car_id: str,
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Инициация проверки автомобиля механиком.
    Аналогично резервированию, но без оплаты – всё бесплатно.
    При проверке статус машины меняется на SERVICE.
    """
    car_uuid = safe_sid_to_uuid(car_id)
    # Проверяем, нет ли у механика активной проверки (резервированной или в работе)
    active_rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_mechanic.id,
        RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
    ).first()
    if active_rental:
        raise HTTPException(
            status_code=400,
            detail="У вас уже есть активная проверка автомобиля. Завершите её, прежде чем начать новую."
        )
    # Выбираем автомобиль если его статус PENDING или SERVICE
    car = db.query(Car).filter(Car.id == car_uuid, Car.status.in_([CarStatus.PENDING, CarStatus.SERVICE])).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден или недоступен для проверки")
    
    # Если автомобиль уже в статусе SERVICE, ищем существующую проверку механика
    if car.status == CarStatus.SERVICE:
        rental = db.query(RentalHistory).filter(
            RentalHistory.car_id == car.id,
            RentalHistory.mechanic_inspector_id == current_mechanic.id,
            RentalHistory.mechanic_inspection_status.in_(["PENDING", "IN_USE", "SERVICE"])
        ).first()
        
        if rental:
            # Проверка уже существует, возвращаем информацию о ней
            return {
                "message": "Проверка автомобиля уже инициирована",
                "rental_id": uuid_to_sid(rental.id),
                "inspection_start_time": rental.mechanic_inspection_start_time.isoformat() if rental.mechanic_inspection_start_time else None
            }
        else:
            raise HTTPException(status_code=403, detail="Этот автомобиль уже закреплен за другим механиком")
    
    # Если автомобиль в статусе PENDING, создаем новую проверку
    # Находим существующую запись аренды клиента для этого автомобиля
    rental = db.query(RentalHistory).filter(
        RentalHistory.car_id == car.id,
        RentalHistory.rental_status == RentalStatus.COMPLETED
    ).order_by(RentalHistory.end_time.desc()).first()
    
    if not rental:
        raise HTTPException(status_code=404, detail="Не найдена завершенная аренда для этого автомобиля")
    
    # Обновляем автомобиль: закрепляем проверяющего механика и меняем статус на SERVICE
    car.current_renter_id = current_mechanic.id
    car.status = CarStatus.SERVICE
    
    # Устанавливаем время начала осмотра механиком в существующую запись
    rental.mechanic_inspector_id = current_mechanic.id
    rental.mechanic_inspection_start_time = datetime.utcnow()
    rental.mechanic_inspection_status = "PENDING"
    # Фиксируем стартовые координаты осмотра по текущему положению автомобиля
    rental.mechanic_inspection_start_latitude = car.latitude
    rental.mechanic_inspection_start_longitude = car.longitude
    
    db.commit()
    return {
        "message": "Проверка автомобиля начата успешно",
        "rental_id": uuid_to_sid(rental.id),
        "inspection_start_time": rental.mechanic_inspection_start_time.isoformat()
    }


@MechanicRouter.post("/start/{car_id}")
async def start_rental(
        car_id: str,
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Старт проверки автомобиля по ID авто (обновление статуса осмотра с PENDING на IN_USE).
    Работает для машин со статусом SERVICE, закрепленных за текущим механиком.
    Всё бесплатно – списания не производится.
    """
    car_uuid = safe_sid_to_uuid(car_id)
    # Сначала проверяем, что машина существует и находится в статусе SERVICE
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    # Проверяем, что машина в статусе SERVICE и закреплена за текущим механиком
    if car.status != CarStatus.SERVICE:
        raise HTTPException(
            status_code=400, 
            detail=f"Автомобиль должен быть в статусе SERVICE. Текущий статус: {car.status}"
        )
    
    if car.current_renter_id != current_mechanic.id:
        raise HTTPException(
            status_code=403, 
            detail="Этот автомобиль не закреплен за вами"
        )
    
    # Ищем активную проверку для этого автомобиля
    rental = db.query(RentalHistory).filter(
        RentalHistory.mechanic_inspector_id == current_mechanic.id,
        RentalHistory.mechanic_inspection_status == "PENDING",
        RentalHistory.car_id == car_uuid,
    ).first()
    
    if not rental:
        raise HTTPException(status_code=404, detail="Нет активной проверки для старта по данному автомобилю")

    # Перед стартом требуем фото: селфи, внешний вид, салон
    before_photos = rental.mechanic_photos_before or []
    has_selfie = any(("/mechanic/before/selfie/" in p) or ("\\mechanic\\before\\selfie\\" in p) for p in before_photos)
    has_exterior = any(("/mechanic/before/car/" in p) or ("\\mechanic\\before\\car\\" in p) for p in before_photos)
    has_interior = any(("/mechanic/before/interior/" in p) or ("\\mechanic\\before\\interior\\" in p) for p in before_photos)
    if not (has_selfie and has_exterior and has_interior):
        missing = []
        if not has_selfie:
            missing.append("селфи")
        if not has_exterior:
            missing.append("внешний вид")
        if not has_interior:
            missing.append("салон")
        raise HTTPException(status_code=400, detail=f"Перед стартом проверки загрузите фото: {', '.join(missing)}")

    # Обновляем статус осмотра на IN_USE
    rental.mechanic_inspection_status = "IN_USE"
    # Для механика переводим автомобиль в состояние IN_USE
    car.status = CarStatus.IN_USE
    db.commit()
    
    # GPS команды при старте проверки механиком
    try:
        if car and car.gps_imei:
            
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            # Универсальная последовательность: разблокировать двигатель → выдать ключ
            result = await execute_gps_sequence(car.gps_imei, auth_token, "interior")
            if not result["success"]:
                print(f"Ошибка GPS последовательности при старте проверки механиком: {result.get('error', 'Unknown error')}")
    except Exception as e:
        print(f"Ошибка GPS команд при старте проверки механиком: {e}")
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_mechanic,
                additional_context={
                    "action": "mechanic_start_inspection_gps",
                    "car_id": str(car.id) if car else None,
                    "car_name": car.name if car else None,
                    "gps_imei": car.gps_imei if car else None,
                    "rental_id": str(rental.id),
                    "mechanic_id": str(current_mechanic.id)
                }
            )
        except:
            pass
    
    # try:
    #     name_parts = []
    #     if current_mechanic.first_name:
    #         name_parts.append(current_mechanic.first_name)
    #     if current_mechanic.middle_name:
    #         name_parts.append(current_mechanic.middle_name)
    #     if current_mechanic.last_name:
    #         name_parts.append(current_mechanic.last_name)
    #     full_name = " ".join(name_parts) if name_parts else "Не указано"
    #     
    #     login = current_mechanic.phone_number or "Не указан"
    #     
    #     await send_rental_start_sms(
    #         client_phone=current_mechanic.phone_number,
    #         rent_id=str(rental.id),
    #         full_name=full_name,
    #         login=login,
    #         client_id=str(current_mechanic.id),
    #         digital_signature=current_mechanic.digital_signature or "Не указана",
    #         car_id=str(car.id),
    #         plate_number=car.plate_number,
    #         car_name=car.name
    #     )
    #     print(f"SMS отправлена механику {current_mechanic.phone_number} при начале проверки")
    # except Exception as e:
    #     print(f"Ошибка отправки SMS при начале проверки механиком: {e}")
    
    return {"message": "Проверка автомобиля запущена", "rental_id": uuid_to_sid(rental.id)}


@MechanicRouter.post("/cancel")
async def cancel_reservation(
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Отмена проверки автомобиля.
    Для механика всё бесплатно, и при отмене статус автомобиля сбрасывается в PENDING.
    Работает только для аренды в статусе RESERVED.
    """
    try:
        # Блокируем запись аренды для обновления, чтобы избежать гонок при конкурентных запросах.
        rental = db.query(RentalHistory).filter(
            RentalHistory.mechanic_inspector_id == current_mechanic.id,
            RentalHistory.mechanic_inspection_status == "PENDING"
        ).with_for_update().first()
        if not rental:
            raise HTTPException(status_code=400, detail="Нет активной проверки для отмены")

        # Получаем автомобиль и блокируем его запись
        car = db.query(Car).filter(Car.id == rental.car_id).with_for_update().first()
        if not car:
            raise HTTPException(status_code=404, detail="Автомобиль не найден")

        now = datetime.utcnow()

        # Обновляем статус осмотра и автомобиля
        rental.mechanic_inspection_status = "CANCELLED"
        rental.mechanic_inspection_end_time = now
        car.current_renter_id = None
        car.status = CarStatus.PENDING  # Возвращаем статус автомобиля в PENDING

        # Пытаемся зафиксировать все изменения одним commit
        db.commit()

        minutes_used = int((now - rental.mechanic_inspection_start_time).total_seconds() / 60) if rental.mechanic_inspection_start_time else 0
        return {
            "message": "Проверка автомобиля отменена",
            "minutes_used": minutes_used
        }
    except Exception as e:
        db.rollback()
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_mechanic,
                additional_context={
                    "action": "mechanic_cancel_inspection",
                    "mechanic_id": str(current_mechanic.id)
                }
            )
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Ошибка при отмене проверки: {str(e)}")

@MechanicRouter.post("/upload-photos-before")
async def upload_photos_before(
        selfie: UploadFile = File(...),
        car_photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    До осмотра (часть 1): selfie + внешние фото. Салон загружается отдельно.
    """
    print(f"=== /mechanic/upload-photos-before START ===")
    print(f"Mechanic ID: {current_mechanic.id}")
    print(f"Mechanic Name: {getattr(current_mechanic, 'first_name', 'N/A')} {getattr(current_mechanic, 'last_name', 'N/A')}")
    print(f"Selfie filename: {selfie.filename}, content_type: {selfie.content_type}")
    print(f"Car photos count: {len(car_photos)}")
    for idx, photo in enumerate(car_photos):
        print(f"  Car photo {idx+1}: {photo.filename}, content_type: {photo.content_type}")
    
    rental = db.query(RentalHistory).filter(
        RentalHistory.mechanic_inspector_id == current_mechanic.id,
        RentalHistory.mechanic_inspection_status.in_(["PENDING", "IN_USE", "SERVICE"])
    ).first()
    
    if not rental:
        print(f"ERROR: Нет активной проверки для механика {current_mechanic.id}")
        raise HTTPException(status_code=404, detail="Нет активной проверки (PENDING, IN_USE или SERVICE)")
    
    print(f"Found rental: ID={rental.id}, car_id={rental.car_id}, status={rental.mechanic_inspection_status}")
    print(f"Existing photos before: {rental.mechanic_photos_before}")

    print(f"Validating selfie...")
    validate_photos([selfie], "selfie")
    # try:
    #     # Сверяем селфи механика с документом
    #     is_same, msg = await run_in_threadpool(verify_user_upload_against_profile, current_mechanic, selfie)
    #     if not is_same:
    #         raise HTTPException(status_code=400, detail=msg)
    # except HTTPException:
    #     raise
    # except Exception as e:
    #     raise HTTPException(status_code=400, detail="Ой! Похоже на фотографии не вы, но если это вы, то пожалуйста сделайте селфи как в профиле.")
    
    print(f"Validating car photos...")
    validate_photos(car_photos, "car_photos")
    print(f"All photos validated successfully")
    
    uploaded_files = []
    try:
        print(f"Starting file upload process...")
        urls = list(rental.mechanic_photos_before or [])
        print(f"Saving selfie...")
        selfie_url = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/mechanic/before/selfie/")
        urls.append(selfie_url)
        uploaded_files.append(selfie_url)
        print(f"Selfie saved: {selfie_url}")
        
        for idx, p in enumerate(car_photos):
            print(f"Saving car photo {idx+1}/{len(car_photos)}: {p.filename}")
            car_photo_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/mechanic/before/car/")
            urls.append(car_photo_url)
            uploaded_files.append(car_photo_url)
            print(f"Car photo {idx+1} saved: {car_photo_url}")
        
        rental.mechanic_photos_before = urls
        print(f"All photos saved. Total URLs: {len(urls)}")
        
        # Универсальная GPS последовательность после загрузки селфи+кузов
        print(f"Starting GPS sequence...")
        car = db.query(Car).get(rental.car_id)
        print(f"Car found: ID={car.id if car else 'None'}, gps_imei={car.gps_imei if car else 'None'}")
        
        if car and car.gps_imei:
            print(f"Executing GPS sequence for IMEI: {car.gps_imei}")
            
            print(f"Getting GPS auth token...")
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            print(f"Auth token received: {auth_token[:20]}..." if auth_token else "No token")
            
            # Универсальная последовательность: открыть замки → выдать ключ → открыть замки → забрать ключ
            print(f"Executing GPS sequence 'selfie_exterior'...")
            result = await execute_gps_sequence(car.gps_imei, auth_token, "selfie_exterior")
            print(f"GPS sequence result: {result}")
            
            if not result["success"]:
                error_msg = result.get('error', 'Unknown error')
                print(f"ERROR: GPS последовательность failed: {error_msg}")
                raise Exception(f"GPS sequence failed: {error_msg}")
            
            print(f"GPS sequence completed successfully")
        else:
            print(f"Skipping GPS sequence - car or gps_imei not available")
        
        print(f"Committing to database...")
        db.commit()
        print(f"Database commit successful")
        
        print(f"=== /mechanic/upload-photos-before SUCCESS ===")
        return {"message": "Фотографии до проверки (selfie+car) загружены", "photo_count": len(urls)}
    except HTTPException as he:
        print(f"ERROR: HTTPException in upload-photos-before: {he.detail}")
        print(f"Rolling back database and deleting uploaded files...")
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        print(f"ERROR: Exception in upload-photos-before: {type(e).__name__}: {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        print(f"Rolling back database and deleting uploaded files...")
        db.rollback()
        delete_uploaded_files(uploaded_files)
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_mechanic,
                additional_context={
                    "action": "mechanic_upload_photos_before",
                    "car_id": str(car.id) if car else None,
                    "car_name": car.name if car else None,
                    "gps_imei": car.gps_imei if car else None,
                    "rental_id": str(rental.id) if rental else None,
                    "mechanic_id": str(current_mechanic.id),
                    "files_uploaded": len(uploaded_files)
                }
            )
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке фотографий до проверки: {str(e)}")


@MechanicRouter.post("/upload-photos-before-interior")
async def upload_photos_before_interior(
        interior_photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    До осмотра (часть 2): только салон (требует загруженные внешние).
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.mechanic_inspector_id == current_mechanic.id,
        RentalHistory.mechanic_inspection_status.in_(["PENDING", "IN_USE", "SERVICE"])
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Нет активной проверки (PENDING, IN_USE или SERVICE)")

    # Требуем сначала внешние фото
    existing = rental.mechanic_photos_before or []
    has_exterior = any(('/mechanic/before/car/' in p) or ('\\mechanic\\before\\car\\' in p) for p in existing)
    if not has_exterior:
        raise HTTPException(status_code=400, detail="Сначала загрузите внешние фото")

    validate_photos(interior_photos, "interior_photos")

    uploaded_files = []
    try:
        urls = list(rental.mechanic_photos_before or [])
        for p in interior_photos:
            interior_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/mechanic/before/interior/")
            urls.append(interior_url)
            uploaded_files.append(interior_url)
        rental.mechanic_photos_before = urls
        db.commit()
        
        return {"message": "Фотографии салона до проверки загружены", "photo_count": len(interior_photos)}
    except HTTPException:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке фото салона до проверки: {str(e)}")


@MechanicRouter.post("/upload-photos-after")
async def upload_photos_after(
        selfie: UploadFile = File(...),
        interior_photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    После осмотра (часть 1): selfie + салон.
    
    После успешной загрузки:
    - Проверяется статус авто (заглушен ли двигатель, закрыты ли окна/двери и т.д.)
    - Блокируются замки
    - Блокируется двигатель
    - Забирается ключ
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.mechanic_inspector_id == current_mechanic.id,
        RentalHistory.mechanic_inspection_status.in_(["PENDING", "IN_USE", "SERVICE"])
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Нет активной проверки (PENDING, IN_USE или SERVICE)")
    
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    # Проверяем состояние автомобиля перед блокировкой
    from app.rent.router import check_vehicle_status_for_completion
    vehicle_status = await check_vehicle_status_for_completion(car.gps_imei)
    
    if "error" in vehicle_status:
        raise HTTPException(status_code=400, detail=vehicle_status["error"])
    
    if vehicle_status.get("errors"):
        error_message = "Перед завершением осмотра:\n" + "\n".join(vehicle_status["errors"])
        raise HTTPException(status_code=400, detail=error_message)

    validate_photos([selfie], "selfie")
    # try:
    #     # Сверяем селфи механика после осмотра с документом
    #     is_same, msg = await run_in_threadpool(verify_user_upload_against_profile, current_mechanic, selfie)
    #     if not is_same:
    #         raise HTTPException(status_code=400, detail=msg)
    # except HTTPException:
    #     raise
    # except Exception as e:
    #     raise HTTPException(status_code=400, detail="Ой! Похоже на фотографии не вы, но если это вы, то пожалуйста сделайте селфи как в профиле.")
    validate_photos(interior_photos, "interior_photos")
    
    uploaded_files = []
    try:
        urls = list(rental.mechanic_photos_after or [])
        selfie_url = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/mechanic/after/selfie/")
        urls.append(selfie_url)
        uploaded_files.append(selfie_url)
        
        for p in interior_photos:
            interior_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/mechanic/after/interior/")
            urls.append(interior_url)
            uploaded_files.append(interior_url)
        
        rental.mechanic_photos_after = urls
        
        # После загрузки селфи+салона механиком: заблокировать двигатель → забрать ключ → закрыть замки
        car = db.query(Car).get(rental.car_id)
        if car and car.gps_imei:
            
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            # Универсальная последовательность: заблокировать двигатель → забрать ключ → закрыть замки
            result = await execute_gps_sequence(car.gps_imei, auth_token, "complete_selfie_interior")
            if not result["success"]:
                error_msg = result.get('error', 'Unknown error')
                print(f"Ошибка GPS последовательности для завершения селфи+салон механиком: {error_msg}")
                raise Exception(f"GPS sequence failed: {error_msg}")
        
        db.commit()
        
        return {"message": "Фотографии после проверки (selfie+interior) загружены", "photo_count": len(urls)}
    except HTTPException:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке фотографий после проверки: {str(e)}")


@MechanicRouter.post("/upload-photos-after-car")
async def upload_photos_after_car(
        car_photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    После осмотра (часть 2): только внешние (требует салон и закрытые двери).
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.mechanic_inspector_id == current_mechanic.id,
        RentalHistory.mechanic_inspection_status.in_(["PENDING", "IN_USE", "SERVICE"])
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Нет активной проверки (PENDING, IN_USE или SERVICE)")

    # Требуем сначала салонные фото
    existing_after = rental.mechanic_photos_after or []
    has_interior_after = any(('/mechanic/after/interior/' in p) or ('\\mechanic\\after\\interior\\' in p) for p in existing_after)
    if not has_interior_after:
        raise HTTPException(status_code=400, detail="Сначала загрузите фото салона")

    # Проверяем двери закрыты (используем общую проверку из аренды)
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    try:
        from app.rent.router import check_vehicle_status_for_completion
        vehicle_status = await check_vehicle_status_for_completion(car.gps_imei)
        if vehicle_status.get("errors"):
            doors_errors = [e for e in vehicle_status["errors"] if "двер" in e.lower() or "door" in e.lower()]
            if doors_errors:
                raise HTTPException(status_code=400, detail="Перед внешними фото закройте двери")
    except Exception:
        pass

    validate_photos(car_photos, "car_photos")

    uploaded_files = []
    try:
        urls = list(rental.mechanic_photos_after or [])
        for p in car_photos:
            car_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/mechanic/after/car/")
            urls.append(car_url)
            uploaded_files.append(car_url)
        
        rental.mechanic_photos_after = urls
        
        # После загрузки кузова механиком: заблокировать двигатель → забрать ключ → закрыть замки
        if car and car.gps_imei:
            
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            # Универсальная последовательность: заблокировать двигатель → забрать ключ → закрыть замки
            result = await execute_gps_sequence(car.gps_imei, auth_token, "complete_exterior")
            if not result["success"]:
                error_msg = result.get('error', 'Unknown error')
                print(f"Ошибка GPS последовательности для завершения кузова механиком: {error_msg}")
                raise Exception(f"GPS sequence failed: {error_msg}")
        
        db.commit()
        
        return {"message": "Фотографии внешние после проверки загружены", "photo_count": len(car_photos)}
    except HTTPException:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке внешних фото после проверки: {str(e)}")


class RentalReviewInput(BaseModel):
    rating: conint(ge=1, le=5) = Field(..., description="Оценка от 1 до 5")
    comment: Optional[constr(max_length=255)] = Field(None, description="Комментарий к проверке (до 255 символов)")


@MechanicRouter.post("/complete")
async def complete_rental(
        review_input: RentalReviewInput,
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Завершает проверку автомобиля.
    Снимается текущая проверка, статус аренды меняется на COMPLETED, а статус автомобиля – на FREE.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.mechanic_inspector_id == current_mechanic.id,
        RentalHistory.mechanic_inspection_status.in_(["PENDING", "IN_USE", "SERVICE"])
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Нет активной проверки для завершения")
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    after_photos = rental.mechanic_photos_after or []
    has_after_selfie = any(("/mechanic/after/selfie/" in p) or ("\\mechanic\\after\\selfie\\" in p) for p in after_photos)
    has_after_interior = any(("/mechanic/after/interior/" in p) or ("\\mechanic\\after\\interior\\" in p) for p in after_photos)
    has_after_exterior = any(("/mechanic/after/car/" in p) or ("\\mechanic\\after\\car\\" in p) for p in after_photos)
    if not (has_after_selfie and has_after_interior and has_after_exterior):
        missing = []
        if not has_after_selfie:
            missing.append("селфи")
        if not has_after_interior:
            missing.append("салон")
        if not has_after_exterior:
            missing.append("внешний вид")
        raise HTTPException(status_code=400, detail=f"Для завершения проверки загрузите фото: {', '.join(missing)}")

    now = datetime.utcnow()
    
    # Устанавливаем время окончания осмотра механиком
    rental.mechanic_inspection_end_time = now
    rental.mechanic_inspection_status = "COMPLETED"
    if review_input and review_input.comment:
        rental.mechanic_inspection_comment = review_input.comment
    # Фиксируем конечные координаты осмотра по текущему положению автомобиля
    rental.mechanic_inspection_end_latitude = car.latitude
    rental.mechanic_inspection_end_longitude = car.longitude
    
    # Освобождаем автомобиль
    car.current_renter_id = None
    # При успешном завершении проверки автомобиль снова становится доступным (FREE)
    car.status = CarStatus.FREE
    add_review_if_exists(db, rental.id, review_input)
    
    # Окончательная блокировка двигателя при завершении проверки механиком
    try:
        if car and car.gps_imei:
            
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            # Универсальная последовательность: заблокировать двигатель
            result = await execute_gps_sequence(car.gps_imei, auth_token, "final_lock")
            if result["success"]:
                print(f"Двигатель автомобиля {car.name} окончательно заблокирован после завершения проверки механиком")
            else:
                print(f"Ошибка GPS последовательности при окончательной блокировке механиком: {result.get('error', 'Unknown error')}")
    except Exception as e:
        print(f"Ошибка GPS команд при окончательной блокировке механиком: {e}")
    
    try:
        db.commit()
        
        # try:
        #     name_parts = []
        #     if current_mechanic.first_name:
        #         name_parts.append(current_mechanic.first_name)
        #     if current_mechanic.middle_name:
        #         name_parts.append(current_mechanic.middle_name)
        #     if current_mechanic.last_name:
        #         name_parts.append(current_mechanic.last_name)
        #     full_name = " ".join(name_parts) if name_parts else "Не указано"
        #     
        #     login = current_mechanic.phone_number or "Не указан"
        #     
        #     await send_rental_complete_sms(
        #         client_phone=current_mechanic.phone_number,
        #         rent_id=str(rental.id),
        #         full_name=full_name,
        #         login=login,
        #         client_id=str(current_mechanic.id),
        #         digital_signature=current_mechanic.digital_signature or "Не указана",
        #         car_id=str(car.id),
        #         plate_number=car.plate_number,
        #         car_name=car.name
        #     )
        #     print(f"SMS отправлена механику {current_mechanic.phone_number} при завершении проверки")
        # except Exception as e:
        #     print(f"Ошибка отправки SMS при завершении проверки механиком: {e}")
        
        return {
            "message": "Проверка автомобиля успешно завершена",
            "rental_id": uuid_to_sid(rental.id),
            "rental_details": {
                "total_duration_minutes": int((now - rental.start_time).total_seconds() / 60),
                "final_total_price": rental.total_price
            },
            "review": {
                "rating": review_input.rating,
                "comment": review_input.comment
            }
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка при завершении проверки: {str(e)}")


@MechanicRouter.get("/inspection-history")
def get_inspection_history(
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Возвращает историю осмотров, проведенных текущим механиком.
    """
    try:
        # Получаем все осмотры, проведенные этим механиком
        inspections = (
            db.query(RentalHistory)
            .filter(
                RentalHistory.mechanic_inspector_id == current_mechanic.id,
                RentalHistory.mechanic_inspection_status.isnot(None)
            )
            .order_by(RentalHistory.mechanic_inspection_start_time.desc())
            .all()
        )
        
        inspections_data = []
        for inspection in inspections:
            car = db.query(Car).filter(Car.id == inspection.car_id).first()
            if not car:
                continue
                
            inspections_data.append({
                "id": uuid_to_sid(inspection.id),
                "car_id": uuid_to_sid(car.id),
                "car_name": car.name,
                "plate_number": car.plate_number,
                "inspection_start_time": inspection.mechanic_inspection_start_time.isoformat() if inspection.mechanic_inspection_start_time else None,
                "inspection_end_time": inspection.mechanic_inspection_end_time.isoformat() if inspection.mechanic_inspection_end_time else None,
                "inspection_status": inspection.mechanic_inspection_status,
                "inspection_comment": inspection.mechanic_inspection_comment,
                "mechanic_photos_before": inspection.mechanic_photos_before or [],
                "mechanic_photos_after": inspection.mechanic_photos_after or [],
                "rental_status": inspection.rental_status.value,
                "total_duration_minutes": int((inspection.mechanic_inspection_end_time - inspection.mechanic_inspection_start_time).total_seconds() / 60) if inspection.mechanic_inspection_start_time and inspection.mechanic_inspection_end_time else None
            })
        
        return {"inspections": inspections_data}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при получении истории осмотров: {str(e)}")


@MechanicRouter.get("/inspection-history/{rental_id}", summary="Детали конкретного осмотра по аренды")
def get_inspection_history_detail(
        rental_id: str,
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Возвращает детальную информацию по конкретному осмотру (аренде) для механика.
    Ожидает `rental_id` в формате SID.
    """
    try:
        rental_uuid = safe_sid_to_uuid(rental_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Некорректный rental_id")

    rental = (
        db.query(RentalHistory)
        .filter(
            RentalHistory.id == rental_uuid,
            RentalHistory.mechanic_inspector_id == current_mechanic.id
        )
        .first()
    )

    if not rental:
        raise HTTPException(status_code=404, detail="Осмотр не найден или недоступен")

    car = db.query(Car).filter(Car.id == rental.car_id).first()
    client = db.query(User).filter(User.id == rental.user_id).first()

    inspection_data = {
        "id": uuid_to_sid(rental.id),
        "mechanic_id": uuid_to_sid(current_mechanic.id),
        "mechanic_inspection_status": rental.mechanic_inspection_status,
        "mechanic_inspection_start_time": rental.mechanic_inspection_start_time.isoformat() if rental.mechanic_inspection_start_time else None,
        "mechanic_inspection_end_time": rental.mechanic_inspection_end_time.isoformat() if rental.mechanic_inspection_end_time else None,
        "mechanic_inspection_comment": rental.mechanic_inspection_comment,
        "mechanic_photos_before": rental.mechanic_photos_before or [],
        "mechanic_photos_after": rental.mechanic_photos_after or [],
        "client_photos_before": rental.photos_before or [],
        "client_photos_after": rental.photos_after or [],
        "rental_status": rental.rental_status.value if rental.rental_status else None,
        "rental_type": rental.rental_type.value if rental.rental_type else None,
        "duration": rental.duration,
        "start_time": rental.start_time.isoformat() if rental.start_time else None,
        "end_time": rental.end_time.isoformat() if rental.end_time else None,
        "charges": {
            "base_price": float(rental.base_price or 0),
            "open_fee": float(rental.open_fee or 0),
            "delivery_fee": float(rental.delivery_fee or 0),
            "waiting_fee": float(rental.waiting_fee or 0),
            "overtime_fee": float(rental.overtime_fee or 0),
            "distance_fee": float(rental.distance_fee or 0),
            "fuel_fee": float(getattr(rental, "fuel_fee", 0) or 0),
            "total_price": float(rental.total_price or 0),
        },
        "car": {
            "id": uuid_to_sid(car.id),
            "name": car.name,
            "plate_number": car.plate_number,
            "status": car.status.value if car.status else None,
            "color": car.color,
            "photos": sort_car_photos(car.photos or [])
        } if car else None,
        "client": {
            "id": uuid_to_sid(client.id),
            "first_name": client.first_name,
            "last_name": client.last_name,
            "phone_number": client.phone_number
        } if client else None
    }

    if rental.mechanic_inspection_start_time and rental.mechanic_inspection_end_time:
        inspection_data["inspection_duration_minutes"] = int(
            (rental.mechanic_inspection_end_time - rental.mechanic_inspection_start_time).total_seconds() / 60
        )
    else:
        inspection_data["inspection_duration_minutes"] = None

    return {"inspection": inspection_data}