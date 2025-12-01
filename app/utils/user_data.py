from sqlalchemy.orm import Session
from datetime import datetime
from typing import Dict, Any
from fastapi import HTTPException

from app.utils.short_id import uuid_to_sid, safe_sid_to_uuid
from app.models.contract_model import UserContractSignature, ContractFile, ContractType
from app.models.history_model import RentalHistory, RentalStatus, RentalReview
from app.models.car_model import Car
from app.models.user_model import UserRole, User
from app.models.application_model import Application, ApplicationStatus
from app.models.notification_model import Notification
from app.models.guarantor_model import Guarantor
from app.rent.utils.user_utils import get_user_available_auto_classes
from app.rent.utils.calculate_price import get_open_price
from app.owner.utils import calculate_month_availability_minutes, ALMATY_TZ
from app.admin.cars.utils import sort_car_photos
from app.core.config import logger
from app.utils.time_utils import get_local_time
import traceback


async def get_user_me_data(db: Session, current_user: User) -> Dict[str, Any]:
    # Получаем активную аренду и автомобиль
    # Для механиков ищем по mechanic_inspector_id, для обычных пользователей - по user_id
    if current_user.role == UserRole.MECHANIC:
        # Сначала ищем активный осмотр
        rental_with_car = (
            db.query(RentalHistory, Car)
            .join(Car, Car.id == RentalHistory.car_id)
            .filter(
                RentalHistory.mechanic_inspector_id == current_user.id,
                RentalHistory.mechanic_inspection_status.in_([
                    "PENDING",
                    "IN_USE",
                    "SERVICE"
                ])
            )
            .first()
        )
        
        # Если нет активного осмотра, ищем активную доставку
        if not rental_with_car:
            rental_with_car = (
                db.query(RentalHistory, Car)
                .join(Car, Car.id == RentalHistory.car_id)
                .filter(
                    RentalHistory.delivery_mechanic_id == current_user.id,
                    RentalHistory.rental_status.in_([
                        RentalStatus.DELIVERY_RESERVED,
                        RentalStatus.DELIVERING,
                        RentalStatus.DELIVERING_IN_PROGRESS
                    ])
                )
                .first()
            )
    else:
        rental_with_car = (
            db.query(RentalHistory, Car)
            .join(Car, Car.id == RentalHistory.car_id)
            .filter(
                RentalHistory.user_id == current_user.id,
                RentalHistory.rental_status.in_([
                    RentalStatus.RESERVED,
                    RentalStatus.IN_USE,
                    RentalStatus.DELIVERING,
                    RentalStatus.DELIVERY_RESERVED,
                    RentalStatus.DELIVERING_IN_PROGRESS
                ])
            )
            .first()
        )

    current_rental = None
    if rental_with_car:
        rental, car = rental_with_car

        # Для механиков используем mechanic_inspection_status, для обычных пользователей - rental_status
        if current_user.role == UserRole.MECHANIC:
            # Проверяем, это осмотр или доставка
            if rental.mechanic_inspector_id == current_user.id:
                # Это осмотр
                rental_details = {
                    "rental_id": uuid_to_sid(rental.id),
                    "reservation_time": rental.mechanic_inspection_start_time.isoformat() if rental.mechanic_inspection_start_time else None,
                    "start_time": rental.mechanic_inspection_start_time.isoformat() if rental.mechanic_inspection_start_time else None,
                    "rental_type": rental.rental_type.value if rental.rental_type else "minutes",
                    "duration": rental.duration,
                    "already_payed": 0,  # Для механиков всегда 0
                    "status": rental.mechanic_inspection_status
                }
            else:
                # Это доставка
                rental_details = {
                    "rental_id": uuid_to_sid(rental.id),
                    "reservation_time": rental.delivery_start_time.isoformat() if rental.delivery_start_time else None,
                    "start_time": rental.delivery_start_time.isoformat() if rental.delivery_start_time else None,
                    "rental_type": rental.rental_type.value if rental.rental_type else "minutes",
                    "duration": rental.duration,
                    "already_payed": 0,  # Для механиков всегда 0
                    "status": rental.rental_status.value,
                    "delivery_start_time": rental.delivery_start_time.isoformat() if rental.delivery_start_time else None,
                    "delivery_end_time": rental.delivery_end_time.isoformat() if rental.delivery_end_time else None
                }
        else:
            rental_details = {
                "rental_id": uuid_to_sid(rental.id),
                "reservation_time": rental.reservation_time.isoformat() if rental.reservation_time else None,
                "start_time": rental.start_time.isoformat() if rental.start_time else None,
                "rental_type": rental.rental_type.value,
                "duration": rental.duration,
                "already_payed": float(rental.already_payed or 0),
                "status": rental.rental_status.value,
                "delivery_start_time": rental.delivery_start_time.isoformat() if rental.delivery_start_time else None,
                "delivery_end_time": rental.delivery_end_time.isoformat() if rental.delivery_end_time else None
            }

        # Для механиков проверяем mechanic_inspection_status, для обычных пользователей - rental_status
        if current_user.role == UserRole.MECHANIC:
            # Для механиков логика доставки не применима
            current_mechanic = None
        elif rental.rental_status == RentalStatus.DELIVERING or rental.rental_status == RentalStatus.DELIVERING_IN_PROGRESS or rental.rental_status == RentalStatus.DELIVERY_RESERVED:
            # Рассчитываем время доставки если она началась
            delivery_duration_minutes = None
            if rental.delivery_start_time:
                delivery_duration_minutes = int((get_local_time() - rental.delivery_start_time).total_seconds() / 60)
            
            rental_details.update({
                "delivery_latitude": rental.delivery_latitude,
                "delivery_longitude": rental.delivery_longitude,
                "delivery_in_progress": rental.delivery_mechanic_id is not None,
                "delivery_start_time": rental.delivery_start_time.isoformat() if rental.delivery_start_time else None,
                "delivery_end_time": rental.delivery_end_time.isoformat() if rental.delivery_end_time else None,
                "delivery_duration_minutes": delivery_duration_minutes,
                "delivery_penalty_fee": rental.delivery_penalty_fee or 0
            })
        else:
            rental_details["delivery_in_progress"] = False

        if rental.delivery_mechanic_id:
            mech = db.get(User, rental.delivery_mechanic_id)
            current_mechanic = {
                "id": uuid_to_sid(mech.id),
                "first_name": mech.first_name,
                "last_name": mech.last_name,
                "phone_number": mech.phone_number
            } if mech else None
        else:
            current_mechanic = None

        # Для механиков добавляем current_renter_details
        car_details = {
            "id": uuid_to_sid(car.id),
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
            "photos": sort_car_photos(car.photos or []),
            "status": car.status,
            "price_per_minute": car.price_per_minute,
            "price_per_hour": car.price_per_hour,
            "price_per_day": car.price_per_day,
            "open_price": get_open_price(car),
            "owned_car": car.owner_id == current_user.id,
            "description": car.description,
            "current_renter_id": uuid_to_sid(car.current_renter_id) if car.current_renter_id else None,
            "vin": car.vin,
            "color": car.color,
        }
        
        # Для механиков добавляем поля статуса загрузки фотографий
        if current_user.role == UserRole.MECHANIC:
            # Проверяем, это осмотр или доставка
            if rental.mechanic_inspector_id == current_user.id:
                # Это осмотр - используем mechanic_photos_before/after
                # Проверяем по содержимому путей (аналогично /mechanic/start)
                before_photos = rental.mechanic_photos_before or []
                car_details["photo_before_selfie_uploaded"] = any(
                    ("/mechanic/before/selfie/" in p) or ("\\mechanic\\before\\selfie\\" in p) 
                    for p in before_photos
                )
                car_details["photo_before_car_uploaded"] = any(
                    ("/mechanic/before/car/" in p) or ("\\mechanic\\before\\car\\" in p) 
                    for p in before_photos
                )
                car_details["photo_before_interior_uploaded"] = any(
                    ("/mechanic/before/interior/" in p) or ("\\mechanic\\before\\interior\\" in p) 
                    for p in before_photos
                )
                
                # Проверяем фото ПОСЛЕ по содержимому путей
                after_photos = rental.mechanic_photos_after or []
                car_details["photo_after_selfie_uploaded"] = any(
                    ("/mechanic/after/selfie/" in p) or ("\\mechanic\\after\\selfie\\" in p) 
                    for p in after_photos
                )
                car_details["photo_after_car_uploaded"] = any(
                    ("/mechanic/after/car/" in p) or ("\\mechanic\\after\\car\\" in p) 
                    for p in after_photos
                )
                car_details["photo_after_interior_uploaded"] = any(
                    ("/mechanic/after/interior/" in p) or ("\\mechanic\\after\\interior\\" in p) 
                    for p in after_photos
                )
            else:
                # Это доставка - используем delivery_photos_before/after
                # Проверяем флаги загрузки фото ПЕРЕД доставкой по содержимому путей
                photo_before_selfie_uploaded = False
                photo_before_car_uploaded = False
                photo_before_interior_uploaded = False
                
                if rental.delivery_photos_before:
                    photos_before = rental.delivery_photos_before
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
                
                car_details["photo_before_selfie_uploaded"] = photo_before_selfie_uploaded
                car_details["photo_before_car_uploaded"] = photo_before_car_uploaded
                car_details["photo_before_interior_uploaded"] = photo_before_interior_uploaded
                
                # Проверяем флаги загрузки фото ПОСЛЕ доставки по содержимому путей
                photo_after_selfie_uploaded = False
                photo_after_car_uploaded = False
                photo_after_interior_uploaded = False
                
                if rental.delivery_photos_after:
                    photos_after = rental.delivery_photos_after
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
                
                car_details["photo_after_selfie_uploaded"] = photo_after_selfie_uploaded
                car_details["photo_after_car_uploaded"] = photo_after_car_uploaded
                car_details["photo_after_interior_uploaded"] = photo_after_interior_uploaded
                
                # Добавляем delivery_coordinates для доставки
                car_details["delivery_coordinates"] = {
                    "latitude": rental.delivery_latitude,
                    "longitude": rental.delivery_longitude,
                }
            
            # Добавляем rental_id для механиков
            car_details["rental_id"] = uuid_to_sid(rental.id)
            
            # Добавляем last_client_review для механиков
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
                    
                    car_details["last_client_review"] = {
                        "rating": client_review.rating,
                        "comment": client_review.comment,
                        "photos_after": {
                            "interior": interior_photos,
                            "exterior": exterior_photos
                        }
                    }
                else:
                    car_details["last_client_review"] = None
            else:
                car_details["last_client_review"] = None
        
        if current_user.role == UserRole.USER:
            photo_before_selfie_uploaded = False
            photo_before_car_uploaded = False
            photo_before_interior_uploaded = False
            
            if rental.photos_before:
                photos_before = rental.photos_before
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
            
            car_details["photo_before_selfie_uploaded"] = photo_before_selfie_uploaded
            car_details["photo_before_car_uploaded"] = photo_before_car_uploaded
            car_details["photo_before_interior_uploaded"] = photo_before_interior_uploaded
            
            photo_after_selfie_uploaded = False
            photo_after_car_uploaded = False
            photo_after_interior_uploaded = False
            
            if rental.photos_after:
                photos_after = rental.photos_after
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
            
            car_details["photo_after_selfie_uploaded"] = photo_after_selfie_uploaded
            car_details["photo_after_car_uploaded"] = photo_after_car_uploaded
            car_details["photo_after_interior_uploaded"] = photo_after_interior_uploaded
        
        # Для механиков добавляем current_renter_details
        if current_user.role == UserRole.MECHANIC and car.current_renter_id:
            car_details["current_renter_details"] = {
                "id": uuid_to_sid(car.current_renter_id),
                "phone_number": current_user.phone_number,
                "first_name": current_user.first_name,
                "last_name": current_user.last_name
            }
        
        current_rental = {
            "rental_details": rental_details,
            "car_details": car_details,
            "current_mechanic": current_mechanic
        }

    # Список машин, принадлежащих пользователю
    owned_cars_raw = db.query(Car).filter(Car.owner_id == current_user.id).all()
    owned_cars = []
    
    # Получаем текущий месяц и год
    now = datetime.now(ALMATY_TZ)
    current_month = now.month
    current_year = now.year
    
    for car in owned_cars_raw:
        # Рассчитываем доступные минуты для текущего месяца
        available_minutes = calculate_month_availability_minutes(
            car_id=uuid_to_sid(car.id),
            year=current_year,
            month=current_month,
            owner_id=current_user.id,
            db=db
        )
        
        owned_cars.append({
            "id": uuid_to_sid(car.id),
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
            "photos": sort_car_photos(car.photos or []),
            "description": car.description,
            "current_renter_id": uuid_to_sid(car.current_renter_id) if car.current_renter_id else None,
            "status": car.status,
            "price_per_minute": car.price_per_minute,
            "price_per_hour": car.price_per_hour,
            "price_per_day": car.price_per_day,
            "open_price": get_open_price(car),
            "available_minutes": available_minutes
        })

    # Подсчитываем количество непрочитанных уведомлений
    unread_messages = (
        db.query(Notification)
        .filter(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False)
        )
        .count()
    )

    try:
        user_application = db.query(Application).filter(Application.user_id == current_user.id).first()
        guarantors_query = (
            db.query(Guarantor, User)
            .join(User, User.id == Guarantor.guarantor_id)
            .filter(
                Guarantor.client_id == current_user.id,
                Guarantor.is_active == True
            )
            .all()
        )
        
        guarantors = []
        for guarantor_relation, guarantor_user in guarantors_query:
            # Проверяем, что гарант подписал оба договора
            guarantor_contract_signed = db.query(UserContractSignature).join(ContractFile).filter(
                UserContractSignature.user_id == guarantor_user.id,
                UserContractSignature.guarantor_relationship_id == guarantor_relation.id,
                ContractFile.contract_type == ContractType.GUARANTOR_CONTRACT
            ).first() is not None
            
            guarantor_main_contract_signed = db.query(UserContractSignature).join(ContractFile).filter(
                UserContractSignature.user_id == guarantor_user.id,
                UserContractSignature.guarantor_relationship_id == guarantor_relation.id,
                ContractFile.contract_type == ContractType.GUARANTOR_MAIN_CONTRACT
            ).first() is not None
            
            # Добавляем гарантора только если подписал оба договора
            if guarantor_contract_signed and guarantor_main_contract_signed:
                guarantors.append({
                    "id": uuid_to_sid(guarantor_user.id),
                    "first_name": guarantor_user.first_name,
                    "last_name": guarantor_user.last_name,
                    "middle_name": guarantor_user.middle_name,
                    "phone_number": guarantor_user.phone_number,
                    "auto_class": guarantor_user.auto_class or []
                })
        
        guarantors_count = len(guarantors)
        
        # Получаем доступные классы авто пользователя (с учетом гаранта)
        available_auto_classes = get_user_available_auto_classes(current_user, db)

        first_name = current_user.first_name if isinstance(current_user.first_name, str) else None
        last_name = current_user.last_name if isinstance(current_user.last_name, str) else None
        role = getattr(current_user.role, "value", current_user.role) if current_user.role is not None else None

        main_contract_signed = False
        rental_main_contract_signed = False
        appendix_7_1_signed = False
        appendix_7_2_signed = False

        if current_user.role in [UserRole.USER, UserRole.MECHANIC]:
            main_contract_signed = db.query(UserContractSignature).join(ContractFile).filter(
                UserContractSignature.user_id == current_user.id,
                ContractFile.contract_type == ContractType.MAIN_CONTRACT
            ).first() is not None

            if current_rental:
                rental_id = current_rental["rental_details"].get("rental_id") if "rental_details" in current_rental else None
                if rental_id:
                    rental_uuid = safe_sid_to_uuid(rental_id)

                    rental_main_contract_signed = db.query(UserContractSignature).join(ContractFile).filter(
                        UserContractSignature.user_id == current_user.id,
                        UserContractSignature.rental_id == rental_uuid,
                        ContractFile.contract_type == ContractType.RENTAL_MAIN_CONTRACT
                    ).first() is not None
                    
                    appendix_7_1_signed = db.query(UserContractSignature).join(ContractFile).filter(
                        UserContractSignature.user_id == current_user.id,
                        UserContractSignature.rental_id == rental_uuid,
                        ContractFile.contract_type == ContractType.APPENDIX_7_1
                    ).first() is not None
                    
                    appendix_7_2_signed = db.query(UserContractSignature).join(ContractFile).filter(
                        UserContractSignature.user_id == current_user.id,
                        UserContractSignature.rental_id == rental_uuid,
                        ContractFile.contract_type == ContractType.APPENDIX_7_2
                    ).first() is not None

        response_data = {
            "id": uuid_to_sid(current_user.id),
            "user_id": uuid_to_sid(current_user.id),
            "phone_number": current_user.phone_number,
            "email": current_user.email,
            "first_name": first_name,
            "last_name": last_name,
            "middle_name": current_user.middle_name,
            "iin": current_user.iin,
            "passport_number": current_user.passport_number,
            "birth_date": current_user.birth_date.isoformat() if current_user.birth_date else None,
            "role": role,
            "is_verified_email": getattr(current_user, "is_verified_email", False),
            "is_citizen_kz": getattr(current_user, "is_citizen_kz", False),
            "wallet_balance": float(current_user.wallet_balance or 0.0),
            "current_rental": current_rental,
            "owned_cars": owned_cars,
            "locale": current_user.locale,
            "unread_message": unread_messages,
            "guarantors_count": guarantors_count,
            "guarantors": guarantors,
            "auto_class": current_user.auto_class or [],
            "available_auto_classes": available_auto_classes,
            "application": {
                "reason": getattr(user_application, "reason", None) if user_application else None,
                "financier_status": user_application.financier_status.value if user_application and user_application.financier_status else None,
                "mvd_status": user_application.mvd_status.value if user_application and user_application.mvd_status else None,
                "financier_approved_at": user_application.financier_approved_at.isoformat() if user_application and user_application.financier_approved_at else None,
                "financier_rejected_at": user_application.financier_rejected_at.isoformat() if user_application and user_application.financier_rejected_at else None,
                "mvd_approved_at": user_application.mvd_approved_at.isoformat() if user_application and user_application.mvd_approved_at else None,
                "mvd_rejected_at": user_application.mvd_rejected_at.isoformat() if user_application and user_application.mvd_rejected_at else None,
            },
            "documents": {
                "documents_verified": current_user.documents_verified,
                "selfie_with_license_url": current_user.selfie_with_license_url,
                "selfie_url": current_user.selfie_url,
                "psych_neurology_certificate_url": getattr(current_user, "psych_neurology_certificate_url", None),
                "narcology_certificate_url": getattr(current_user, "narcology_certificate_url", None),
                "pension_contributions_certificate_url": getattr(current_user, "pension_contributions_certificate_url", None),
                "drivers_license": {
                    "url": current_user.drivers_license_url,
                    "expiry": current_user.drivers_license_expiry.isoformat()
                    if current_user.drivers_license_expiry else None,
                },
                "id_card": {
                    "front_url": current_user.id_card_front_url,
                    "back_url": current_user.id_card_back_url,
                    "expiry": current_user.id_card_expiry.isoformat()
                    if current_user.id_card_expiry else None,
                }
            },
            "is_consent_to_data_processing": current_user.is_consent_to_data_processing,
            "is_contract_read": current_user.is_contract_read,
            "is_user_agreement": current_user.is_user_agreement,
            "upload_document_at": current_user.upload_document_at.isoformat() if current_user.upload_document_at else None,
            "main_contract_signed": main_contract_signed,  # Договор о присоединении
            "rental_main_contract_signed": rental_main_contract_signed,  # Основной договор аренды (только для активной аренды)
            "appendix_7_1_signed": appendix_7_1_signed,  # Акт приема (только для активной аренды)
            "appendix_7_2_signed": appendix_7_2_signed,  # Акт возврата (только для активной аренды)
        }

        if not current_user.is_contract_read:
            full_name_parts = []
            if first_name:
                full_name_parts.append(first_name)
            if last_name:
                full_name_parts.append(last_name)
            if current_user.middle_name:
                full_name_parts.append(current_user.middle_name)
            full_name = " ".join(full_name_parts) if full_name_parts else None
            
            response_data.update({
                "full_name": full_name,
                "login": current_user.phone_number, 
                "client_uuid": str(current_user.id),  
                "digital_signature": current_user.digital_signature
            })

        if current_rental and (current_user.role in [UserRole.USER, UserRole.ADMIN, UserRole.MECHANIC] or guarantors_count > 0):
            rental_id = current_rental["rental_details"].get("rental_id") if "rental_details" in current_rental else None
            if rental_id:
                # Сначала проверяем основной договор аренды
                if not rental_main_contract_signed:
                    car_details = current_rental.get("car_details", {})
                    
                    if 'full_name' not in locals():
                        full_name_parts = []
                        if first_name:
                            full_name_parts.append(first_name)
                        if last_name:
                            full_name_parts.append(last_name)
                        if current_user.middle_name:
                            full_name_parts.append(current_user.middle_name)
                        full_name = " ".join(full_name_parts) if full_name_parts else None
                    
                    response_data.update({
                        "full_name": full_name,
                        "login": current_user.phone_number,
                        "client_uuid": str(current_user.id),
                        "digital_signature": current_user.digital_signature,
                        "rent_uuid": str(safe_sid_to_uuid(rental_id)),
                        "plate_number": car_details.get("plate_number"),
                        "car_uuid": str(safe_sid_to_uuid(car_details.get("id"))),
                        "car_year": car_details.get("year"),
                        "body_type": car_details.get("body_type"),
                        "vin": car_details.get("vin"),
                        "color": car_details.get("color")
                    })
                
                # Затем проверяем приложение 7.1 (только если основной договор аренды подписан)
                elif not appendix_7_1_signed:
                    car_details = current_rental.get("car_details", {})
                    
                    if 'full_name' not in locals():
                        full_name_parts = []
                        if first_name:
                            full_name_parts.append(first_name)
                        if last_name:
                            full_name_parts.append(last_name)
                        if current_user.middle_name:
                            full_name_parts.append(current_user.middle_name)
                        full_name = " ".join(full_name_parts) if full_name_parts else None
                    
                    response_data.update({
                        "full_name": full_name,
                        "login": current_user.phone_number,
                        "client_uuid": str(current_user.id),
                        "digital_signature": current_user.digital_signature,
                        "rent_uuid": str(safe_sid_to_uuid(rental_id)),
                        "plate_number": car_details.get("plate_number"),
                        "car_uuid": str(safe_sid_to_uuid(car_details.get("id"))),
                        "car_year": car_details.get("year"),
                        "body_type": car_details.get("body_type"),
                        "vin": car_details.get("vin"),
                        "color": car_details.get("color")
                    })
                
                # И наконец проверяем приложение 7.2 (только если основной договор аренды и приложение 7.1 подписаны)
                elif not appendix_7_2_signed:
                    car_details = current_rental.get("car_details", {})
                    
                    if 'full_name' not in locals():
                        full_name_parts = []
                        if first_name:
                            full_name_parts.append(first_name)
                        if last_name:
                            full_name_parts.append(last_name)
                        if current_user.middle_name:
                            full_name_parts.append(current_user.middle_name)
                        full_name = " ".join(full_name_parts) if full_name_parts else None
                    
                    response_data.update({
                        "full_name": full_name,
                        "login": current_user.phone_number,
                        "client_uuid": str(current_user.id),
                        "digital_signature": current_user.digital_signature,
                        "rent_uuid": str(safe_sid_to_uuid(rental_id)),
                        "plate_number": car_details.get("plate_number"),
                        "car_uuid": str(safe_sid_to_uuid(car_details.get("id"))),
                        "car_year": car_details.get("year"),
                        "body_type": car_details.get("body_type"),
                        "vin": car_details.get("vin"),
                        "color": car_details.get("color")
                    })

        # Проверяем завершенную аренду и не подписан ли аппендикс 7.2
        # Также проверяем для пользователей с гарантом (guarantors_count > 0)
        if current_user.role in [UserRole.USER, UserRole.ADMIN, UserRole.MECHANIC] or guarantors_count > 0:
            last_completed_rental = db.query(RentalHistory).filter(
                RentalHistory.user_id == current_user.id,
                RentalHistory.rental_status == RentalStatus.COMPLETED
            ).order_by(RentalHistory.end_time.desc()).first()
            
            if last_completed_rental:
                appendix_7_2_signed = db.query(UserContractSignature).join(ContractFile).filter(
                    UserContractSignature.user_id == current_user.id,
                    UserContractSignature.rental_id == last_completed_rental.id,
                    ContractFile.contract_type == ContractType.APPENDIX_7_2
                ).first() is not None
                
                if not appendix_7_2_signed:
                    car = db.query(Car).filter(Car.id == last_completed_rental.car_id).first()
                    
                    if car:
                        if 'full_name' not in locals():
                            full_name_parts = []
                            if first_name:
                                full_name_parts.append(first_name)
                            if last_name:
                                full_name_parts.append(last_name)
                            if current_user.middle_name:
                                full_name_parts.append(current_user.middle_name)
                            full_name = " ".join(full_name_parts) if full_name_parts else None
                        
                        # Используем rent_uuid от активной аренды, если она есть, иначе от последней завершенной
                        rent_uuid_to_use = None
                        if current_rental:
                            rental_id = current_rental["rental_details"].get("rental_id")
                            if rental_id:
                                rent_uuid_to_use = safe_sid_to_uuid(rental_id)
                        else:
                            rent_uuid_to_use = last_completed_rental.id
                        
                        response_data.update({
                            "full_name": full_name,
                            "login": current_user.phone_number,
                            "client_uuid": str(current_user.id),
                            "digital_signature": current_user.digital_signature,
                            "rent_uuid": str(rent_uuid_to_use),
                            "plate_number": car.plate_number,
                            "car_uuid": str(car.id),
                            "car_year": car.year,
                            "body_type": car.body_type,
                            "vin": car.vin,
                            "color": car.color
                        })

    except Exception as e:
        logger.error(f"Error in get_user_me_data: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal Server Error")

    return response_data

