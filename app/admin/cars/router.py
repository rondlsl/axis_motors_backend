from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
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
from app.models.car_model import Car, CarStatus, CarBodyType, TransmissionType
from app.models.car_comment_model import CarComment
from app.models.history_model import RentalHistory, RentalStatus, RentalReview
from app.models.rental_actions_model import RentalAction
from app.models.contract_model import UserContractSignature
from app.models.wallet_transaction_model import WalletTransaction
from app.admin.cars.schemas import (
    CarDetailSchema, CarEditSchema, CarCommentSchema, 
    CarCommentCreateSchema, CarCommentUpdateSchema,
    CarAvailabilityTimerSchema, CarCurrentUserSchema,
    CarListResponseSchema, CarMapResponseSchema, CarStatisticsSchema,
    CarListItemSchema, CarMapItemSchema, OwnerSchema, CurrentRenterSchema
)
from app.admin.cars.utils import car_to_detail_schema, status_display, _get_drive_type_display, sort_car_photos
from app.gps_api.utils.route_data import get_gps_route_data
from app.gps_api.utils.auth_api import get_auth_token
from app.gps_api.utils.car_data import send_open, send_close, send_give_key, send_take_key, send_lock_engine, send_unlock_engine
from app.gps_api.utils.glonassoft_client import glonassoft_client
from app.gps_api.utils.telemetry_processor import process_glonassoft_data
from app.core.config import GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD, logger
from app.models.support_action_model import SupportAction
from app.utils.plate_normalizer import normalize_plate_number
from app.utils.telegram_logger import log_error_to_telegram
from app.websocket.notifications import notify_vehicles_list_update, notify_user_status_update
from app.utils.time_utils import get_local_time
from app.owner.availability import update_car_availability_snapshot
from app.owner.router import calculate_owner_earnings, calculate_fuel_cost, calculate_delivery_cost
import asyncio
import uuid
from app.models.contract_model import UserContractSignature, ContractFile, ContractType

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
    body: CarEditSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Редактировать автомобиль"""
    if current_user.role not in [UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    update_fields = body.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        if field == "status" and value is not None:
            setattr(car, "status", value.value)
        else:
            setattr(car, field, value)

    db.commit()
    db.refresh(car)

    return car_to_detail_schema(car, db)


@cars_router.get("/{car_id}/details", response_model=CarDetailSchema)
async def get_car_details(
    car_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> CarDetailSchema:
    """Получить детальную информацию об автомобиле"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

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
        owner_id=uuid_to_sid(car.owner_id) if car.owner_id else None,
        current_renter_id=uuid_to_sid(car.current_renter_id) if car.current_renter_id else None,
        owner=owner_obj,
        current_renter=current_renter_obj,
        available_minutes=available_minutes,
        gps_id=car.gps_id,
        gps_imei=car.gps_imei,
        vin=car.vin,
        color=car.color,
        rating=car.rating,
        reservationtime=reservation_time_str,
    )


@cars_router.get("", response_model=Dict[str, List[Dict[str, Any]]])
async def get_all_cars_for_admin(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение всех автомобилей для админ панели"""
    
    if current_user.role != UserRole.ADMIN:
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
    
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
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
        
        return {
            "message": "Статус автомобиля успешно изменен",
            "car_name": car.name,
            "old_status": old_status.value if old_status else None,
            "new_status": new_status.value
        }
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


@cars_router.get("/{car_id}/status", summary="Получить текущий статус автомобиля")
async def get_car_status(
    car_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Получить текущий статус автомобиля"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Только администраторы могут получать статус автомобилей")
    
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
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Только администраторы могут удалять автомобили")
    
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
        
        db.delete(car)
        db.commit()
        
        return {
            "message": "Автомобиль успешно удален",
            "deleted_car": car_info
        }
        
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
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Только администраторы могут получать список статусов")
    
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
    Возвращает информацию по всем месяцам, в которых были поездки.
    """
    from calendar import monthrange
    from collections import defaultdict
    
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    # Получаем все завершенные поездки для машины
    rentals = db.query(RentalHistory).filter(
        RentalHistory.car_id == car.id,
        RentalHistory.rental_status == RentalStatus.COMPLETED,
        RentalHistory.end_time.isnot(None)
    ).all()
    
    # Группируем поездки по месяцам
    monthly_data = defaultdict(lambda: {
        "total_income": 0,
        "base_earnings": 0.0,
        "deductions": 0.0,
        "trips_count": 0
    })
    
    for r in rentals:
        if not r.end_time:
            continue
        month_key = (r.end_time.year, r.end_time.month)
        monthly_data[month_key]["trips_count"] += 1
        monthly_data[month_key]["total_income"] += int(r.total_price or 0)
        
        if r.user_id == car.owner_id:
            fuel_cost = calculate_fuel_cost(r, car, current_user)
            delivery_cost = calculate_delivery_cost(r, car, current_user)
            monthly_data[month_key]["deductions"] += (fuel_cost or 0) + (delivery_cost or 0)
        else:
            components = calculate_owner_earnings(r, car, current_user, return_components=True)
            monthly_data[month_key]["base_earnings"] += components["base_earnings"]
    
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
        owner_income = int(data["base_earnings"] * 0.5 * 0.97) - int(data["deductions"])
        
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
    """Список поездок автомобиля за выбранный месяц с пагинацией"""
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
        .join(User, User.id == RentalHistory.user_id)
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

    def get_status_display(status):
        status_map = {
            "reserved": "Забронирована",
            "in_use": "В аренде",
            "completed": "Завершена",
            "cancelled": "Отменена",
            "delivering": "Доставка",
            "delivering_in_progress": "Доставляется",
            "delivery_reserved": "Доставка забронирована",
            "scheduled": "Запланирована",
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
        
        items.append({
            "rental_id": uuid_to_sid(r.id),
            "rental_status": rental_status_value,
            "status_display": get_status_display(rental_status_value),
            "reservation_time": r.reservation_time.isoformat() if r.reservation_time else None,
            "start_date": r.start_time.isoformat() if r.start_time else None,
            "end_date": r.end_time.isoformat() if r.end_time else None,
            "duration_minutes": duration_minutes,
            "tariff": r.rental_type.value if r.rental_type else None,
            "tariff_display": tariff_display,
            "total_price": r.total_price,
            "renter": {
                "id": uuid_to_sid(renter.id),
                "first_name": renter.first_name,
                "last_name": renter.last_name,
                "phone_number": renter.phone_number,
                "selfie": renter.selfie_url,
            }
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

    # Данные маршрута (если доступны gps_id и времена)
    route_data = None
    try:
        if car and car.gps_id and rental.start_time and rental.end_time:
            route = await get_gps_route_data(
                device_id=car.gps_id,
                start_date=rental.start_time.isoformat() if rental.start_time else None,
                end_date=rental.end_time.isoformat() if rental.end_time else None
            )
            route_data = route.dict() if route else None
    except Exception:
        route_data = None

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

    result = {
        "rental_id": uuid_to_sid(rental.id),
        "car_name": car.name,
        "plate_number": car.plate_number,
        "reservation_time": rental.reservation_time.isoformat() if rental.reservation_time else None,
        "start_time": rental.start_time.isoformat() if rental.start_time else None,
        "end_time": rental.end_time.isoformat() if rental.end_time else None,
        "duration": rental.duration,  # Длительность аренды в часах/днях
        "duration_minutes": int((rental.end_time - rental.start_time).total_seconds() // 60) if rental.start_time and rental.end_time else 0,
        "already_payed": rental.already_payed,
        "total_price": rental.total_price,
        "total_price_without_fuel": total_price_without_fuel,
        "rental_status": rental.rental_status.value,
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
        "fuel_before": rental.fuel_before,
        "fuel_after": rental.fuel_after,
        "fuel_after_main_tariff": rental.fuel_after_main_tariff,
        
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
        "route_map": {
            "start_latitude": rental.start_latitude,
            "start_longitude": rental.start_longitude,
            "end_latitude": rental.end_latitude,
            "end_longitude": rental.end_longitude,
            "route_data": route_data
        },
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

    return result


@cars_router.get("/map", response_model=CarMapResponseSchema)
async def get_cars_map(
    status: Optional[CarStatus] = None,
    search_query: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> CarMapResponseSchema:
    """Карта автопарка: вернуть все машины с координатами и статусами"""
    if current_user.role != UserRole.ADMIN:
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
    if current_user.role != UserRole.ADMIN:
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
    if current_user.role != UserRole.ADMIN:
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
    if current_user.role != UserRole.ADMIN:
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
    db.refresh(car)

    return {
        "message": "Автомобиль успешно обновлен",
        "car_id": uuid_to_sid(car.id),
        "updated_fields": list(update_data.keys())
    }



@cars_router.post("/{car_id}/photos")
async def upload_car_photos(
    car_id: str,
    photos: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Загрузка фотографий автомобиля (append к существующим car.photos)"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    saved_paths: List[str] = []
    # Используем plate_number для создания директории (как в файловой системе)
    normalized_plate = normalize_plate_number(car.plate_number) if car.plate_number else str(car.id)
    base_dir = os.path.join("uploads", "cars", normalized_plate)
    os.makedirs(base_dir, exist_ok=True)

    for f in photos:
        # Получаем оригинальное имя файла
        original_filename = f.filename or "photo.jpg"
        # Обрабатываем имя файла для предотвращения конфликтов
        filename = original_filename
        file_path = os.path.join(base_dir, filename)
        
        # Если файл уже существует, добавляем номер к имени
        counter = 1
        while os.path.exists(file_path):
            name, ext = os.path.splitext(original_filename)
            filename = f"{name}_{counter}{ext}"
            file_path = os.path.join(base_dir, filename)
            counter += 1
        
        # Сохраняем файл
        with open(file_path, "wb") as buffer:
            content = await f.read()
            buffer.write(content)
        
        # Нормализуем путь для сохранения в БД
        normalized = file_path.replace("\\", "/")
        if not normalized.startswith("/"):
            normalized = "/" + normalized.lstrip("/")
        saved_paths.append(normalized)

    existing = car.photos or []
    car.photos = existing + saved_paths
    db.commit()
    db.refresh(car)

    return {
        "message": "Фотографии добавлены",
        "car_id": uuid_to_sid(car.id),
        "added": saved_paths,
        "total_photos": len(car.photos or [])
    }


@cars_router.delete("/{car_id}/photos", summary="Удалить все фотографии автомобиля")
async def delete_car_photos(
    car_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Удалить все фотографии автомобиля из базы данных и с файловой системы"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    try:
        # Путь к директории с фотографиями автомобиля (используем plate_number)
        normalized_plate = normalize_plate_number(car.plate_number) if car.plate_number else str(car.id)
        photos_dir = os.path.join("uploads", "cars", normalized_plate)
        
        deleted_files = []
        
        # Удаляем только файлы из директории
        if os.path.exists(photos_dir):
            for filename in os.listdir(photos_dir):
                file_path = os.path.join(photos_dir, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    deleted_files.append(filename)
        
        # Также удаляем файлы, на которые есть ссылки в car.photos (на случай если пути отличаются)
        if car.photos:
            for photo_path in car.photos:
                # Убираем ведущий слеш если есть
                photo_path_clean = photo_path.lstrip("/").lstrip("\\")
                if os.path.exists(photo_path_clean):
                    try:
                        os.remove(photo_path_clean)
                        deleted_files.append(os.path.basename(photo_path_clean))
                    except OSError:
                        pass
        
        # Очищаем поле photos в базе данных
        deleted_count = len(car.photos or [])
        car.photos = []
        db.commit()
        db.refresh(car)

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
    if current_user.role != UserRole.ADMIN:
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

BASE_URL = "https://regions.glonasssoft.ru"


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
