from fastapi import APIRouter, Depends, HTTPException, Query, Form
from sqlalchemy.orm import Session, joinedload, aliased
from sqlalchemy import and_, or_, func, case, desc, distinct, select, String
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from decimal import Decimal
import uuid
from app.models.notification_model import Notification

from app.utils.short_id import safe_sid_to_uuid, uuid_to_sid
from app.utils.sid_converter import convert_uuid_response_to_sid

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.application_model import Application, ApplicationStatus
from app.models.history_model import RentalHistory, RentalStatus, RentalReview
from app.models.car_model import Car
from app.models.guarantor_model import GuarantorRequest
from app.models.wallet_transaction_model import WalletTransaction, WalletTransactionType
from app.models.rental_actions_model import RentalAction
from app.models.contract_model import UserContractSignature, ContractFile
import base64
import os
from app.admin.users.schemas import (
    UserProfileSchema, UserRoleUpdateSchema, UserCardSchema, 
    UserListSchema, UserMapPositionSchema, UserCommentUpdateSchema,
    UserSearchFiltersSchema, GuarantorInfoSchema, TripSummarySchema,
    TripListItemSchema, TripDetailSchema, OwnerCarListItemSchema,
    UserEditSchema, UserBlockSchema, CompanyBonusSchema, SanctionPenaltySchema,
    DeleteRentalsRequestSchema, UserPaginatedResponse,
    WalletTransactionPaginationSchema, RentalHistoryUpdateSchema, RentalCreateSchema,
    BalanceTopUpSchema, AutoClassUpdateSchema
)
from math import ceil
from app.owner.router import calculate_owner_earnings
from app.admin.cars.utils import sort_car_photos
from app.utils.telegram_logger import log_error_to_telegram
from app.push.utils import send_push_to_user_by_id, send_localized_notification_to_user, send_localized_notification_to_user_async, user_has_push_tokens
from app.websocket.notifications import notify_user_status_update
from app.utils.time_utils import get_local_time
import asyncio

users_router = APIRouter(tags=["Admin Users"])


@users_router.get("/pending", response_model=List[UserProfileSchema])
async def get_pending_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение пользователей, ожидающих одобрения"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    users = db.query(User).filter(User.role == UserRole.PENDING).all()
    
    result = []
    for user in users:
        user_data = {
            "id": uuid_to_sid(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "middle_name": user.middle_name,
            "phone_number": user.phone_number,
            "role": user.role.value,
            "is_active": user.is_active,
            "is_verified_email": user.is_verified_email,
            "is_citizen_kz": user.is_citizen_kz,
            "documents_verified": user.documents_verified,
            "selfie_url": user.selfie_url,
            "selfie_with_license_url": user.selfie_with_license_url,
            "drivers_license_url": user.drivers_license_url,
            "id_card_front_url": user.id_card_front_url,
            "id_card_back_url": user.id_card_back_url,
            "psych_neurology_certificate_url": user.psych_neurology_certificate_url,
            "narcology_certificate_url": user.narcology_certificate_url,
            "pension_contributions_certificate_url": user.pension_contributions_certificate_url,
            "auto_class": user.auto_class or [],
            "rating": float(user.rating) if user.rating else None
        }
        
        converted_data = convert_uuid_response_to_sid(user_data, ["id"])
        result.append(UserProfileSchema(**converted_data))
    
    return result


@users_router.post("/{user_id}/approve")
async def approve_or_reject_user(
    user_id: str,
    approved: bool,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Одобрение или отклонение пользователя"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    if approved:
        user.role = UserRole.CLIENT
        user.documents_verified = True
        
        application = Application(
            user_id=user.id,
            status=ApplicationStatus.APPROVED,
            created_at=get_local_time()
        )
        db.add(application)
        
        message = "Пользователь одобрен"
    else:
        user.role = UserRole.REJECTED
        message = "Пользователь отклонен"
    
    db.commit()
    
    return {"message": message}


@users_router.get("/all", response_model=List[UserProfileSchema])
async def get_all_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение всех пользователей"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    users = db.query(User).all()
    
    result = []
    for user in users:
        user_data = {
            "id": uuid_to_sid(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "middle_name": user.middle_name,
            "phone_number": user.phone_number,
            "role": user.role.value,
            "is_active": user.is_active,
            "is_verified_email": user.is_verified_email,
            "is_citizen_kz": user.is_citizen_kz,
            "documents_verified": user.documents_verified,
            "selfie_url": user.selfie_url,
            "selfie_with_license_url": user.selfie_with_license_url,
            "drivers_license_url": user.drivers_license_url,
            "id_card_front_url": user.id_card_front_url,
            "id_card_back_url": user.id_card_back_url,
            "psych_neurology_certificate_url": user.psych_neurology_certificate_url,
            "narcology_certificate_url": user.narcology_certificate_url,
            "pension_contributions_certificate_url": user.pension_contributions_certificate_url,
            "auto_class": user.auto_class or [],
            "rating": float(user.rating) if user.rating else None
        }
        
        converted_data = convert_uuid_response_to_sid(user_data, ["id"])
        result.append(UserProfileSchema(**converted_data))
    
    return result


@users_router.get("/clients", response_model=List[UserProfileSchema])
async def get_all_clients(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение всех клиентов"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    users = db.query(User).filter(User.role == UserRole.CLIENT).all()
    
    result = []
    for user in users:
        user_data = {
            "id": uuid_to_sid(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "middle_name": user.middle_name,
            "phone_number": user.phone_number,
            "role": user.role.value,
            "is_active": user.is_active,
            "is_verified_email": user.is_verified_email,
            "is_citizen_kz": user.is_citizen_kz,
            "documents_verified": user.documents_verified,
            "selfie_url": user.selfie_url,
            "selfie_with_license_url": user.selfie_with_license_url,
            "drivers_license_url": user.drivers_license_url,
            "id_card_front_url": user.id_card_front_url,
            "id_card_back_url": user.id_card_back_url,
            "psych_neurology_certificate_url": user.psych_neurology_certificate_url,
            "narcology_certificate_url": user.narcology_certificate_url,
            "pension_contributions_certificate_url": user.pension_contributions_certificate_url,
            "auto_class": user.auto_class or [],
            "rating": float(user.rating) if user.rating else None
        }
        
        converted_data = convert_uuid_response_to_sid(user_data, ["id"])
        result.append(UserProfileSchema(**converted_data))
    
    return result


@users_router.patch("/{user_id}/role")
async def update_employee_role(
    user_id: str,
    role_data: UserRoleUpdateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Обновление роли сотрудника"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    db.commit()
    
    return {"message": f"Роль пользователя изменена на {role_data.role.value}"}


# === User Profile ===
@users_router.get("/{user_id}/profile", response_model=UserProfileSchema)
async def get_user_profile(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> UserProfileSchema:
    """Получить профиль пользователя"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    try:
        user_uuid = safe_sid_to_uuid(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат ID")

    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    auto_class_list = []
    if user.auto_class:
        if isinstance(user.auto_class, list):
            auto_class_list = user.auto_class
        elif isinstance(user.auto_class, str):
            raw = user.auto_class.strip()
            if raw.startswith("{") and raw.endswith("}"):
                raw = raw[1:-1]
            auto_class_list = [part.strip() for part in raw.split(",") if part.strip()]

    return UserProfileSchema(
        id=user.sid,
        email=user.email,
        phone_number=user.phone_number,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role.value,
        is_active=user.is_active,
        is_verified_email=user.is_verified_email,
        is_citizen_kz=user.is_citizen_kz,
        documents_verified=user.documents_verified,
        selfie_url=user.selfie_url,
        selfie_with_license_url=user.selfie_with_license_url,
        drivers_license_url=user.drivers_license_url,
        id_card_front_url=user.id_card_front_url,
        id_card_back_url=user.id_card_back_url,
        psych_neurology_certificate_url=user.psych_neurology_certificate_url,
        narcology_certificate_url=user.narcology_certificate_url,
        pension_contributions_certificate_url=user.pension_contributions_certificate_url,
        auto_class=auto_class_list,
        digital_signature=user.digital_signature,
        rating=float(user.rating) if user.rating else None
    )


def _get_mvd_approved_status(user: User, db: Session) -> bool:
    """Определяет, одобрен ли пользователь МВД"""
    # Если роль USER - точно одобрен
    if user.role == UserRole.USER:
        return True
    
    application = db.query(Application).filter(Application.user_id == user.id).first()
    if application and application.mvd_status == ApplicationStatus.APPROVED:
        return True
    
    return False


def _get_current_rental_car(user: User, db: Session) -> Optional[Dict[str, Any]]:
    """Получает информацию о текущей аренде пользователя"""
    active_rental = db.query(RentalHistory).filter(
        and_(
            RentalHistory.user_id == user.id,
            RentalHistory.rental_status.in_([
                RentalStatus.IN_USE, 
                RentalStatus.DELIVERING, 
                RentalStatus.DELIVERING_IN_PROGRESS
            ])
        )
    ).first()
    
    if not active_rental:
        return None
    
    car = db.query(Car).filter(Car.id == active_rental.car_id).first()
    if not car:
        return None
    
    return {
        "id": uuid_to_sid(car.id),
        "name": car.name,
        "plate_number": car.plate_number,
        "brand": car.name.split()[0] if car.name else "Unknown",
        "photos": car.photos
    }


def _calculate_owner_earnings(user: User, db: Session) -> Dict[str, float]:
    """Рассчитывает заработок владельца"""
    if user.role not in [UserRole.USER]:  # Только для одобренных пользователей
        return {"current_month": 0.0, "total": 0.0}
    
    owned_cars = db.query(Car).filter(Car.owner_id == user.id).all()
    if not owned_cars:
        return {"current_month": 0.0, "total": 0.0}
    
    car_ids = [car.id for car in owned_cars]
    
    # Текущий месяц
    now = datetime.now()
    current_month_start = datetime(now.year, now.month, 1)
    
    # Заработок за текущий месяц
    current_month_rentals = db.query(RentalHistory).filter(
        and_(
            RentalHistory.car_id.in_(car_ids),
            RentalHistory.rental_status == RentalStatus.COMPLETED,
            RentalHistory.end_time >= current_month_start,
            RentalHistory.user_id != user.id  # Исключаем поездки самого владельца
        )
    ).all()
    
    current_month_earnings = 0.0
    for rental in current_month_rentals:
        car = next((c for c in owned_cars if c.id == rental.car_id), None)
        if car:
            earnings = calculate_owner_earnings(rental, car, user)
            current_month_earnings += earnings
    
    # Общий заработок
    total_rentals = db.query(RentalHistory).filter(
        and_(
            RentalHistory.car_id.in_(car_ids),
            RentalHistory.rental_status == RentalStatus.COMPLETED,
            RentalHistory.user_id != user.id
        )
    ).all()
    
    total_earnings = 0.0
    for rental in total_rentals:
        car = next((c for c in owned_cars if c.id == rental.car_id), None)
        if car:
            earnings = calculate_owner_earnings(rental, car, user)
            total_earnings += earnings
    
    return {"current_month": current_month_earnings, "total": total_earnings}


@users_router.get("/list", response_model=UserPaginatedResponse)
async def get_users_list(
    role: Optional[str] = Query(None, description="Фильтр по роли"),
    search_query: Optional[str] = Query(None, description="Поиск по имени, фамилии, телефону, ИИН или паспорту"),
    has_active_rental: Optional[bool] = Query(None, description="Фильтр по активной аренде"),
    is_blocked: Optional[bool] = Query(None, description="Фильтр по заблокированным пользователям"),
    mvd_approved: Optional[bool] = Query(None, description="Фильтр по МВД одобрению"),
    car_status: Optional[str] = Query(None, description="Фильтр по статусу авто"),

    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(50, ge=1, le=200, description="Количество элементов на странице"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> UserPaginatedResponse:
    """Получение списка пользователей с фильтрацией и поиском"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    # Базовый запрос
    query = db.query(User)
    
    # Фильтр по роли
    if role:
        try:
            role_enum = UserRole(role)
            query = query.filter(User.role == role_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверная роль")
    
    # Фильтр по заблокированным
    if is_blocked is not None:
        query = query.filter(User.is_active == (not is_blocked))
    
    # Поиск
    if search_query:
        search_filter = or_(
            func.lower(User.first_name).contains(search_query.lower()),
            func.lower(User.last_name).contains(search_query.lower()),
            User.phone_number.contains(search_query),
            User.iin.contains(search_query),
            User.passport_number.contains(search_query)
        )
        query = query.filter(search_filter)
    
    users = query.all()
    
    car_status_param = car_status
    
    result = []
    for user in users:
        # Проверяем МВД одобрение
        user_mvd_approved = _get_mvd_approved_status(user, db)
        if mvd_approved is not None and user_mvd_approved != mvd_approved:
            continue
        
        # Получаем текущую аренду
        current_car = _get_current_rental_car(user, db)
        has_active = current_car is not None
        
        if has_active_rental is not None and has_active != has_active_rental:
            continue
        
        # Обработка auto_class
        auto_class_list = []
        if user.auto_class:
            if isinstance(user.auto_class, list):
                auto_class_list = user.auto_class
            elif isinstance(user.auto_class, str):
                raw = user.auto_class.strip()
                if raw.startswith("{") and raw.endswith("}"):
                    raw = raw[1:-1]
                auto_class_list = [part.strip() for part in raw.split(",") if part.strip()]
        
        user_data = {
            "id": uuid_to_sid(user.id),
            "first_name": user.first_name,
            "last_name": user.last_name,
            "middle_name": user.middle_name,
            "phone_number": user.phone_number,
            "iin": user.iin,
            "passport_number": user.passport_number,
            "role": user.role.value,
            "auto_class": auto_class_list,
            "selfie_url": user.selfie_url,
            "is_blocked": not user.is_active,
            "current_rental_car": current_car,
            "rating": float(user.rating) if user.rating else None
        }

        car_status = "FREE"
        if current_car:
            active_rental = db.query(RentalHistory).filter(
                RentalHistory.user_id == user.id,
                RentalHistory.rental_status.in_([
                    RentalStatus.IN_USE, 
                    RentalStatus.DELIVERING, 
                    RentalStatus.DELIVERING_IN_PROGRESS,
                    RentalStatus.RESERVED,
                    RentalStatus.SCHEDULED,
                    RentalStatus.DELIVERY_RESERVED
                ])
            ).first()
            
            if active_rental:
                rs = active_rental.rental_status
                if rs == RentalStatus.IN_USE:
                    car_status = "IN_USE"
                elif rs == RentalStatus.RESERVED:
                    car_status = "RESERVED"
                elif rs == RentalStatus.SCHEDULED:
                    car_status = "SCHEDULED"
                elif rs in [RentalStatus.DELIVERING, RentalStatus.DELIVERING_IN_PROGRESS]:
                    car_status = "DELIVERING_IN_PROGRESS"
                elif rs == RentalStatus.DELIVERY_RESERVED:
                    car_status = "DELIVERY_RESERVED"
        
        if car_status == "FREE":
            if user.owned_cars:
                car_status = "OWNER"
            elif user.role in [UserRole.PENDING, UserRole.PENDINGTOFIRST, UserRole.PENDINGTOSECOND] or user.role.value.startswith("PENDING") or user.role.value.startswith("REJECT"):
                 if user.role.value.startswith("PENDING"):
                     car_status = "PENDING"
        
        user_data["carStatus"] = car_status
        
        if car_status_param is not None and car_status != car_status_param:
            continue
        
        converted_data = convert_uuid_response_to_sid(user_data, ["id"])
        result.append(UserListSchema(**converted_data))
    
    result.sort(key=lambda x: x.current_rental_car is None)
    
    return {
        "items": result[(page - 1) * limit : page * limit],
        "total": len(result),
        "page": page,
        "limit": limit,
        "pages": ceil(len(result) / limit)
    }


@users_router.get("/map-positions", response_model=List[UserMapPositionSchema])
async def get_users_map_positions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение позиций пользователей для карты"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    # Получаем всех пользователей
    users = db.query(User).all()
    
    result = []
    for user in users:
        # Проверяем активную аренду
        current_car = _get_current_rental_car(user, db)
        
        # Получаем координаты из последней завершенной аренды
        last_rental = db.query(RentalHistory).filter(
            and_(
                RentalHistory.user_id == user.id,
                RentalHistory.rental_status == RentalStatus.COMPLETED,
                RentalHistory.end_latitude.isnot(None),
                RentalHistory.end_longitude.isnot(None)
            )
        ).order_by(RentalHistory.end_time.desc()).first()
        
        # Если нет завершенных аренд, берем координаты из текущей аренды
        if not last_rental and current_car:
            active_rental = db.query(RentalHistory).filter(
                and_(
                    RentalHistory.user_id == user.id,
                    RentalHistory.rental_status.in_([
                        RentalStatus.IN_USE, 
                        RentalStatus.DELIVERING, 
                        RentalStatus.DELIVERING_IN_PROGRESS
                    ])
                )
            ).first()
            if active_rental:
                last_rental = active_rental
        
        # Пропускаем пользователей без координат
        if not last_rental or not last_rental.end_latitude or not last_rental.end_longitude:
            continue
        
        user_data = {
            "id": uuid_to_sid(user.id),
            "first_name": user.first_name,
            "last_name": user.last_name,
            "middle_name": user.middle_name,
            "selfie_url": user.selfie_url,
            "last_rental_end_latitude": float(last_rental.end_latitude),
            "last_rental_end_longitude": float(last_rental.end_longitude),
            "last_activity_at": last_rental.end_time,
            "is_active_rental": current_car is not None
        }
        
        converted_data = convert_uuid_response_to_sid(user_data, ["id"])
        result.append(UserMapPositionSchema(**converted_data))
    
    return result


@users_router.get("/{user_id}/card", response_model=UserCardSchema)
async def get_user_card(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение полной карточки пользователя"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    mvd_approved = _get_mvd_approved_status(user, db)
    current_car = _get_current_rental_car(user, db)
    
    # Заработок владельца (если применимо)
    owner_earnings = None
    if user.role == UserRole.USER:  # Только для одобренных пользователей
        earnings_data = _calculate_owner_earnings(user, db)
        owner_earnings = {
            "current_month": earnings_data["current_month"],
            "total": earnings_data["total"]
        }
    
    # Обработка auto_class
    auto_class_list = []
    if user.auto_class:
        if isinstance(user.auto_class, list):
            auto_class_list = user.auto_class
        elif isinstance(user.auto_class, str):
            raw = user.auto_class.strip()
            if raw.startswith("{") and raw.endswith("}"):
                raw = raw[1:-1]
            auto_class_list = [part.strip() for part in raw.split(",") if part.strip()]
    
    user_data = {
        "id": uuid_to_sid(user.id),
        "user_uuid": str(user.id),
        "digital_signature": user.digital_signature,
        "phone_number": user.phone_number,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "middle_name": user.middle_name,
        "iin": user.iin,
        "passport_number": user.passport_number,
        "birth_date": user.birth_date,
        "drivers_license_expiry": user.drivers_license_expiry,
        "id_card_expiry": user.id_card_expiry,
        "locale": user.locale,
        "role": user.role.value,
        "is_active": user.is_active,
        "is_verified_email": user.is_verified_email,
        "is_citizen_kz": user.is_citizen_kz,
        "documents_verified": user.documents_verified,
        "selfie_url": user.selfie_url,
        "selfie_with_license_url": user.selfie_with_license_url,
        "drivers_license_url": user.drivers_license_url,
        "id_card_front_url": user.id_card_front_url,
        "id_card_back_url": user.id_card_back_url,
        "psych_neurology_certificate_url": user.psych_neurology_certificate_url,
        "narcology_certificate_url": user.narcology_certificate_url,
        "pension_contributions_certificate_url": user.pension_contributions_certificate_url,
        "auto_class": auto_class_list,
        "wallet_balance": float(user.wallet_balance) if user.wallet_balance else 0.0,
        "created_at": user.created_at,
        "last_activity_at": user.last_activity_at,
        "mvd_approved": mvd_approved,
        "is_blocked": not user.is_active,
        "admin_comment": user.admin_comment,
        "current_rental_car": current_car,
        "owner_earnings_current_month": owner_earnings["current_month"] if owner_earnings else None,
        "owner_earnings_total": owner_earnings["total"] if owner_earnings else None,
        "rating": float(user.rating) if user.rating else None
    }
    
    converted_data = convert_uuid_response_to_sid(user_data, ["id"])
    return UserCardSchema(**converted_data)


@users_router.get("/{user_id}/transactions", response_model=WalletTransactionPaginationSchema)
async def get_user_transactions(
    user_id: str,
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(20, ge=1, le=100, description="Количество элементов на странице"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение истории транзакций пользователя"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.FINANCIER]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
        
    query = db.query(WalletTransaction).filter(WalletTransaction.user_id == user.id)
    
    query = query.order_by(desc(WalletTransaction.created_at))
    
    total_count = query.count()
    transactions = query.offset((page - 1) * limit).limit(limit).all()
    
    items = []
    for tx in transactions:
        tx_data = {
            "id": uuid_to_sid(tx.id),
            "amount": float(tx.amount),
            "transaction_type": tx.transaction_type.value if hasattr(tx.transaction_type, "value") else str(tx.transaction_type),
            "description": tx.description,
            "balance_before": float(tx.balance_before),
            "balance_after": float(tx.balance_after),
            "tracking_id": tx.tracking_id,
            "created_at": tx.created_at,
            "related_rental_id": uuid_to_sid(tx.related_rental_id) if tx.related_rental_id else None
        }
        items.append(WalletTransactionSchema(**tx_data))
        
    return {
        "items": items,
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": ceil(total_count / limit)
    }
@users_router.patch("/trips/{trip_id}", response_model=TripDetailSchema, summary="Редактирование данных поездки (Form Data)")
async def update_trip_details(
    trip_id: str,
    car_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    delivery_mechanic_id: Optional[str] = Form(None),
    mechanic_inspector_id: Optional[str] = Form(None),
    rental_type: Optional[RentalType] = Form(None),
    rental_status: Optional[str] = Form(None),
    start_time: Optional[datetime] = Form(None),
    end_time: Optional[datetime] = Form(None),
    price_per_minute: Optional[float] = Form(None),
    price_per_hour: Optional[float] = Form(None),
    price_per_day: Optional[float] = Form(None),
    total_price: Optional[float] = Form(None),
    photos_before: Optional[List[str]] = Form(None),
    photos_after: Optional[List[str]] = Form(None),
    mechanic_photos_before: Optional[List[str]] = Form(None),
    mechanic_photos_after: Optional[List[str]] = Form(None),
    client_comment: Optional[str] = Form(None),
    mechanic_comment: Optional[str] = Form(None),
    client_rating: Optional[int] = Form(None),
    mechanic_rating: Optional[int] = Form(None),
    start_latitude: Optional[float] = Form(None),
    start_longitude: Optional[float] = Form(None),
    end_latitude: Optional[float] = Form(None),
    end_longitude: Optional[float] = Form(None),
    fuel_level_start: Optional[float] = Form(None),
    fuel_level_end: Optional[float] = Form(None),
    mileage_start: Optional[float] = Form(None),
    mileage_end: Optional[float] = Form(None),
    
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Редактирование данных поездки с использованием multipart/form-data.
    Удобно для отправки списков файлов/строк.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
        
    rental_uuid = safe_sid_to_uuid(trip_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    
    if not rental:
        raise HTTPException(status_code=404, detail="Поездка не найдена")
    
    # Собираем данные в словарь, исключая None
    update_data = {
        "car_id": car_id,
        "user_id": user_id,
        "delivery_mechanic_id": delivery_mechanic_id,
        "mechanic_inspector_id": mechanic_inspector_id,
        "rental_type": rental_type,
        "rental_status": rental_status,
        "start_time": start_time,
        "end_time": end_time,
        "price_per_minute": price_per_minute,
        "price_per_hour": price_per_hour,
        "price_per_day": price_per_day,
        "total_price": total_price,
        "photos_before": photos_before, 
        "photos_after": photos_after,
        "mechanic_photos_before": mechanic_photos_before,
        "mechanic_photos_after": mechanic_photos_after,
        "client_comment": client_comment,
        "mechanic_comment": mechanic_comment,
        "client_rating": client_rating,
        "mechanic_rating": mechanic_rating,
        "start_latitude": start_latitude,
        "start_longitude": start_longitude,
        "end_latitude": end_latitude,
        "end_longitude": end_longitude,
        "fuel_level_start": fuel_level_start,
        "fuel_level_end": fuel_level_end,
        "mileage_start": mileage_start,
        "mileage_end": mileage_end,
    }
    
    update_dict = {k: v for k, v in update_data.items() if v is not None}
    
    if "rental_status" in update_dict and update_dict["rental_status"]:
        try:
            update_dict["rental_status"] = RentalStatus(update_dict["rental_status"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный статус аренды")
            
    if "car_id" in update_dict and update_dict["car_id"]:
        update_dict["car_id"] = safe_sid_to_uuid(update_dict["car_id"])
    if "user_id" in update_dict and update_dict["user_id"]:
         update_dict["user_id"] = safe_sid_to_uuid(update_dict["user_id"])
    if "delivery_mechanic_id" in update_dict and update_dict["delivery_mechanic_id"]:
        update_dict["delivery_mechanic_id"] = safe_sid_to_uuid(update_dict["delivery_mechanic_id"])
    if "mechanic_inspector_id" in update_dict and update_dict["mechanic_inspector_id"]:
        update_dict["mechanic_inspector_id"] = safe_sid_to_uuid(update_dict["mechanic_inspector_id"])

    for key, value in update_dict.items():
        setattr(rental, key, value)
        
    db.commit()
    db.refresh(rental)
    
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    car_name = car.name if car else "Unknown"
    car_plate = car.plate_number if car else "Unknown"
    
    return TripDetailSchema(
        id=uuid_to_sid(rental.id),
        rental_type=rental.rental_type,
        start_date=rental.start_time,
        end_date=rental.end_time,
        duration_minutes=int((rental.end_time - rental.start_time).total_seconds() / 60) if rental.end_time and rental.start_time else 0,
        total_price=float(rental.total_price) if rental.total_price else 0.0,
        car_id=uuid_to_sid(rental.car_id),
        car_name=car_name,
        car_plate_number=car_plate,
        photos_before=rental.photos_before or [],
        photos_after=rental.photos_after or [],
        mechanic_photos_before=rental.mechanic_photos_before or [],
        mechanic_photos_after=rental.mechanic_photos_after or [],
        client_comment=rental.client_comment,
        mechanic_comment=rental.mechanic_comment,
        client_rating=rental.client_rating,
        mechanic_rating=rental.mechanic_rating,
        rating=float(rental.rating) if rental.rating else None,
        start_latitude=rental.start_latitude,
        start_longitude=rental.start_longitude,
        end_latitude=rental.end_latitude,
        end_longitude=rental.end_longitude
    )

@users_router.post("/trips/delete")
async def delete_rentals_bulk(
    payload: DeleteRentalsRequestSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Массовое удаление поездок (RentalHistory) по списку ID.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    deleted_count = 0
    errors = []

    for sid in payload.rental_ids:
        try:
            rental_uuid = safe_sid_to_uuid(sid)
            rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
            
            if rental:
                db.query(RentalReview).filter(RentalReview.rental_id == rental_uuid).delete()
                
                db.delete(rental)
                deleted_count += 1
            else:
                errors.append(f"Rental {sid} not found")
        except Exception as e:
            errors.append(f"Error deleting {sid}: {str(e)}")

    db.commit()

    return {
        "success": True, 
        "deleted_count": deleted_count,
        "errors": errors
    }


@users_router.post("/trips")
async def create_rental(
    payload: RentalCreateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Создание новой аренды через админ-панель.
    Позволяет привязать аренду к пользователю и машине.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(payload.user_id)
    car_id = safe_sid_to_uuid(payload.car_id)
    
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    rental_status = RentalStatus.COMPLETED
    if payload.rental_status:
        status_map = {s.value: s for s in RentalStatus}
        rental_status = status_map.get(payload.rental_status.lower(), RentalStatus.COMPLETED)
    
    new_rental = RentalHistory(
        user_id=user_uuid,
        car_id=car_id,
        rental_type=payload.rental_type,
        rental_status=rental_status,
        start_time=payload.start_time,
        end_time=payload.end_time,
        start_latitude=payload.start_latitude,
        start_longitude=payload.start_longitude,
        end_latitude=payload.end_latitude,
        end_longitude=payload.end_longitude,
        total_price=int(payload.total_price) if payload.total_price else None,
        mileage_before=payload.mileage_before,
        mileage_after=payload.mileage_after,
        fuel_before=payload.fuel_before,
        fuel_after=payload.fuel_after
    )
    
    db.add(new_rental)
    db.commit()
    db.refresh(new_rental)
    
    return {
        "success": True,
        "rental_id": uuid_to_sid(new_rental.id),
        "user_id": uuid_to_sid(new_rental.user_id),
        "car_id": uuid_to_sid(new_rental.car_id),
        "rental_type": new_rental.rental_type.value if new_rental.rental_type else None,
        "rental_status": new_rental.rental_status.value if new_rental.rental_status else None,
        "start_time": new_rental.start_time.isoformat() if new_rental.start_time else None,
        "end_time": new_rental.end_time.isoformat() if new_rental.end_time else None,
        "total_price": new_rental.total_price
    }


@users_router.get("/contracts/{signature_id}/download")
async def download_user_contract(
    signature_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Скачивание подписанного договора с данными пользователя.
    Возвращает файл договора в base64 и информацию о подписанте.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    signature_uuid = safe_sid_to_uuid(signature_id)
    signature = db.query(UserContractSignature).filter(
        UserContractSignature.id == signature_uuid
    ).first()
    
    if not signature:
        raise HTTPException(status_code=404, detail="Подпись договора не найдена")
    
    contract_file = db.query(ContractFile).filter(
        ContractFile.id == signature.contract_file_id
    ).first()
    
    if not contract_file:
        raise HTTPException(status_code=404, detail="Файл договора не найден")
    
    user = db.query(User).filter(User.id == signature.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    if not os.path.exists(contract_file.file_path):
        raise HTTPException(status_code=404, detail="Физический файл договора не найден")
    
    with open(contract_file.file_path, "rb") as f:
        file_content = f.read()
    
    file_base64 = base64.b64encode(file_content).decode()
    
    file_ext = os.path.splitext(contract_file.file_path)[1].lower()
    mime_types = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".html": "text/html"
    }
    mime_type = mime_types.get(file_ext, "application/octet-stream")
    
    return {
        "success": True,
        "signature_id": uuid_to_sid(signature.id),
        "contract_type": contract_file.contract_type.value if contract_file.contract_type else None,
        "file_name": contract_file.file_name,
        "file_content": f"data:{mime_type};base64,{file_base64}",
        "signed_at": signature.signed_at.isoformat() if signature.signed_at else None,
        "user": {
            "id": uuid_to_sid(user.id),
            "phone_number": user.phone_number,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "middle_name": user.middle_name,
            "iin": user.iin,
            "digital_signature": signature.digital_signature
        },
        "rental_id": uuid_to_sid(signature.rental_id) if signature.rental_id else None
    }


@users_router.get("/contracts")
async def get_all_user_signatures(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получение списка всех подписанных договоров.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    total = db.query(UserContractSignature).count()
    skip = (page - 1) * limit
    
    signatures = db.query(UserContractSignature).order_by(
        UserContractSignature.signed_at.desc()
    ).offset(skip).limit(limit).all()
    
    items = []
    for sig in signatures:
        user = db.query(User).filter(User.id == sig.user_id).first()
        contract = db.query(ContractFile).filter(ContractFile.id == sig.contract_file_id).first()
        
        items.append({
            "signature_id": uuid_to_sid(sig.id),
            "contract_type": contract.contract_type.value if contract and contract.contract_type else None,
            "signed_at": sig.signed_at.isoformat() if sig.signed_at else None,
            "user_id": uuid_to_sid(sig.user_id),
            "user_name": f"{user.last_name or ''} {user.first_name or ''}".strip() if user else None,
            "user_phone": user.phone_number if user else None,
            "rental_id": uuid_to_sid(sig.rental_id) if sig.rental_id else None
        })
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": ceil(total / limit) if limit > 0 else 0
    }


@users_router.post("/{user_id}/balance/topup")
async def topup_user_balance(
    user_id: str,
    payload: BalanceTopUpSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Пополнение баланса пользователя администратором.
    
    1. Создаёт транзакцию в таблице wallet_transactions
    2. Обновляет баланс пользователя
    3. Отправляет push-уведомление пользователю
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    balance_before = float(user.wallet_balance or 0)
    balance_after = balance_before + payload.amount
    
    transaction = WalletTransaction(
        user_id=user_uuid,
        amount=payload.amount,
        transaction_type=WalletTransactionType.DEPOSIT,
        description=payload.description or f"Пополнение баланса администратором ({current_user.phone_number})",
        balance_before=balance_before,
        balance_after=balance_after
    )
    db.add(transaction)
    
    user.wallet_balance = balance_after
    
    db.commit()
    db.refresh(transaction)
    
    notification_message = f"Ваш баланс пополнен на {payload.amount:.0f} ₸. Новый баланс: {balance_after:.0f} ₸"
    if payload.description:
        notification_message += f"\nПричина: {payload.description}"
    
    try:
        await send_push_to_user_by_id(
            user_id=user_uuid,
            db=db,
            title="Пополнение баланса",
            body=notification_message
        )
    except Exception as e:
        pass
    
    notification = Notification(
        user_id=user_uuid,
        title="Пополнение баланса",
        body=notification_message
    )
    db.add(notification)
    db.commit()
    
    return {
        "success": True,
        "transaction_id": uuid_to_sid(transaction.id),
        "user_id": uuid_to_sid(user_uuid),
        "amount": payload.amount,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "description": payload.description
    }



@users_router.patch("/{user_id}/auto_class")
async def update_user_auto_class(
    user_id: str,
    payload: AutoClassUpdateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Изменение уровня доступа пользователя к автомобилям.
    При повышении уровня — отправляется уведомление.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    old_classes = set(user.auto_class or [])
    new_classes = set(payload.auto_class)
    
    user.auto_class = payload.auto_class
    db.commit()
    
    class_names = {"A": "A", "B": "B", "C": "C"}
    new_text = ", ".join([class_names.get(c, c) for c in sorted(new_classes)]) if new_classes else "—"
    notification_message = f"Ваш уровень доступа к автомобилям изменён. Доступные классы: {new_text}"
    
    try:
        await send_push_to_user_by_id(
            user_id=user_uuid,
            db=db,
            title="Изменение уровня доступа",
            body=notification_message
        )
    except Exception:
        pass
    
    notification = Notification(
        user_id=user_uuid,
        title="Изменение уровня доступа",
        body=notification_message
    )
    db.add(notification)
    db.commit()
    
    return {
        "success": True,
        "user_id": uuid_to_sid(user_uuid),
        "auto_class": payload.auto_class
    }


@users_router.patch("/{user_id}/zone-exit-permission")
async def update_user_zone_exit_permission(
    user_id: str,
    can_exit_zone: bool,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Изменение разрешения на выезд за зону для пользователя"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    if not user_uuid:
        raise HTTPException(status_code=400, detail="Неверный ID пользователя")
    
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    user.can_exit_zone = can_exit_zone
    db.commit()
    
    return {
        "success": True,
        "user_id": uuid_to_sid(user_uuid),
        "can_exit_zone": can_exit_zone
    }


# API endpoint для проверки разрешения выезда за зону (для cars сервиса)
@users_router.get("/{user_id}/zone-exit-permission")
async def get_user_zone_exit_permission(
    user_id: str,
    db: Session = Depends(get_db)
):
    """Получение разрешения на выезд за зону для пользователя (для внутреннего использования)"""
    user_uuid = safe_sid_to_uuid(user_id)
    if not user_uuid:
        return {"can_exit_zone": False}
    
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        return {"can_exit_zone": False}
    
    return {"can_exit_zone": user.can_exit_zone}


@users_router.patch("/{user_id}/comment")
async def update_user_comment(
    user_id: str,
    comment_data: UserCommentUpdateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Обновление комментария пользователя"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    user.admin_comment = comment_data.admin_comment
    db.commit()
    
    return {"message": "Комментарий обновлен", "admin_comment": comment_data.admin_comment}


@users_router.get("/{user_id}/guarantors/he-is-guarantor", response_model=List[GuarantorInfoSchema])
async def get_users_he_is_guarantor_for(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка пользователей, для которых текущий пользователь является гарантом"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    from app.models.guarantor_model import Guarantor
    guarantor_relations = db.query(Guarantor).filter(
        and_(
            Guarantor.guarantor_id == user_uuid,
            Guarantor.is_active == True
        )
    ).all()
    
    result = []
    for relation in guarantor_relations:
        client = db.query(User).filter(User.id == relation.client_id).first()
        if client:
            client_data = {
                "id": uuid_to_sid(client.id),
                "first_name": client.first_name,
                "last_name": client.last_name,
                "phone_number": client.phone_number,
                "iin": client.iin,
                "passport_number": client.passport_number,
                "selfie_url": client.selfie_url
            }
            
            converted_data = convert_uuid_response_to_sid(client_data, ["id"])
            result.append(GuarantorInfoSchema(**converted_data))
    
    return result


@users_router.get("/{user_id}/guarantors/his-guarantors", response_model=List[GuarantorInfoSchema])
async def get_his_guarantors(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка гарантов текущего пользователя"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Получаем гарантов этого пользователя
    from app.models.guarantor_model import Guarantor
    guarantor_relations = db.query(Guarantor).filter(
        and_(
            Guarantor.client_id == user_uuid,
            Guarantor.is_active == True
        )
    ).all()
    
    result = []
    for relation in guarantor_relations:
        guarantor = db.query(User).filter(User.id == relation.guarantor_id).first()
        if guarantor:
            guarantor_data = {
                "id": uuid_to_sid(guarantor.id),
                "first_name": guarantor.first_name,
                "last_name": guarantor.last_name,
                "phone_number": guarantor.phone_number,
                "iin": guarantor.iin,
                "passport_number": guarantor.passport_number,
                "selfie_url": guarantor.selfie_url
            }
            
            converted_data = convert_uuid_response_to_sid(guarantor_data, ["id"])
            result.append(GuarantorInfoSchema(**converted_data))
    
    return result


@users_router.get("/{user_id}/trips/summary", response_model=TripSummarySchema)
async def get_user_trips_summary(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение сводки по поездкам пользователя"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Получаем все завершенные поездки пользователя
    completed_trips = db.query(RentalHistory).filter(
        and_(
            RentalHistory.user_id == user_uuid,
            RentalHistory.rental_status == RentalStatus.COMPLETED
        )
    ).all()
    
    total_minutes = 0
    total_spent = 0.0
    total_trips = len(completed_trips)
    
    for trip in completed_trips:
        if trip.start_time and trip.end_time:
            duration_seconds = (trip.end_time - trip.start_time).total_seconds()
            total_minutes += int(duration_seconds / 60)
        
        total_spent += float(trip.total_price or 0)
    
    return TripSummarySchema(
        total_minutes=total_minutes,
        total_spent=total_spent,
        total_trips=total_trips
    )


@users_router.get("/{user_id}/trips", response_model=List[TripListItemSchema])
async def get_user_trips(
    user_id: str,
    month: Optional[int] = Query(None, description="Месяц (1-12). Если не указан, возвращается текущий месяц"),
    year: Optional[int] = Query(None, description="Год. Если не указан, возвращается текущий год"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка поездок пользователя с фильтром по месяцам"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Определяем период
    now = datetime.now()
    target_month = month or now.month
    target_year = year or now.year
    
    month_start = datetime(target_year, target_month, 1)
    if target_month == 12:
        month_end = datetime(target_year + 1, 1, 1)
    else:
        month_end = datetime(target_year, target_month + 1, 1)
    
    # Получаем поездки за указанный месяц
    trips = db.query(RentalHistory).filter(
        and_(
            RentalHistory.user_id == user_uuid,
            RentalHistory.rental_status == RentalStatus.COMPLETED,
            RentalHistory.end_time >= month_start,
            RentalHistory.end_time < month_end
        )
    ).order_by(RentalHistory.end_time.desc()).all()
    
    result = []
    for trip in trips:
        duration_minutes = 0
        if trip.start_time and trip.end_time:
            duration_seconds = (trip.end_time - trip.start_time).total_seconds()
            duration_minutes = int(duration_seconds / 60)
        
        # Получаем информацию об автомобиле
        car = db.query(Car).filter(Car.id == trip.car_id).first()
        
        result.append(TripListItemSchema(
            id=uuid_to_sid(trip.id),
            rental_type=trip.rental_type.value,
            start_date=trip.start_time,
            end_date=trip.end_time,
            duration_minutes=duration_minutes,
            total_price=float(trip.total_price or 0),
            car_name=car.name if car else None,
            car_plate_number=car.plate_number if car else None
        ))
    
    return result


@users_router.get("/{user_id}/trips/{trip_id}", response_model=TripDetailSchema)
async def get_trip_detail(
    user_id: str,
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение детальной информации о поездке"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    trip_uuid = safe_sid_to_uuid(trip_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Получаем поездку
    trip = db.query(RentalHistory).filter(
        and_(
            RentalHistory.id == trip_uuid,
            RentalHistory.user_id == user_uuid
        )
    ).first()
    
    if not trip:
        raise HTTPException(status_code=404, detail="Поездка не найдена")
    
    # Получаем информацию об автомобиле
    car = db.query(Car).filter(Car.id == trip.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    # Вычисляем длительность
    duration_minutes = 0
    if trip.start_time and trip.end_time:
        duration_seconds = (trip.end_time - trip.start_time).total_seconds()
        duration_minutes = int(duration_seconds / 60)
    
    # Получаем отзыв
    from app.models.history_model import RentalReview
    review = db.query(RentalReview).filter(RentalReview.rental_id == trip.id).first()
    
    return TripDetailSchema(
        id=uuid_to_sid(trip.id),
        rental_type=trip.rental_type.value,
        start_date=trip.start_time,
        end_date=trip.end_time,
        duration_minutes=duration_minutes,
        total_price=float(trip.total_price or 0),
        car_id=uuid_to_sid(car.id),
        car_name=car.name,
        car_plate_number=car.plate_number,
        photos_before=trip.photos_before or [],
        photos_after=trip.photos_after or [],
        mechanic_photos_before=trip.mechanic_photos_before or [],
        mechanic_photos_after=trip.mechanic_photos_after or [],
        client_comment=review.comment if review else None,
        mechanic_comment=review.mechanic_comment if review else None,
        client_rating=review.rating if review else None,
        mechanic_rating=review.mechanic_rating if review else None,
        start_latitude=float(trip.start_latitude) if trip.start_latitude else None,
        start_longitude=float(trip.start_longitude) if trip.start_longitude else None,
        end_latitude=float(trip.end_latitude) if trip.end_latitude else None,
        end_longitude=float(trip.end_longitude) if trip.end_longitude else None
    )


@users_router.get("/{user_id}/cars", response_model=List[OwnerCarListItemSchema])
async def get_user_cars(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка автомобилей владельца"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Получаем автомобили владельца
    cars = db.query(Car).filter(Car.owner_id == user_uuid).all()
    
    result = []
    now = datetime.now()
    current_month_start = datetime(now.year, now.month, 1)
    
    for car in cars:
        # Рассчитываем доступные минуты для текущего месяца
        available_minutes = _calculate_month_availability_minutes(
            car_id=car.id,
            year=now.year,
            month=now.month,
            owner_id=user_uuid,
            db=db
        )
        
        # Рассчитываем заработок
        earnings_data = _calculate_car_earnings(car.id, user_uuid, db, current_month_start)
        
        result.append(OwnerCarListItemSchema(
            id=uuid_to_sid(car.id),
            name=car.name,
            plate_number=car.plate_number,
            available_minutes=available_minutes,
            earnings_current_month=earnings_data["current_month"],
            earnings_total=earnings_data["total"],
            photos=sort_car_photos(car.photos or []),
            vin=car.vin,
            color=car.color
        ))
    
    return result


@users_router.patch("/{user_id}/edit")
async def edit_user(
    user_id: str,
    edit_data: UserEditSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Редактирование пользователя (смена класса допуска и роли)"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    if edit_data.auto_class is not None:
        user.auto_class = edit_data.auto_class
    
    if edit_data.role is not None:
        old_role = user.role
        user.role = edit_data.role
        
        if (edit_data.role in [UserRole.REJECTFIRST, UserRole.REJECTSECOND, UserRole.REJECTFIRSTDOC, UserRole.REJECTFIRSTCERT] 
            and old_role != edit_data.role):
            from app.guarantor.router import cancel_guarantor_requests_on_rejection
            await cancel_guarantor_requests_on_rejection(str(user.id), db)
    
    db.commit()
    
    asyncio.create_task(notify_user_status_update(str(user.id)))
    
    return {"message": "Пользователь обновлен"}


@users_router.patch("/{user_id}/block")
async def block_user(
    user_id: str,
    block_data: UserBlockSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Блокировка/разблокировка пользователя по ИИН/паспорту"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Если блокируем и причина не указана
    if block_data.is_blocked and not block_data.block_reason:
        raise HTTPException(status_code=400, detail="При блокировке обязательно указать причину")
    
    # Обновляем статус активности
    user.is_active = not block_data.is_blocked
    
    # Сохраняем причину блокировки в комментарии (можно создать отдельную таблицу для аудита)
    if block_data.is_blocked:
        block_reason = f"Блокировка: {block_data.block_reason}"
        if user.admin_comment:
            user.admin_comment = f"{user.admin_comment}\n{block_reason}"
        else:
            user.admin_comment = block_reason
    
    db.commit()
    
    asyncio.create_task(notify_user_status_update(str(user.id)))
    
    action = "заблокирован" if block_data.is_blocked else "разблокирован"
    return {"message": f"Пользователь {action}"}


def _calculate_month_availability_minutes(
    car_id: str,
    year: int,
    month: int,
    owner_id: str,
    db: Session
) -> int:
    """Рассчитывает доступные минуты для автомобиля в месяце"""
    # Импортируем функцию из owner.utils
    from app.owner.utils import calculate_month_availability_minutes
    owner_uuid = safe_sid_to_uuid(owner_id)
    return calculate_month_availability_minutes(car_id, year, month, owner_uuid, db)


def _calculate_car_earnings(car_id: str, owner_id: str, db: Session, month_start: datetime) -> Dict[str, float]:
    """Рассчитывает заработок с автомобиля"""
    car_uuid = safe_sid_to_uuid(car_id)
    # Получаем поездки клиентов (исключаем поездки самого владельца)
    client_rentals = db.query(RentalHistory).filter(
        and_(
            RentalHistory.car_id == car_uuid,
            RentalHistory.rental_status == RentalStatus.COMPLETED,
            RentalHistory.user_id != owner_id
        )
    ).all()
    
    current_month_earnings = 0.0
    total_earnings = 0.0
    
    for rental in client_rentals:
        car = db.query(Car).filter(Car.id == car_id).first()
        if car:
            earnings = calculate_owner_earnings(rental, car, db.query(User).filter(User.id == owner_id).first())
            
            # Заработок за текущий месяц
            if rental.end_time and rental.end_time >= month_start:
                current_month_earnings += earnings
            
            # Общий заработок
            total_earnings += earnings
    
    return {"current_month": current_month_earnings, "total": total_earnings}


@users_router.post("/bonus")
async def add_company_bonus(
    bonus_data: CompanyBonusSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Начисление бонуса от компании клиенту"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    try:
        # Проверяем формат номера телефона
        if not bonus_data.phone_number.isdigit():
            raise HTTPException(status_code=400, detail="Номер телефона должен содержать только цифры")
        
        # Ищем пользователя по номеру телефона
        user = db.query(User).filter(User.phone_number == bonus_data.phone_number).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь с таким номером телефона не найден")
        
        # Сохраняем баланс до операции
        balance_before = float(user.wallet_balance or 0)
        bonus_amount_decimal = Decimal(str(bonus_data.amount))
        
        # Начисляем бонус
        user.wallet_balance = (user.wallet_balance or Decimal('0')) + bonus_amount_decimal
        balance_after = float(user.wallet_balance)
        
        # Записываем транзакцию
        transaction = WalletTransaction(
            user_id=user.id,
            amount=float(bonus_amount_decimal),
            transaction_type=WalletTransactionType.COMPANY_BONUS,
            description=bonus_data.description,
            balance_before=balance_before,
            balance_after=balance_after,
            created_at=get_local_time()
        )
        db.add(transaction)
        db.commit()
        db.refresh(user)
        
        asyncio.create_task(notify_user_status_update(str(user.id)))
        
        # Отправляем push-уведомление
        try:
            await send_push_to_user_by_id(
                db_session=db,
                user_id=user.id,
                title=bonus_data.title,
                body=f"Вам начислен бонус - {bonus_data.amount:,.0f} тг на основной баланс. Спасибо, что выбираете нас!"
            )
        except Exception as push_error:
            await log_error_to_telegram(
                error=push_error,
                user=user,
                additional_context={
                    "action": "send_bonus_notification",
                    "bonus_amount": bonus_data.amount,
                    "phone_number": bonus_data.phone_number,
                    "admin_id": str(current_user.id)
                }
            )
        
        return {
            "message": "Бонус успешно начислен",
            "user_id": uuid_to_sid(user.id),
            "phone_number": user.phone_number,
            "amount": bonus_data.amount,
            "new_balance": float(user.wallet_balance),
            "transaction_id": uuid_to_sid(transaction.id)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        await log_error_to_telegram(
            error=e,
            user=current_user,
            additional_context={
                "action": "add_company_bonus",
                "phone_number": bonus_data.phone_number,
                "bonus_amount": bonus_data.amount,
                "description": bonus_data.description
            }
        )
        raise HTTPException(
            status_code=500,
            detail="Ошибка при начислении бонуса. Администраторы уведомлены."
        )


@users_router.post("/sanctions", summary="Назначить санкцию клиенту")
async def add_sanction_penalty(
    penalty_data: SanctionPenaltySchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Назначает санкцию (штраф) клиенту:
    - Находит пользователя по номеру телефона
    - Вычитает сумму санкции из баланса
    - Создаёт транзакцию SANCTION_PENALTY, привязанную к аренде
    - Отправляет push-уведомление пользователю
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    if not penalty_data.phone_number.isdigit():
        raise HTTPException(status_code=400, detail="Номер телефона должен содержать только цифры")
    
    try:
        user = db.query(User).filter(User.phone_number == penalty_data.phone_number).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь с таким номером телефона не найден")
        
        try:
            rental_uuid = safe_sid_to_uuid(penalty_data.rental_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Некорректный rental_id")
        
        rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
        if not rental:
            raise HTTPException(status_code=404, detail="Аренда не найдена")
        if rental.user_id != user.id:
            raise HTTPException(status_code=400, detail="Указанная аренда не принадлежит пользователю")
        
        penalty_amount = Decimal(str(penalty_data.amount))
        balance_before = float(user.wallet_balance or 0)
        current_balance = Decimal(user.wallet_balance or 0)
        new_balance = current_balance - penalty_amount
        user.wallet_balance = new_balance
        balance_after = float(new_balance)
        
        transaction = WalletTransaction(
            user_id=user.id,
            amount=float(-penalty_amount),
            transaction_type=WalletTransactionType.SANCTION_PENALTY,
            description=penalty_data.description,
            balance_before=balance_before,
            balance_after=balance_after,
            related_rental_id=rental.id,
            created_at=get_local_time()
        )
        db.add(transaction)
        db.commit()
        db.refresh(user)
        
        asyncio.create_task(notify_user_status_update(str(user.id)))
        
        try:
            if user_has_push_tokens(db, user.id):
                asyncio.create_task(
                    send_localized_notification_to_user_async(
                        user.id,
                        "fine_issued",
                        "fine_issued"
                    )
                )
        except Exception as push_error:
            await log_error_to_telegram(
                error=push_error,
                user=user,
                additional_context={
                    "action": "send_sanction_notification",
                    "penalty_amount": penalty_data.amount,
                    "phone_number": penalty_data.phone_number,
                    "admin_id": str(current_user.id)
                }
            )
        
        return {
            "message": "Санкция успешно начислена",
            "user_id": uuid_to_sid(user.id),
            "phone_number": user.phone_number,
            "amount": penalty_data.amount,
            "new_balance": float(user.wallet_balance),
            "transaction_id": uuid_to_sid(transaction.id),
            "rental_id": penalty_data.rental_id
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        await log_error_to_telegram(
            error=e,
            user=current_user,
            additional_context={
                "action": "add_sanction_penalty",
                "phone_number": penalty_data.phone_number,
                "penalty_amount": penalty_data.amount,
                "description": penalty_data.description,
                "rental_id": penalty_data.rental_id
            }
        )
        raise HTTPException(
            status_code=500,
            detail="Ошибка при назначении санкции. Администраторы уведомлены."
        )


@users_router.delete("/rentals", summary="Удалить конкретные аренды")
async def delete_rentals(
    request: DeleteRentalsRequestSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Удалить конкретные аренды из базы данных (включая связанные данные).
    Удаляет: wallet_transactions, contract_signatures, rental_actions, rental_reviews, rental_history
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав. Только администраторы могут удалять аренды")

    if not request.rental_ids:
        raise HTTPException(status_code=400, detail="Список ID аренд не может быть пустым")

    try:
        # Преобразуем sid в UUID
        rental_uuids = []
        invalid_ids = []
        
        for rental_id in request.rental_ids:
            try:
                rental_uuid = safe_sid_to_uuid(rental_id)
                rental_uuids.append(rental_uuid)
            except Exception:
                invalid_ids.append(rental_id)
        
        if invalid_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Некорректные ID аренд: {', '.join(invalid_ids)}"
            )

        # Получаем аренды по UUID
        rentals = db.query(RentalHistory).filter(RentalHistory.id.in_(rental_uuids)).all()
        
        if not rentals:
            return {
                "message": "Аренды не найдены",
                "deleted_rentals": 0,
                "deleted_wallet_transactions": 0,
                "deleted_contract_signatures": 0,
                "deleted_rental_actions": 0,
                "deleted_rental_reviews": 0
            }

        # Счетчики удаленных записей
        deleted_rentals_count = len(rentals)
        deleted_actions_count = 0
        deleted_signatures_count = 0
        deleted_transactions_count = 0
        deleted_reviews_count = 0

        # Для каждой аренды удаляем связанные данные в правильном порядке
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

            # 4. Удаляем rental_reviews (rental_id)
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
            "message": "Аренды успешно удалены",
            "deleted_rentals": deleted_rentals_count,
            "deleted_wallet_transactions": deleted_transactions_count,
            "deleted_contract_signatures": deleted_signatures_count,
            "deleted_rental_actions": deleted_actions_count,
            "deleted_rental_reviews": deleted_reviews_count,
            "rental_ids": [uuid_to_sid(r.id) for r in rentals]
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
                    "action": "admin_delete_rentals",
                    "rental_ids": request.rental_ids,
                    "admin_id": str(current_user.id)
                }
            )
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Ошибка удаления аренд: {str(e)}")
