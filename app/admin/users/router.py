from fastapi import APIRouter, Depends, HTTPException, Query, Form, File, UploadFile, Request
from pydantic import BaseModel, Field
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
from app.auth.dependencies.save_documents import save_file, validate_photos
from app.utils.atomic_operations import delete_uploaded_files
from app.models.user_model import User, UserRole
from app.models.application_model import Application, ApplicationStatus
from app.models.history_model import RentalHistory, RentalStatus, RentalReview, RentalType
from app.models.car_model import Car, CarStatus, CarBodyType
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
    WalletTransactionSchema, WalletTransactionPaginationSchema, RentalHistoryUpdateSchema, RentalCreateSchema,
    BalanceTopUpSchema, AutoClassUpdateSchema,
    AdminRentalReviewRequest, AdminRentalReviewResponse,
    AdminCancelReservationRequest, AdminCancelReservationResponse,
    AdminExtendRentalRequest, AdminExtendRentalResponse,
    MechanicStartInspectionResponse, MechanicPhotoUploadResponse, MechanicCompleteInspectionResponse,
    AdminMechanicCompleteRequest, AdminAssignMechanicRequest,
    AssignMechanicResponse, UnassignMechanicResponse,
    AdminDeleteUserRequest, AdminDeleteUserResponse,
    GroupedTransactionsPaginationSchema, GroupedTransactionItemSchema
)
from math import ceil, floor
from app.owner.router import calculate_owner_earnings
from app.admin.cars.utils import sort_car_photos
from app.utils.telegram_logger import log_error_to_telegram
from app.push.utils import send_push_to_user_by_id, send_localized_notification_to_user, send_localized_notification_to_user_async, user_has_push_tokens, send_localized_notification_to_all_mechanics
from app.websocket.notifications import notify_user_status_update
from app.utils.time_utils import get_local_time, parse_datetime_to_local
import asyncio
import httpx
from app.wallet.utils import record_wallet_transaction
from app.rent.utils.calculate_price import get_open_price, calc_required_balance, calculate_total_price
from app.rent.utils.balance_utils import verify_and_fix_rental_balance
from app.core.config import TELEGRAM_BOT_TOKEN, TELEGRAM_BOT_TOKEN_2
from app.models.application_model import Application
from app.models.history_model import RentalHistory
from app.models.wallet_transaction_model import WalletTransaction
from app.models.guarantor_model import Guarantor, GuarantorRequest
from app.models.user_device_model import UserDevice
from app.models.contract_model import UserContractSignature
from app.utils.action_logger import log_action
from app.models.action_log_model import ActionLog

users_router = APIRouter(tags=["Admin Users"])

# Константы для расчета топлива
FUEL_PRICE_PER_LITER = 400
ELECTRIC_FUEL_PRICE_PER_LITER = 100


def recalculate_transactions_after(
    db: Session,
    user_id: uuid.UUID,
    after_time: datetime,
    base_balance: float
) -> float:
    """
    Пересчитывает balance_before и balance_after для всех транзакций пользователя
    после указанного времени. Возвращает итоговый баланс.
    
    Args:
        db: Сессия БД
        user_id: UUID пользователя
        after_time: Время, после которого пересчитывать транзакции
        base_balance: Начальный баланс (balance_after удаленной/измененной транзакции или balance_before)
    
    Returns:
        float: Итоговый баланс после пересчёта
    """
    subsequent_transactions = (
        db.query(WalletTransaction)
        .filter(
            WalletTransaction.user_id == user_id,
            WalletTransaction.created_at > after_time
        )
        .order_by(WalletTransaction.created_at.asc())
        .all()
    )
    
    running_balance = base_balance
    
    for tx in subsequent_transactions:
        tx.balance_before = running_balance
        tx.balance_after = running_balance + float(tx.amount)
        running_balance = tx.balance_after
    
    return running_balance


@users_router.post("/generate-token")
async def generate_user_token(
    user_id: str = Form(..., description="UUID пользователя"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получить access token для указанного пользователя.
    Только для ADMIN.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Доступ только для админа")
    
    from app.auth.security.tokens import create_access_token, create_refresh_token
    import uuid as uuid_module
    
    try:
        user_uuid = uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат UUID")
    
    user = db.query(User).filter(User.id == user_uuid).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    access_token = create_access_token(data={"sub": user.phone_number})
    refresh_token = create_refresh_token(data={"sub": user.phone_number})
    
    log_action(
        db,
        actor_id=current_user.id,
        action="admin_impersonate_user_token",
        entity_type="user",
        entity_id=user.id,
        details={"phone": user.phone_number}
    )
    db.commit()
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": uuid_to_sid(user.id),
            "phone_number": user.phone_number,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role.value if user.role else None
        }
    }

@users_router.get("/pending", response_model=List[UserProfileSchema])
async def get_pending_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение пользователей, ожидающих одобрения"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    users = db.query(User).filter(
        User.role == UserRole.PENDING,
        User.is_deleted == False
    ).all()
    
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
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
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

    log_action(
        db,
        actor_id=current_user.id,
        action="approve_or_reject_user",
        entity_type="user",
        entity_id=user.id,
        details={
            "approved": approved,
            "new_role": user.role.value
        }
    )
    db.commit()
    
    return {"message": message}


@users_router.get("/all", response_model=List[UserProfileSchema])
async def get_all_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение всех пользователей"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    users = db.query(User).filter(User.is_deleted == False).all()
    
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
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    users = db.query(User).filter(
        User.role == UserRole.CLIENT,
        User.is_deleted == False
    ).all()
    
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
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    db.commit()

    log_action(
        db,
        actor_id=current_user.id,
        action="update_user_role",
        entity_type="user",
        entity_id=user.id,
        details={"old_role": user.role.value, "new_role": role_data.role.value}
    )
    user.role = role_data.role
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
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
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
    
    current_month_base = 0.0
    current_month_delivery = 0.0
    
    for rental in current_month_rentals:
        car = next((c for c in owned_cars if c.id == rental.car_id), None)
        if car:
            components = calculate_owner_earnings(rental, car, user, return_components=True)
            current_month_base += components["base_earnings"]
            current_month_delivery += components["delivery_cost"]
            
    current_month_earnings = int(current_month_base * 0.5 * 0.97) - int(current_month_delivery)
    
    # Общий заработок
    total_rentals = db.query(RentalHistory).filter(
        and_(
            RentalHistory.car_id.in_(car_ids),
            RentalHistory.rental_status == RentalStatus.COMPLETED,
            RentalHistory.user_id != user.id
        )
    ).all()
    
    total_base = 0.0
    total_delivery = 0.0
    
    for rental in total_rentals:
        car = next((c for c in owned_cars if c.id == rental.car_id), None)
        if car:
            components = calculate_owner_earnings(rental, car, user, return_components=True)
            total_base += components["base_earnings"]
            total_delivery += components["delivery_cost"]

    total_earnings = int(total_base * 0.5 * 0.97) - int(total_delivery)
    
    return {"current_month": current_month_earnings, "total": total_earnings}


@users_router.get("/list", response_model=UserPaginatedResponse)
async def get_users_list(
    role: Optional[str] = Query(None, description="Фильтр по роли"),
    search_query: Optional[str] = Query(None, description="Поиск по имени, фамилии, телефону, ИИН или паспорту"),
    has_active_rental: Optional[bool] = Query(None, description="Фильтр по активной аренде"),
    is_blocked: Optional[bool] = Query(None, description="Фильтр по заблокированным пользователям"),
    mvd_approved: Optional[bool] = Query(None, description="Фильтр по МВД одобрению"),
    car_status: Optional[str] = Query(None, description="Фильтр по статусу авто"),
    auto_class: Optional[List[str]] = Query(None, description="Фильтр по классу авто (A, B, C, AB, ABC)"),
    balance_filter: Optional[str] = Query(None, description="Фильтр по балансу (positive - все у кого есть деньги, negative - все у кого долг)"),
    documents_verified: Optional[bool] = Query(None, description="Фильтр по проверке документов"),
    is_active: Optional[bool] = Query(None, description="Фильтр по активности пользователя"),
    is_verified_email: Optional[bool] = Query(None, description="Фильтр по подтверждению email"),

    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(50, ge=1, le=200, description="Количество элементов на странице"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> UserPaginatedResponse:
    """Получение списка пользователей с фильтрацией и поиском"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    from sqlalchemy.orm import aliased
    from sqlalchemy import literal_column
    
    active_statuses = [
        RentalStatus.IN_USE, 
        RentalStatus.DELIVERING, 
        RentalStatus.DELIVERING_IN_PROGRESS,
        RentalStatus.RESERVED,
        RentalStatus.SCHEDULED,
        RentalStatus.DELIVERY_RESERVED
    ]
    
    active_rental_subq = (
        db.query(
            RentalHistory.user_id,
            RentalHistory.rental_status,
            RentalHistory.car_id
        )
        .filter(RentalHistory.rental_status.in_(active_statuses))
        .subquery()
    )
    
    owner_ids_subq = (
        db.query(Car.owner_id)
        .filter(Car.owner_id.isnot(None))
        .distinct()
        .subquery()
    )
    
    query = (
        db.query(
            User,
            active_rental_subq.c.rental_status,
            active_rental_subq.c.car_id,
            Car.id.label("car_id_real"),
            Car.name.label("car_name"),
            Car.plate_number.label("car_plate"),
            Car.photos.label("car_photos"),
            Car.latitude.label("car_lat"),
            Car.longitude.label("car_lon"),
            Car.fuel_level.label("car_fuel"),
            case(
                (owner_ids_subq.c.owner_id.isnot(None), True),
                else_=False
            ).label("is_owner")
        )
        .outerjoin(active_rental_subq, User.id == active_rental_subq.c.user_id)
        .outerjoin(Car, Car.id == active_rental_subq.c.car_id)
        .outerjoin(owner_ids_subq, User.id == owner_ids_subq.c.owner_id)
    )
    
    if role:
        try:
            role_enum = UserRole(role)
            query = query.filter(User.role == role_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверная роль")
    
    if is_blocked is not None:
        query = query.filter(User.is_blocked == is_blocked)

    if auto_class:
        # Обработка комбинаций типа AB, ABC
        # Если передано ["AB"], разбиваем на ["A", "B"]
        # Если передано ["A", "B"], ищем пользователей, у которых есть все указанные классы
        processed_classes = []
        for class_item in auto_class:
            if len(class_item) > 1:  # Комбинация типа AB, ABC
                processed_classes.extend(list(class_item))
            else:
                processed_classes.append(class_item)
        
        # Убираем дубликаты и приводим к верхнему регистру
        processed_classes = list(set(c.upper() for c in processed_classes))
        
        # Фильтруем пользователей, у которых есть все указанные классы
        for class_name in processed_classes:
            query = query.filter(User.auto_class.contains([class_name]))

    if balance_filter:
        if balance_filter == "positive":
            query = query.filter(User.wallet_balance > 0)
        elif balance_filter == "negative":
            query = query.filter(User.wallet_balance < 0)
    
    if documents_verified is not None:
        query = query.filter(User.documents_verified == documents_verified)
    
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    
    if is_verified_email is not None:
        query = query.filter(User.is_verified_email == is_verified_email)
    
    # Фильтр по МВД одобрению
    if mvd_approved is not None:
        if mvd_approved:
            # Одобренные: либо роль USER, либо есть Application с APPROVED статусом
            mvd_approved_condition = or_(
                User.role == UserRole.USER,
                and_(
                    Application.user_id == User.id,
                    Application.mvd_status == ApplicationStatus.APPROVED
                )
            )
            query = query.outerjoin(Application, Application.user_id == User.id).filter(mvd_approved_condition)
        else:
            # Не одобренные: роль не USER и нет Application с APPROVED статусом
            mvd_not_approved_condition = and_(
                User.role != UserRole.USER,
                or_(
                    Application.id.is_(None),
                    Application.mvd_status != ApplicationStatus.APPROVED
                )
            )
            query = query.outerjoin(Application, Application.user_id == User.id).filter(mvd_not_approved_condition)
    
    query = query.filter(User.is_deleted == False)
    
    if search_query:
        search_filter = or_(
            func.lower(User.first_name).contains(search_query.lower()),
            func.lower(User.last_name).contains(search_query.lower()),
            User.phone_number.contains(search_query),
            User.iin.contains(search_query),
            User.passport_number.contains(search_query)
        )
        query = query.filter(search_filter)
    
    if has_active_rental is True:
        query = query.filter(active_rental_subq.c.user_id.isnot(None))
    elif has_active_rental is False:
        query = query.filter(active_rental_subq.c.user_id.is_(None))
    
    count_query = db.query(func.count(func.distinct(User.id)))
    
    if role:
        try:
            role_enum = UserRole(role)
            count_query = count_query.filter(User.role == role_enum)
        except ValueError:
            pass
    if is_blocked is not None:
        count_query = count_query.filter(User.is_blocked == is_blocked)
    
    if auto_class:
        # Обработка комбинаций типа AB, ABC (та же логика, что и в query)
        processed_classes = []
        for class_item in auto_class:
            if len(class_item) > 1:  # Комбинация типа AB, ABC
                processed_classes.extend(list(class_item))
            else:
                processed_classes.append(class_item)
        
        # Убираем дубликаты и приводим к верхнему регистру
        processed_classes = list(set(c.upper() for c in processed_classes))
        
        # Фильтруем пользователей, у которых есть все указанные классы
        for class_name in processed_classes:
            count_query = count_query.filter(User.auto_class.contains([class_name]))

    if balance_filter:
        if balance_filter == "positive":
            count_query = count_query.filter(User.wallet_balance > 0)
        elif balance_filter == "negative":
            count_query = count_query.filter(User.wallet_balance < 0)
    
    if documents_verified is not None:
        count_query = count_query.filter(User.documents_verified == documents_verified)
    
    if is_active is not None:
        count_query = count_query.filter(User.is_active == is_active)
    
    if is_verified_email is not None:
        count_query = count_query.filter(User.is_verified_email == is_verified_email)
    
    # Фильтр по МВД одобрению для count_query
    if mvd_approved is not None:
        if mvd_approved:
            # Одобренные: либо роль USER, либо есть Application с APPROVED статусом
            mvd_approved_condition = or_(
                User.role == UserRole.USER,
                and_(
                    Application.user_id == User.id,
                    Application.mvd_status == ApplicationStatus.APPROVED
                )
            )
            count_query = count_query.outerjoin(Application, Application.user_id == User.id).filter(mvd_approved_condition)
        else:
            # Не одобренные: роль не USER и нет Application с APPROVED статусом
            mvd_not_approved_condition = and_(
                User.role != UserRole.USER,
                or_(
                    Application.id.is_(None),
                    Application.mvd_status != ApplicationStatus.APPROVED
                )
            )
            count_query = count_query.outerjoin(Application, Application.user_id == User.id).filter(mvd_not_approved_condition)
    
    count_query = count_query.filter(User.is_deleted == False)
    
    if search_query:
        count_query = count_query.filter(search_filter)
    
    total_count = count_query.scalar() or 0
    
    query = query.order_by(
        case(
            (active_rental_subq.c.user_id.isnot(None), 0),
            else_=1
        ),
        User.id
    )
    
    query = query.offset((page - 1) * limit).limit(limit)
    
    rows = query.all()
    
    result = []
    seen_user_ids = set()
    
    for row in rows:
        user = row[0]
        rental_status = row[1]
        car_id = row[2]
        car_name = row[4]
        car_plate = row[5]
        car_photos = row[6]
        car_lat = row[7]
        car_lon = row[8]
        car_fuel = row[9]
        is_owner = row[10] 
        
        if user.id in seen_user_ids:
            continue
        seen_user_ids.add(user.id)
        
        # Фильтр mvd_approved теперь применяется в query, поэтому здесь не нужен
        
        current_car = None
        if car_id and car_name:
            current_car = {
                "id": uuid_to_sid(car_id),
                "name": car_name,
                "plate_number": car_plate,
                "brand": car_name.split()[0] if car_name else "Unknown",
                "photos": car_photos
            }
        
        auto_class_list = []
        if user.auto_class:
            if isinstance(user.auto_class, list):
                auto_class_list = user.auto_class
            elif isinstance(user.auto_class, str):
                raw = user.auto_class.strip()
                if raw.startswith("{") and raw.endswith("}"):
                    raw = raw[1:-1]
                auto_class_list = [part.strip() for part in raw.split(",") if part.strip()]
        
        car_status_value = "FREE"
        if rental_status:
            if rental_status == RentalStatus.IN_USE:
                car_status_value = "IN_USE"
            elif rental_status == RentalStatus.RESERVED:
                car_status_value = "RESERVED"
            elif rental_status == RentalStatus.SCHEDULED:
                car_status_value = "SCHEDULED"
            elif rental_status in [RentalStatus.DELIVERING, RentalStatus.DELIVERING_IN_PROGRESS]:
                car_status_value = "DELIVERING_IN_PROGRESS"
            elif rental_status == RentalStatus.DELIVERY_RESERVED:
                car_status_value = "DELIVERY_RESERVED"
        
        if car_status_value == "FREE":
            # Используем is_owner вместо user.owned_cars (избегаем N+1)
            if is_owner:
                car_status_value = "OWNER"
            elif user.role in [UserRole.PENDING, UserRole.PENDINGTOFIRST, UserRole.PENDINGTOSECOND] or user.role.value.startswith("PENDING") or user.role.value.startswith("REJECT"):
                if user.role.value.startswith("PENDING"):
                    car_status_value = "PENDING"
        
        if car_status is not None and car_status_value != car_status:
            continue
        
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
            "is_blocked": user.is_blocked,
            "current_rental_car": current_car,
            "rating": float(user.rating) if user.rating else None,
            "carStatus": car_status_value,
            "wallet_balance": float(user.wallet_balance) if user.wallet_balance is not None else 0.0
        }
        
        converted_data = convert_uuid_response_to_sid(user_data, ["id"])
        result.append(UserListSchema(**converted_data))
    
    return {
        "items": result,
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": ceil(total_count / limit) if limit > 0 else 0
    }



@users_router.get("/map-positions", response_model=List[UserMapPositionSchema])
async def get_users_map_positions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение позиций пользователей для карты"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
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
        "is_blocked": user.is_blocked,
        "can_exit_zone": user.can_exit_zone,
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
        "pages": ceil(total_count / limit),
        "wallet_balance": float(user.wallet_balance) if user.wallet_balance else 0.0
    }


@users_router.get("/{user_id}/transactions-grouped", response_model=GroupedTransactionsPaginationSchema)
async def get_user_transactions_grouped(
    user_id: str,
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(50, ge=1, le=200, description="Количество элементов на странице"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получение истории транзакций пользователя с группировкой по аренде.
    
    Транзакции с одинаковым rental_id группируются в одну аренду (как в /admin/rentals/completed),
    а транзакции без rental_id или с уникальным rental_id показываются отдельно.
    """
    from datetime import datetime
    from sqlalchemy.orm import joinedload
    from app.models.history_model import RentalHistory, RentalStatus
    from app.models.car_model import Car, CarBodyType
    from app.admin.cars.utils import sort_car_photos
    from app.rent.utils.calculate_price import FUEL_PRICE_PER_LITER, ELECTRIC_FUEL_PRICE_PER_LITER
    
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.FINANCIER]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Получаем все транзакции пользователя с сортировкой по created_at и id для стабильности
    all_transactions = (
        db.query(WalletTransaction)
        .filter(WalletTransaction.user_id == user.id)
        .order_by(desc(WalletTransaction.created_at), desc(WalletTransaction.id))
        .all()
    )
    
    # Получаем все аренды пользователя
    all_user_rentals = (
        db.query(RentalHistory)
        .options(joinedload(RentalHistory.car), joinedload(RentalHistory.user))
        .filter(RentalHistory.user_id == user.id)
        .all()
    )
    
    # Группируем транзакции по rental_id
    from collections import defaultdict
    rental_transactions = defaultdict(list)
    standalone_transactions = []
    
    for tx in all_transactions:
        if tx.related_rental_id:
            rental_transactions[tx.related_rental_id].append(tx)
        else:
            standalone_transactions.append(tx)
    
    # Для каждой аренды добавляем транзакции по временному диапазону с проверкой цепочки балансов
    for rental in all_user_rentals:
        if rental.id not in rental_transactions:
            rental_transactions[rental.id] = []
        
        # Определяем временной диапазон аренды
        start_bound = rental.reservation_time if rental.reservation_time else rental.start_time
        end_bound = rental.end_time
        
        if start_bound and end_bound:
            # Ищем транзакции в этом диапазоне
            transactions_in_range = []
            for tx in standalone_transactions:
                if tx.created_at and start_bound <= tx.created_at <= end_bound:
                    transactions_in_range.append(tx)
            
            # Если есть транзакции в диапазоне
            if transactions_in_range:
                # Если у аренды уже есть транзакции, проверяем цепочку балансов
                if rental_transactions[rental.id]:
                    all_rental_txs = list(rental_transactions[rental.id])
                    
                    for tx in transactions_in_range:
                        # Проверяем, вписывается ли транзакция в цепочку балансов
                        can_add = False
                        
                        # Проверяем наличие balance_before и balance_after
                        if tx.balance_before is None or tx.balance_after is None:
                            continue
                        
                        # Ищем место, куда можно вставить транзакцию
                        for i, existing_tx in enumerate(all_rental_txs):
                            if existing_tx.balance_before is None or existing_tx.balance_after is None:
                                continue
                            
                            # Проверяем, может ли tx идти перед existing_tx
                            if tx.created_at and existing_tx.created_at and tx.created_at <= existing_tx.created_at:
                                if i == 0:
                                    # tx будет первой - проверяем только balance_after tx == balance_before existing_tx
                                    if abs(float(tx.balance_after) - float(existing_tx.balance_before)) < 0.01:
                                        can_add = True
                                        break
                                else:
                                    # tx между предыдущей и текущей
                                    prev_tx = all_rental_txs[i - 1]
                                    if prev_tx.balance_after is not None and prev_tx.balance_before is not None:
                                        if (abs(float(prev_tx.balance_after) - float(tx.balance_before)) < 0.01 and 
                                            abs(float(tx.balance_after) - float(existing_tx.balance_before)) < 0.01):
                                            can_add = True
                                            break
                        
                        # Или tx может быть последней
                        if not can_add and all_rental_txs:
                            last_tx = all_rental_txs[-1]
                            if (last_tx.balance_after is not None and 
                                tx.created_at and last_tx.created_at and 
                                tx.created_at >= last_tx.created_at):
                                if abs(float(last_tx.balance_after) - float(tx.balance_before)) < 0.01:
                                    can_add = True
                        
                        # Если транзакция вписывается в цепочку, добавляем её
                        if can_add:
                            rental_transactions[rental.id].append(tx)
                            all_rental_txs = list(rental_transactions[rental.id])
    
    # Убираем из standalone те транзакции, которые были добавлены к арендам
    used_tx_ids = set()
    for transactions in rental_transactions.values():
        for tx in transactions:
            used_tx_ids.add(tx.id)
    
    standalone_transactions = [tx for tx in standalone_transactions if tx.id not in used_tx_ids]
    
    # Создаем список всех элементов (аренды и отдельные транзакции)
    all_items = []
    
    # Добавляем аренды
    for rental_id, transactions in rental_transactions.items():
        rental = None
        for r in all_user_rentals:
            if r.id == rental_id:
                rental = r
                break
        
        if not rental:
            rental = (
                db.query(RentalHistory)
                .options(joinedload(RentalHistory.car), joinedload(RentalHistory.user))
                .filter(RentalHistory.id == rental_id)
                .first()
            )
        
        if rental and transactions:
            car = rental.car
            renter = rental.user
            
            # Рассчитываем fuel_fee
            fuel_fee = 0
            if rental.fuel_before is not None and rental.fuel_after is not None:
                if rental.fuel_after < rental.fuel_before:
                    fuel_consumed = ceil(rental.fuel_before) - floor(rental.fuel_after)
                    if fuel_consumed > 0 and car:
                        fuel_price = ELECTRIC_FUEL_PRICE_PER_LITER if car.body_type == CarBodyType.ELECTRIC else FUEL_PRICE_PER_LITER
                        fuel_fee = int(fuel_consumed * fuel_price)
            
            # Рассчитываем total_price_without_fuel
            total_price_without_fuel = (
                (rental.base_price or 0) +
                (rental.open_fee or 0) +
                (rental.delivery_fee or 0) +
                (rental.waiting_fee or 0) +
                (rental.overtime_fee or 0) +
                (rental.distance_fee or 0) +
                (rental.driver_fee or 0)
            )
            
            # Строим информацию о машине
            car_info = {}
            if car:
                car_info = {
                    "id": uuid_to_sid(car.id),
                    "name": car.name,
                    "plate_number": car.plate_number,
                    "engine_volume": car.engine_volume,
                    "year": car.year,
                    "drive_type": car.drive_type,
                    "transmission_type": car.transmission_type.value if car.transmission_type else None,
                    "body_type": car.body_type.value if car.body_type else None,
                    "auto_class": car.auto_class.value if car.auto_class else None,
                    "price_per_minute": car.price_per_minute,
                    "price_per_hour": car.price_per_hour,
                    "price_per_day": car.price_per_day,
                    "latitude": car.latitude,
                    "longitude": car.longitude,
                    "fuel_level": car.fuel_level,
                    "mileage": car.mileage,
                    "course": car.course,
                    "photos": sort_car_photos(car.photos or []),
                    "description": car.description,
                    "vin": car.vin,
                    "color": car.color,
                    "gps_id": car.gps_id,
                    "gps_imei": car.gps_imei,
                    "status": car.status.value if car.status else None,
                }
            
            # Строим информацию об арендаторе
            renter_info = {}
            if renter:
                is_owner = False
                if car and car.owner_id:
                    is_owner = renter.id == car.owner_id
                
                renter_info = {
                    "id": uuid_to_sid(renter.id),
                    "first_name": renter.first_name,
                    "last_name": renter.last_name,
                    "phone_number": renter.phone_number,
                    "selfie": renter.selfie_url,
                    "is_owner": is_owner
                }
            
            # Получаем tariff_display
            tariff_value = rental.rental_type.value if hasattr(rental.rental_type, 'value') else str(rental.rental_type)
            tariff_map = {
                "minutes": "Минутный",
                "hours": "Часовой",
                "days": "Суточный"
            }
            tariff_display = tariff_map.get(tariff_value, tariff_value)
            
            # Рассчитываем заработок владельца
            base_price_owner = int((rental.base_price or 0) * 0.5 * 0.97)
            waiting_fee_owner = int((rental.waiting_fee or 0) * 0.5 * 0.97)
            overtime_fee_owner = int((rental.overtime_fee or 0) * 0.5 * 0.97)
            total_owner_earnings = int(((rental.base_price or 0) + (rental.waiting_fee or 0) + (rental.overtime_fee or 0)) * 0.5 * 0.97)
            
            # Строим список транзакций с правильной сортировкой по created_at и id
            transactions_list = []
            sorted_transactions = sorted(
                transactions, 
                key=lambda x: (x.created_at or datetime.min, x.id or '')
            )
            for tx in sorted_transactions:
                transactions_list.append({
                    "id": uuid_to_sid(tx.id),
                    "amount": float(tx.amount),
                    "transaction_type": tx.transaction_type.value if hasattr(tx.transaction_type, 'value') else str(tx.transaction_type),
                    "description": tx.description,
                    "balance_before": float(tx.balance_before),
                    "balance_after": float(tx.balance_after),
                    "tracking_id": tx.tracking_id,
                    "created_at": tx.created_at.isoformat() if tx.created_at else None,
                    "related_rental_id": uuid_to_sid(tx.related_rental_id) if tx.related_rental_id else None,
                })
            
            # Получаем balance_before из первой транзакции и balance_after из последней
            first_tx = sorted_transactions[0] if sorted_transactions else None
            last_tx = sorted_transactions[-1] if sorted_transactions else None
            rental_balance_before = float(first_tx.balance_before) if first_tx and first_tx.balance_before is not None else 0.0
            rental_balance_after = float(last_tx.balance_after) if last_tx and last_tx.balance_after is not None else 0.0
            
            # Формируем объект аренды
            rental_data = {
                "rental_id": uuid_to_sid(rental.id),
                "car": car_info,
                "reservation_time": rental.reservation_time.isoformat() if rental.reservation_time else None,
                "start_time": rental.start_time.isoformat() if rental.start_time else None,
                "end_time": rental.end_time.isoformat() if rental.end_time else None,
                "duration": rental.duration,
                "already_payed": rental.already_payed or 0,
                "total_price": rental.total_price or 0,
                "total_price_without_fuel": total_price_without_fuel,
                "tariff": tariff_value,
                "tariff_display": tariff_display,
                "base_price": rental.base_price or 0,
                "open_fee": rental.open_fee or 0,
                "delivery_fee": rental.delivery_fee or 0,
                "fuel_fee": fuel_fee,
                "waiting_fee": rental.waiting_fee or 0,
                "overtime_fee": rental.overtime_fee or 0,
                "distance_fee": rental.distance_fee or 0,
                "with_driver": rental.with_driver or False,
                "driver_fee": rental.driver_fee or 0,
                "rebooking_fee": rental.rebooking_fee or 0,
                "base_price_owner": base_price_owner,
                "waiting_fee_owner": waiting_fee_owner,
                "overtime_fee_owner": overtime_fee_owner,
                "total_owner_earnings": total_owner_earnings,
                "fuel_before": float(rental.fuel_before) if rental.fuel_before is not None else None,
                "fuel_after": float(rental.fuel_after) if rental.fuel_after is not None else None,
                "renter": renter_info,
                "transactions": transactions_list,
                "balance_before": rental_balance_before,
                "balance_after": rental_balance_after,
            }
            
            # Используем самую раннюю дату транзакции аренды для сортировки
            # Если нет транзакций, используем reservation_time или start_time аренды
            # Сортируем по created_at и id для стабильности при одинаковых временах
            if transactions:
                earliest_tx = min(
                    transactions, 
                    key=lambda x: (x.created_at or datetime.max, x.id or '')
                )
                sort_date = earliest_tx.created_at
            else:
                sort_date = rental.reservation_time if rental.reservation_time else rental.start_time
            
            all_items.append({
                "type": "rental",
                "created_at": sort_date,
                "rental": rental_data,
                "transaction": None,
                "sort_id": rental.id
            })
    
    # Добавляем отдельные транзакции
    for tx in standalone_transactions:
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
        all_items.append({
            "type": "transaction",
            "created_at": tx.created_at,
            "transaction": WalletTransactionSchema(**tx_data),
            "rental": None,
            "sort_id": tx.id
        })
    
    # Сортируем все элементы по дате (самые новые сначала) с учетом id для стабильности
    # Используем кортеж (created_at, sort_id) для стабильной сортировки при одинаковых временах
    all_items.sort(key=lambda x: (
        x["created_at"] if x["created_at"] else datetime.min,
        x.get("sort_id", "")
    ), reverse=True)
    
    # Применяем пагинацию
    total_count = len(all_items)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated_items = all_items[start_idx:end_idx]
    
    # Формируем финальный список (удаляем sort_id перед созданием схемы)
    result_items = []
    for item in paginated_items:
        item_copy = {k: v for k, v in item.items() if k != "sort_id"}
        result_items.append(GroupedTransactionItemSchema(**item_copy))
    
    return {
        "items": result_items,
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": ceil(total_count / limit) if limit > 0 else 0,
        "wallet_balance": float(user.wallet_balance) if user.wallet_balance else 0.0
    }


@users_router.delete("/{user_id}/transactions/{transaction_id}")
async def delete_user_transaction(
    user_id: str,
    transaction_id: str,
    adjust_balance: bool = Query(False, description="Если true - откатывает влияние транзакции на баланс и пересчитывает последующие"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Удаление транзакции пользователя (только для ADMIN).
    
    - adjust_balance=false: только удаляет запись транзакции
    - adjust_balance=true: удаляет транзакцию, пересчитывает balance_before/balance_after 
      для всех последующих транзакций и обновляет баланс пользователя
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав. Только ADMIN может удалять транзакции.")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    tx_uuid = safe_sid_to_uuid(transaction_id)
    transaction = db.query(WalletTransaction).filter(
        WalletTransaction.id == tx_uuid,
        WalletTransaction.user_id == user_uuid
    ).first()
    
    if not transaction:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")
    
    tx_data = {
        "id": uuid_to_sid(transaction.id),
        "amount": float(transaction.amount),
        "transaction_type": transaction.transaction_type.value if hasattr(transaction.transaction_type, "value") else str(transaction.transaction_type),
        "description": transaction.description,
        "balance_before": float(transaction.balance_before) if transaction.balance_before else 0,
        "balance_after": float(transaction.balance_after) if transaction.balance_after else 0
    }
    
    old_balance = float(user.wallet_balance or 0)
    new_balance = old_balance
    recalculated_count = 0
    
    if adjust_balance:
        tx_created_at = transaction.created_at
        tx_balance_before = float(transaction.balance_before) if transaction.balance_before else 0
        
        db.delete(transaction)
        db.flush()
        
        new_balance = recalculate_transactions_after(
            db=db,
            user_id=user_uuid,
            after_time=tx_created_at,
            base_balance=tx_balance_before
        )
        
        subsequent_count = db.query(WalletTransaction).filter(
            WalletTransaction.user_id == user_uuid,
            WalletTransaction.created_at > tx_created_at
        ).count()
        recalculated_count = subsequent_count
        
        user.wallet_balance = new_balance
    else:
        db.delete(transaction)
    
    log_action(
        db,
        actor_id=current_user.id,
        action="delete_transaction",
        entity_type="wallet_transaction",
        entity_id=tx_uuid,
        details={
            "user_id": user_id,
            "adjust_balance": adjust_balance,
            "transaction_data": tx_data
        }
    )
    
    db.commit()
    
    return {
        "success": True,
        "message": "Транзакция удалена" + (f" и пересчитано {recalculated_count} последующих транзакций" if adjust_balance else ""),
        "deleted_transaction": tx_data,
        "balance_adjusted": adjust_balance,
        "recalculated_transactions_count": recalculated_count,
        "old_balance": old_balance,
        "new_balance": new_balance
    }


@users_router.patch("/{user_id}/transactions/{transaction_id}")
async def edit_user_transaction(
    user_id: str,
    transaction_id: str,
    amount: Optional[float] = Form(None, description="Новая сумма транзакции"),
    description: Optional[str] = Form(None, description="Новое описание"),
    adjust_balance: bool = Form(False, description="Если true - пересчитывает все последующие транзакции"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Редактирование транзакции пользователя (только для ADMIN).
    
    - amount: новая сумма (если указана)
    - description: новое описание (если указано)
    - adjust_balance: если true, пересчитывает balance_before/balance_after для всех последующих транзакций
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав. Только ADMIN может редактировать транзакции.")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    tx_uuid = safe_sid_to_uuid(transaction_id)
    transaction = db.query(WalletTransaction).filter(
        WalletTransaction.id == tx_uuid,
        WalletTransaction.user_id == user_uuid
    ).first()
    
    if not transaction:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")
    
    old_amount = float(transaction.amount)
    old_description = transaction.description
    old_balance = float(user.wallet_balance or 0)
    new_balance = old_balance
    recalculated_count = 0
    
    if description is not None:
        transaction.description = description
    
    if amount is not None:
        new_amount = amount
        amount_diff = new_amount - old_amount
        
        transaction.amount = new_amount
        
        tx_balance_before = float(transaction.balance_before) if transaction.balance_before else 0
        transaction.balance_after = tx_balance_before + new_amount
        
        if adjust_balance and amount_diff != 0:
            tx_created_at = transaction.created_at
            
            db.flush()
            
            new_balance = recalculate_transactions_after(
                db=db,
                user_id=user_uuid,
                after_time=tx_created_at,
                base_balance=float(transaction.balance_after)
            )
            
            subsequent_count = db.query(WalletTransaction).filter(
                WalletTransaction.user_id == user_uuid,
                WalletTransaction.created_at > tx_created_at
            ).count()
            recalculated_count = subsequent_count
            
            user.wallet_balance = new_balance
    
    db.commit()
    db.refresh(transaction)

    log_action(
        db,
        actor_id=current_user.id,
        action="edit_transaction",
        entity_type="wallet_transaction",
        entity_id=transaction.id,
        details={
            "old_amount": old_amount,
            "new_amount": float(transaction.amount),
            "adjust_balance": adjust_balance,
            "description_changed": old_description != transaction.description
        }
    )
    db.commit()
    
    return {
        "success": True,
        "message": "Транзакция обновлена" + (f" и пересчитано {recalculated_count} последующих транзакций" if recalculated_count > 0 else ""),
        "transaction": {
            "id": uuid_to_sid(transaction.id),
            "old_amount": old_amount,
            "new_amount": float(transaction.amount),
            "old_description": old_description,
            "new_description": transaction.description,
            "balance_before": float(transaction.balance_before) if transaction.balance_before else None,
            "balance_after": float(transaction.balance_after) if transaction.balance_after else None
        },
        "balance_adjusted": adjust_balance and recalculated_count > 0,
        "recalculated_transactions_count": recalculated_count,
        "old_user_balance": old_balance,
        "new_user_balance": new_balance
    }


@users_router.patch("/trips/{trip_id}", response_model=TripDetailSchema, summary="Редактирование данных поездки (Form Data)")
async def update_trip_details(
    request: Request,
    trip_id: str,
    car_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    delivery_mechanic_id: Optional[str] = Form(None),
    mechanic_inspector_id: Optional[str] = Form(None),
    
    rental_type: Optional[str] = Form(None),
    rental_status: Optional[str] = Form(None),
    duration: Optional[str] = Form(None),
    
    start_time: Optional[str] = Form(None),
    end_time: Optional[str] = Form(None),
    reservation_time: Optional[str] = Form(None),
    scheduled_start_time: Optional[str] = Form(None),
    scheduled_end_time: Optional[str] = Form(None),
    is_advance_booking: Optional[str] = Form(None),
    
    base_price: Optional[str] = Form(None),
    open_fee: Optional[str] = Form(None),
    delivery_fee: Optional[str] = Form(None),
    waiting_fee: Optional[str] = Form(None),
    overtime_fee: Optional[str] = Form(None),
    distance_fee: Optional[str] = Form(None),
    already_payed: Optional[str] = Form(None),
    total_price: Optional[str] = Form(None),
    driver_fee: Optional[str] = Form(None),
    rebooking_fee: Optional[str] = Form(None),
    delivery_penalty_fee: Optional[str] = Form(None),
    
    start_latitude: Optional[str] = Form(None),
    start_longitude: Optional[str] = Form(None),
    end_latitude: Optional[str] = Form(None),
    end_longitude: Optional[str] = Form(None),
    delivery_latitude: Optional[str] = Form(None),
    delivery_longitude: Optional[str] = Form(None),
    delivery_start_latitude: Optional[str] = Form(None),
    delivery_start_longitude: Optional[str] = Form(None),
    delivery_end_latitude: Optional[str] = Form(None),
    delivery_end_longitude: Optional[str] = Form(None),
    mechanic_inspection_start_latitude: Optional[str] = Form(None),
    mechanic_inspection_start_longitude: Optional[str] = Form(None),
    mechanic_inspection_end_latitude: Optional[str] = Form(None),
    mechanic_inspection_end_longitude: Optional[str] = Form(None),
    
    fuel_before: Optional[str] = Form(None),
    fuel_after: Optional[str] = Form(None),
    fuel_after_main_tariff: Optional[str] = Form(None),
    mileage_before: Optional[str] = Form(None),
    mileage_after: Optional[str] = Form(None),
    
    delivery_start_time: Optional[str] = Form(None),
    delivery_end_time: Optional[str] = Form(None),
    
    mechanic_inspection_start_time: Optional[str] = Form(None),
    mechanic_inspection_end_time: Optional[str] = Form(None),
    mechanic_inspection_status: Optional[str] = Form(None),
    mechanic_inspection_comment: Optional[str] = Form(None),
    
    rating: Optional[str] = Form(None),
    with_driver: Optional[str] = Form(None),
    
    photos_before: Optional[List[UploadFile]] = File(None, description="Фото до аренды"),
    photos_after: Optional[List[UploadFile]] = File(None, description="Фото после аренды"),
    mechanic_photos_before: Optional[List[UploadFile]] = File(None, description="Фото механика до"),
    mechanic_photos_after: Optional[List[UploadFile]] = File(None, description="Фото механика после"),
    delivery_photos_before: Optional[List[UploadFile]] = File(None, description="Фото доставки до"),
    delivery_photos_after: Optional[List[UploadFile]] = File(None, description="Фото доставки после"),
    
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Редактирование данных поездки с использованием multipart/form-data.
    
    Поддерживает загрузку файлов.
    Загруженные файлы сохраняются и добавляются к списку фото.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    form = await request.form()
    
    def get_files_from_form(field_name: str) -> List:
        files = []
        for key, value in form.multi_items():
            if key == field_name and hasattr(value, 'filename') and hasattr(value, 'read'):
                if value.filename: 
                    files.append(value)
        return files
    
    filtered_photos_before = get_files_from_form("photos_before")
    filtered_photos_after = get_files_from_form("photos_after")
    filtered_mechanic_photos_before = get_files_from_form("mechanic_photos_before")
    filtered_mechanic_photos_after = get_files_from_form("mechanic_photos_after")
    filtered_delivery_photos_before = get_files_from_form("delivery_photos_before")
    filtered_delivery_photos_after = get_files_from_form("delivery_photos_after")
        
    rental_uuid = safe_sid_to_uuid(trip_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    
    if not rental:
        raise HTTPException(status_code=404, detail="Поездка не найдена")

    async def process_photos_upload(
        new_files: Optional[List[UploadFile]], 
        db_urls: List[str],
        save_folder: str
    ) -> List[str]:
        final_urls = list(db_urls or [])
             
        if new_files:
            for file in new_files:
                try:
                    file_url = await save_file(file, rental.id, f"uploads/rents/{rental.id}/{save_folder}")
                    final_urls.append(file_url)
                except Exception as e:
                    print(f"Error saving file {file.filename}: {e}")
                    pass
                
        return final_urls
    
    if filtered_photos_before:
        rental.photos_before = await process_photos_upload(filtered_photos_before, rental.photos_before, "before/admin_upload")
        
    if filtered_photos_after:
        rental.photos_after = await process_photos_upload(filtered_photos_after, rental.photos_after, "after/admin_upload")
        
    if filtered_mechanic_photos_before:
        rental.mechanic_photos_before = await process_photos_upload(filtered_mechanic_photos_before, rental.mechanic_photos_before, "before/mechanic_upload")

    if filtered_mechanic_photos_after:
        rental.mechanic_photos_after = await process_photos_upload(filtered_mechanic_photos_after, rental.mechanic_photos_after, "after/mechanic_upload")

    if filtered_delivery_photos_before:
        rental.delivery_photos_before = await process_photos_upload(filtered_delivery_photos_before, rental.delivery_photos_before, "before/delivery_upload")

    if filtered_delivery_photos_after:
        rental.delivery_photos_after = await process_photos_upload(filtered_delivery_photos_after, rental.delivery_photos_after, "after/delivery_upload")

    update_data = {}
    
    def set_uuid(field_name: str, value: Optional[str]):
        if value and value.strip():
            update_data[field_name] = safe_sid_to_uuid(value.strip())
    
    def set_float(field_name: str, value: Optional[str]):
        if value and value.strip():
            try:
                update_data[field_name] = float(value.strip())
            except ValueError:
                pass
    
    def set_int(field_name: str, value: Optional[str]):
        if value and value.strip():
            try:
                update_data[field_name] = int(value.strip())
            except ValueError:
                pass
    
    def set_datetime(field_name: str, value: Optional[str]):
        if value and value.strip():
            try:
                update_data[field_name] = parse_datetime_to_local(value.strip())
            except ValueError:
                pass
    
    def set_str(field_name: str, value: Optional[str]):
        if value and value.strip():
            update_data[field_name] = value.strip()
    
    def set_bool(field_name: str, value: Optional[str]):
        if value and value.strip():
            update_data[field_name] = value.strip().lower() in ["true", "1", "yes"]
    
    set_uuid("car_id", car_id)
    set_uuid("user_id", user_id)
    set_uuid("delivery_mechanic_id", delivery_mechanic_id)
    set_uuid("mechanic_inspector_id", mechanic_inspector_id)
    
    if rental_type and rental_type.strip():
        try:
            update_data["rental_type"] = RentalType(rental_type.strip().lower())
        except ValueError:
            pass
    if rental_status and rental_status.strip():
        try:
            update_data["rental_status"] = RentalStatus(rental_status.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный статус аренды")
    set_int("duration", duration)
    
    set_datetime("start_time", start_time)
    set_datetime("end_time", end_time)
    set_datetime("reservation_time", reservation_time)
    set_datetime("scheduled_start_time", scheduled_start_time)
    set_datetime("scheduled_end_time", scheduled_end_time)
    set_str("is_advance_booking", is_advance_booking)
    
    set_int("base_price", base_price)
    set_int("open_fee", open_fee)
    set_int("delivery_fee", delivery_fee)
    set_int("waiting_fee", waiting_fee)
    set_int("overtime_fee", overtime_fee)
    set_int("distance_fee", distance_fee)
    set_int("already_payed", already_payed)
    set_int("total_price", total_price)
    set_int("driver_fee", driver_fee)
    set_int("rebooking_fee", rebooking_fee)
    set_int("delivery_penalty_fee", delivery_penalty_fee)
    
    set_float("start_latitude", start_latitude)
    set_float("start_longitude", start_longitude)
    set_float("end_latitude", end_latitude)
    set_float("end_longitude", end_longitude)
    set_float("delivery_latitude", delivery_latitude)
    set_float("delivery_longitude", delivery_longitude)
    set_float("delivery_start_latitude", delivery_start_latitude)
    set_float("delivery_start_longitude", delivery_start_longitude)
    set_float("delivery_end_latitude", delivery_end_latitude)
    set_float("delivery_end_longitude", delivery_end_longitude)
    set_float("mechanic_inspection_start_latitude", mechanic_inspection_start_latitude)
    set_float("mechanic_inspection_start_longitude", mechanic_inspection_start_longitude)
    set_float("mechanic_inspection_end_latitude", mechanic_inspection_end_latitude)
    set_float("mechanic_inspection_end_longitude", mechanic_inspection_end_longitude)
    
    set_float("fuel_before", fuel_before)
    set_float("fuel_after", fuel_after)
    set_float("fuel_after_main_tariff", fuel_after_main_tariff)
    set_int("mileage_before", mileage_before)
    set_int("mileage_after", mileage_after)
    
    set_datetime("delivery_start_time", delivery_start_time)
    set_datetime("delivery_end_time", delivery_end_time)
    
    set_datetime("mechanic_inspection_start_time", mechanic_inspection_start_time)
    set_datetime("mechanic_inspection_end_time", mechanic_inspection_end_time)
    set_str("mechanic_inspection_status", mechanic_inspection_status)
    set_str("mechanic_inspection_comment", mechanic_inspection_comment)
    
    set_float("rating", rating)
    set_bool("with_driver", with_driver)

    
    for key, value in update_data.items():
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
        client_comment=rental.review.comment if rental.review else None,
        mechanic_comment=rental.review.mechanic_comment if rental.review else None,
        client_rating=rental.review.rating if rental.review else None,
        mechanic_rating=rental.review.mechanic_rating if rental.review else None,
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


@users_router.post("/trips/reserve", summary="Забронировать машину за клиента (Admin)")
async def admin_reserve_car(
    car_id: str = Form(..., description="ID машины"),
    user_id: str = Form(..., description="ID пользователя"),
    rental_type: str = Form(..., description="Тип аренды: MINUTES, HOURS, DAYS"),
    duration: Optional[str] = Form(None, description="Длительность (для HOURS/DAYS)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Эндпоинт для админа для бронирования машины за клиента.
    
    - Создает аренду со статусом RESERVED
    - Проверяет минимальный баланс клиента
    - Обновляет статус машины на RESERVED
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    parsed_duration = None
    if duration and duration.strip():
        try:
            parsed_duration = int(duration.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Duration должен быть целым числом")
    
    rental_type_map = {
        "MINUTES": RentalType.MINUTES,
        "HOURS": RentalType.HOURS,
        "DAYS": RentalType.DAYS
    }
    rental_type_enum = rental_type_map.get(rental_type.upper())
    if not rental_type_enum:
        raise HTTPException(status_code=400, detail="Неверный тип аренды. Допустимые: MINUTES, HOURS, DAYS")
    
    if rental_type_enum in [RentalType.HOURS, RentalType.DAYS] and not parsed_duration:
        raise HTTPException(status_code=400, detail="Duration обязателен для аренды по часам/дням")
    
    target_user_uuid = safe_sid_to_uuid(user_id)
    target_user = db.query(User).filter(User.id == target_user_uuid).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    car_uuid = safe_sid_to_uuid(car_id)
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    if car.status not in [CarStatus.FREE, CarStatus.PENDING]:
        raise HTTPException(status_code=400, detail=f"Машина недоступна для бронирования. Текущий статус: {car.status.value}")
    
    active_rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == target_user_uuid,
        RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
    ).first()
    
    if active_rental:
        if active_rental.rental_status == RentalStatus.IN_USE:
            raise HTTPException(status_code=400, detail="У пользователя уже есть активная аренда")
        if active_rental.rental_status == RentalStatus.RESERVED:
            raise HTTPException(status_code=400, detail="У пользователя уже есть активное бронирование")
    
    is_owner = (car.owner_id == target_user_uuid)
    required_balance = calc_required_balance(
        rental_type=rental_type_enum,
        duration=parsed_duration,
        car=car,
        include_delivery=False,
        is_owner=is_owner,
        with_driver=False
    )
    
    if target_user.wallet_balance < required_balance:
        formatted_required = f"{required_balance:,}".replace(",", " ")
        formatted_balance = f"{int(target_user.wallet_balance):,}".replace(",", " ")
        raise HTTPException(
            status_code=402, 
            detail=f"Недостаточно средств на балансе клиента. Требуется минимум: {formatted_required} ₸, доступно: {formatted_balance} ₸"
        )
    
    open_fee = get_open_price(car)
    
    new_rental = RentalHistory(
        user_id=target_user_uuid,
        car_id=car_uuid,
        rental_type=rental_type_enum,
        duration=parsed_duration,
        rental_status=RentalStatus.RESERVED,
        reservation_time=get_local_time(),
        start_latitude=car.latitude or 0,
        start_longitude=car.longitude or 0,
        open_fee=open_fee,
        base_price=required_balance,
    )
    
    db.add(new_rental)
    
    car.status = CarStatus.RESERVED
    car.current_renter_id = target_user_uuid
    
    target_user.last_activity_at = get_local_time()
    
    db.commit()
    db.refresh(new_rental)
    
    asyncio.create_task(notify_user_status_update(str(target_user.id)))
    
    return {
        "success": True,
        "message": "Машина успешно забронирована за клиента",
        "rental_id": uuid_to_sid(new_rental.id),
        "user_id": uuid_to_sid(new_rental.user_id),
        "car_id": uuid_to_sid(new_rental.car_id),
        "rental_type": new_rental.rental_type.value,
        "rental_status": new_rental.rental_status.value,
        "duration": new_rental.duration,
        "required_balance": required_balance,
        "reservation_time": new_rental.reservation_time.isoformat(),
        "reserved_by_admin": uuid_to_sid(current_user.id)
    }

@users_router.post("/trips/start", summary="Начать аренду за клиента (Admin)")
async def admin_start_rental(
    request: Request,
    car_id: str = Form(..., description="ID машины"),
    user_id: str = Form(..., description="ID пользователя"),
    rental_type: str = Form(..., description="Тип аренды: MINUTES, HOURS, DAYS"),
    duration: Optional[str] = Form(None, description="Длительность (для HOURS/DAYS)"),
    selfie: UploadFile = File(default=None, description="Селфи пользователя"),
    car_photos: List[UploadFile] = File(default=[], description="Фото кузова (1-10)"),
    interior_photos: List[UploadFile] = File(default=[], description="Фото салона (1-10)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Эндпоинт для админа для начала аренды за клиента.
    
    - Создает аренду со статусом IN_USE
    - Сохраняет фотографии (селфи, кузов, салон)
    - Списывает open_fee с кошелька пользователя
    - Обновляет статус машины на IN_USE
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    parsed_duration = None
    if duration and duration.strip():
        try:
            parsed_duration = int(duration.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Duration должен быть целым числом")
    
    form = await request.form()
    
    def get_files_from_form(field_name: str) -> List:
        files = []
        for key, value in form.multi_items():
            if key == field_name and hasattr(value, 'filename') and hasattr(value, 'read'):
                if value.filename:
                    files.append(value)
        return files
    
    def get_single_file_from_form(field_name: str):
        for key, value in form.multi_items():
            if key == field_name and hasattr(value, 'filename') and hasattr(value, 'read'):
                if value.filename:
                    return value
        return None
    
    filtered_selfie = get_single_file_from_form("selfie")
    filtered_car_photos = get_files_from_form("car_photos")
    filtered_interior_photos = get_files_from_form("interior_photos")
    
    rental_type_map = {
        "MINUTES": RentalType.MINUTES,
        "HOURS": RentalType.HOURS,
        "DAYS": RentalType.DAYS
    }
    rental_type_enum = rental_type_map.get(rental_type.upper())
    if not rental_type_enum:
        raise HTTPException(status_code=400, detail="Неверный тип аренды. Допустимые: MINUTES, HOURS, DAYS")
    
    if rental_type_enum in [RentalType.HOURS, RentalType.DAYS] and not parsed_duration:
        raise HTTPException(status_code=400, detail="Duration обязателен для аренды по часам/дням")
    
    target_user_uuid = safe_sid_to_uuid(user_id)
    target_user = db.query(User).filter(User.id == target_user_uuid).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    car_uuid = safe_sid_to_uuid(car_id)
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    if car.status not in [CarStatus.FREE, CarStatus.RESERVED, CarStatus.PENDING]:
        raise HTTPException(status_code=400, detail=f"Машина недоступна для аренды. Текущий статус: {car.status.value}")
    
    active_rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == target_user_uuid,
        RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
    ).first()
    
    if active_rental:
        if active_rental.rental_status == RentalStatus.IN_USE:
            raise HTTPException(status_code=400, detail="У пользователя уже есть активная аренда в использовании")
        
        if active_rental.rental_status == RentalStatus.RESERVED and active_rental.car_id == car_uuid:
            is_owner = (car.owner_id == target_user_uuid)
            
            # Рассчитываем base_price для часового/суточного тарифа
            base_price = 0
            if rental_type_enum == RentalType.MINUTES:
                base_price = 0
            elif rental_type_enum == RentalType.HOURS:
                if parsed_duration is None:
                    raise HTTPException(status_code=400, detail="Duration обязателен для аренды по часам")
                base_price = calculate_total_price(rental_type_enum, parsed_duration, car.price_per_hour or 0, car.price_per_day or 0)
            elif rental_type_enum == RentalType.DAYS:
                if parsed_duration is None:
                    raise HTTPException(status_code=400, detail="Duration обязателен для посуточной аренды")
                base_price = calculate_total_price(rental_type_enum, parsed_duration, car.price_per_hour or 0, car.price_per_day or 0)
            
            # Рассчитываем open_fee используя get_open_price
            open_fee_value = get_open_price(car) if rental_type_enum in [RentalType.MINUTES, RentalType.HOURS] else 0
            
            required_balance = calc_required_balance(
                rental_type=rental_type_enum,
                duration=parsed_duration,
                car=car,
                include_delivery=False,
                is_owner=is_owner,
                with_driver=False
            )
            
            if target_user.wallet_balance < required_balance:
                formatted_required = f"{required_balance:,}".replace(",", " ")
                formatted_balance = f"{int(target_user.wallet_balance):,}".replace(",", " ")
                raise HTTPException(
                    status_code=402, 
                    detail=f"Недостаточно средств на балансе клиента. Требуется минимум: {formatted_required} ₸, доступно: {formatted_balance} ₸"
                )
            
            # Convert existing reservation to IN_USE
            existing_rental = active_rental
            existing_rental.rental_status = RentalStatus.IN_USE
            existing_rental.rental_type = rental_type_enum
            existing_rental.duration = parsed_duration
            existing_rental.start_time = get_local_time()
            existing_rental.start_latitude = car.latitude
            existing_rental.start_longitude = car.longitude
            existing_rental.base_price = base_price
            existing_rental.open_fee = open_fee_value
            existing_rental.total_price = base_price + open_fee_value + (existing_rental.delivery_fee or 0)
            
            photos_before = list(existing_rental.photos_before or [])
            if filtered_selfie:
                selfie_url = await save_file(filtered_selfie, existing_rental.id, f"uploads/rents/{existing_rental.id}/before/selfie/")
                photos_before.append(selfie_url)
            for photo in filtered_car_photos:
                car_url = await save_file(photo, existing_rental.id, f"uploads/rents/{existing_rental.id}/before/car/")
                photos_before.append(car_url)
            for photo in filtered_interior_photos:
                interior_url = await save_file(photo, existing_rental.id, f"uploads/rents/{existing_rental.id}/before/interior/")
                photos_before.append(interior_url)
            existing_rental.photos_before = photos_before
            existing_rental.fuel_before = car.fuel_level
            existing_rental.mileage_before = car.mileage
            
            # Списываем деньги с кошелька пользователя
            total_charged = 0
            balance_before = float(target_user.wallet_balance or 0)
            
            if not is_owner:
                if rental_type_enum in [RentalType.HOURS, RentalType.DAYS]:
                    # 1. Базовая стоимость аренды
                    if base_price > 0:
                        record_wallet_transaction(
                            db,
                            user=target_user,
                            amount=-base_price,
                            ttype=WalletTransactionType.RENT_BASE_CHARGE,
                            description=f"Оплата аренды: {parsed_duration} {'час(ов)' if rental_type_enum == RentalType.HOURS else 'день(дней)'}",
                            related_rental=existing_rental,
                            balance_before_override=balance_before
                        )
                        target_user.wallet_balance -= base_price
                        total_charged += base_price
                        balance_before = float(target_user.wallet_balance)
                    
                    # 2. Открытие дверей (только для часового тарифа)
                    if open_fee_value > 0:
                        record_wallet_transaction(
                            db,
                            user=target_user,
                            amount=-open_fee_value,
                            ttype=WalletTransactionType.RENT_BASE_CHARGE,
                            description="Оплата открытия дверей",
                            related_rental=existing_rental,
                            balance_before_override=balance_before
                        )
                        target_user.wallet_balance -= open_fee_value
                        total_charged += open_fee_value
                elif rental_type_enum == RentalType.MINUTES:
                    # Для поминутного тарифа списываем только open_fee
                    if open_fee_value > 0:
                        record_wallet_transaction(
                            db,
                            user=target_user,
                            amount=-open_fee_value,
                            ttype=WalletTransactionType.RENT_BASE_CHARGE,
                            description="Оплата открытия дверей",
                            related_rental=existing_rental,
                            balance_before_override=balance_before
                        )
                        target_user.wallet_balance -= open_fee_value
                        total_charged += open_fee_value
                
                # Обновляем already_payed
                if target_user.wallet_balance >= 0:
                    existing_rental.already_payed = total_charged + (existing_rental.already_payed or 0)
                else:
                    existing_rental.already_payed = existing_rental.already_payed or 0
            else:
                # Для владельца все бесплатно
                existing_rental.base_price = 0
                existing_rental.open_fee = 0
                existing_rental.total_price = 0
                existing_rental.already_payed = 0
            
            car.status = CarStatus.IN_USE
            car.current_renter_id = target_user_uuid
            target_user.last_activity_at = get_local_time()
            
            db.commit()
            db.refresh(existing_rental)
            
            # Отправляем уведомление в Telegram на оба бота о начале аренды
            try:
                name_parts = []
                if target_user.first_name:
                    name_parts.append(target_user.first_name)
                if target_user.middle_name:
                    name_parts.append(target_user.middle_name)
                if target_user.last_name:
                    name_parts.append(target_user.last_name)
                full_name = " ".join(name_parts) if name_parts else "Не указано"
                
                notification_text = (
                    f"Начало аренды\n\n"
                    f"Клиент: {full_name}\n"
                    f"Телефон: {target_user.phone_number or 'Не указан'}\n"
                    f"Машина: {car.name}\n"
                    f"Гос. номер: {car.plate_number or 'Не указан'}\n"
                    f"Тип аренды: {rental_type_enum.value}\n"
                    f"ID аренды: {uuid_to_sid(existing_rental.id)}\n"
                    f"Запущено администратором: {current_user.first_name or 'Admin'}"
                )
                
                async def _send_telegram_notification(text: str, chat_id: int, bot_token: str):
                    try:
                        async with httpx.AsyncClient() as client:
                            await client.post(
                                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                json={"chat_id": chat_id, "text": text}
                            )
                    except Exception as e:
                        print(f"Ошибка отправки Telegram уведомления в {chat_id}: {e}")
                
                # Список чатов для уведомлений
                chat_ids = [965048905, 5941825713, 860991388, 1594112444, 808277096, 7656716395, 964255811, 8522837235, 797693964]
                
                if TELEGRAM_BOT_TOKEN:
                    for chat_id in chat_ids:
                        asyncio.create_task(_send_telegram_notification(notification_text, chat_id, TELEGRAM_BOT_TOKEN))
                
                if TELEGRAM_BOT_TOKEN_2:
                    for chat_id in chat_ids:
                        asyncio.create_task(_send_telegram_notification(notification_text, chat_id, TELEGRAM_BOT_TOKEN_2))
                        
            except Exception as e:
                print(f"Не удалось отправить Telegram уведомление о начале аренды: {e}")
            
            asyncio.create_task(notify_user_status_update(str(target_user.id)))
            
            return {
                "success": True,
                "message": "Бронь переведена в активную аренду",
                "rental_id": uuid_to_sid(existing_rental.id),
                "user_id": uuid_to_sid(existing_rental.user_id),
                "car_id": uuid_to_sid(existing_rental.car_id),
                "rental_type": existing_rental.rental_type.value,
                "rental_status": existing_rental.rental_status.value,
                "start_time": existing_rental.start_time.isoformat(),
                "open_fee": open_fee_value,
                "base_price": base_price,
                "total_charged": total_charged,
                "photos_count": len(photos_before),
                "new_balance": float(target_user.wallet_balance),
                "started_by_admin": uuid_to_sid(current_user.id)
            }
        
        if active_rental.rental_status == RentalStatus.RESERVED and active_rental.car_id != car_uuid:
            active_rental.rental_status = RentalStatus.CANCELLED
            active_rental.end_time = get_local_time()
    
    is_owner = (car.owner_id == target_user_uuid)
    
    # Рассчитываем base_price для часового/суточного тарифа
    base_price = 0
    if rental_type_enum == RentalType.MINUTES:
        base_price = 0  # Для поминутного тарифа base_price = 0
    elif rental_type_enum == RentalType.HOURS:
        if parsed_duration is None:
            raise HTTPException(status_code=400, detail="Duration обязателен для аренды по часам")
        base_price = calculate_total_price(rental_type_enum, parsed_duration, car.price_per_hour or 0, car.price_per_day or 0)
    elif rental_type_enum == RentalType.DAYS:
        if parsed_duration is None:
            raise HTTPException(status_code=400, detail="Duration обязателен для посуточной аренды")
        base_price = calculate_total_price(rental_type_enum, parsed_duration, car.price_per_hour or 0, car.price_per_day or 0)
    
    # Рассчитываем open_fee используя get_open_price
    open_fee_value = get_open_price(car) if rental_type_enum in [RentalType.MINUTES, RentalType.HOURS] else 0
    
    required_balance = calc_required_balance(
        rental_type=rental_type_enum,
        duration=parsed_duration,
        car=car,
        include_delivery=False,
        is_owner=is_owner,
        with_driver=False
    )
    
    if target_user.wallet_balance < required_balance:
        formatted_required = f"{required_balance:,}".replace(",", " ")
        formatted_balance = f"{int(target_user.wallet_balance):,}".replace(",", " ")
        raise HTTPException(
            status_code=402, 
            detail=f"Недостаточно средств на балансе клиента. Требуется минимум: {formatted_required} ₸, доступно: {formatted_balance} ₸"
        )
    
    new_rental = RentalHistory(
        user_id=target_user_uuid,
        car_id=car_uuid,
        rental_type=rental_type_enum,
        duration=parsed_duration,
        rental_status=RentalStatus.IN_USE,
        reservation_time=get_local_time(),
        start_time=get_local_time(),
        start_latitude=car.latitude,
        start_longitude=car.longitude,
        open_fee=open_fee_value,
        base_price=base_price,
        delivery_fee=0,
        waiting_fee=0,
        overtime_fee=0,
        distance_fee=0,
        total_price=base_price + open_fee_value,
        already_payed=0
    )
    db.add(new_rental)
    db.flush()
    
    photos_before = []
    
    if filtered_selfie:
        selfie_url = await save_file(filtered_selfie, new_rental.id, f"uploads/rents/{new_rental.id}/before/selfie/")
        photos_before.append(selfie_url)
    
    for photo in filtered_car_photos:
        car_url = await save_file(photo, new_rental.id, f"uploads/rents/{new_rental.id}/before/car/")
        photos_before.append(car_url)
    
    for photo in filtered_interior_photos:
        interior_url = await save_file(photo, new_rental.id, f"uploads/rents/{new_rental.id}/before/interior/")
        photos_before.append(interior_url)
    
    new_rental.photos_before = photos_before
    new_rental.fuel_before = car.fuel_level
    new_rental.mileage_before = car.mileage
    
    # Списываем деньги с кошелька пользователя
    total_charged = 0
    balance_before = float(target_user.wallet_balance or 0)
    
    if not is_owner:
        # Для владельца ничего не списываем
        if rental_type_enum in [RentalType.HOURS, RentalType.DAYS]:
            # 1. Базовая стоимость аренды
            if base_price > 0:
                record_wallet_transaction(
                    db,
                    user=target_user,
                    amount=-base_price,
                    ttype=WalletTransactionType.RENT_BASE_CHARGE,
                    description=f"Оплата аренды: {parsed_duration} {'час(ов)' if rental_type_enum == RentalType.HOURS else 'день(дней)'}",
                    related_rental=new_rental,
                    balance_before_override=balance_before
                )
                target_user.wallet_balance -= base_price
                total_charged += base_price
                balance_before = float(target_user.wallet_balance)
            
            # 2. Открытие дверей (только для часового тарифа)
            if open_fee_value > 0:
                record_wallet_transaction(
                    db,
                    user=target_user,
                    amount=-open_fee_value,
                    ttype=WalletTransactionType.RENT_BASE_CHARGE,
                    description="Оплата открытия дверей",
                    related_rental=new_rental,
                    balance_before_override=balance_before
                )
                target_user.wallet_balance -= open_fee_value
                total_charged += open_fee_value
        elif rental_type_enum == RentalType.MINUTES:
            # Для поминутного тарифа списываем только open_fee
            if open_fee_value > 0:
                record_wallet_transaction(
                    db,
                    user=target_user,
                    amount=-open_fee_value,
                    ttype=WalletTransactionType.RENT_BASE_CHARGE,
                    description="Оплата открытия дверей",
                    related_rental=new_rental,
                    balance_before_override=balance_before
                )
                target_user.wallet_balance -= open_fee_value
                total_charged += open_fee_value
        
        # Обновляем already_payed
        if target_user.wallet_balance >= 0:
            new_rental.already_payed = total_charged
        else:
            new_rental.already_payed = 0
    else:
        # Для владельца все бесплатно
        new_rental.base_price = 0
        new_rental.open_fee = 0
        new_rental.total_price = 0
        new_rental.already_payed = 0
    
    car.status = CarStatus.IN_USE
    car.current_renter_id = target_user_uuid
    
    target_user.last_activity_at = get_local_time()
    
    db.commit()
    
    log_action(
        db,
        actor_id=current_user.id,
        action="admin_start_rental",
        entity_type="rental",
        entity_id=new_rental.id,
        details={
            "user_id": target_user_uuid,
            "car_id": car_uuid,
            "open_fee": open_fee_value,
            "base_price": base_price,
            "rental_type": new_rental.rental_type.value
        }
    )
    db.commit()
    db.refresh(new_rental)
    
    # Отправляем уведомление в Telegram на оба бота о начале аренды
    try:
        name_parts = []
        if target_user.first_name:
            name_parts.append(target_user.first_name)
        if target_user.middle_name:
            name_parts.append(target_user.middle_name)
        if target_user.last_name:
            name_parts.append(target_user.last_name)
        full_name = " ".join(name_parts) if name_parts else "Не указано"
        
        notification_text = (
            f"Начало аренды\n\n"
            f"Клиент: {full_name}\n"
            f"Телефон: {target_user.phone_number or 'Не указан'}\n"
            f"Машина: {car.name}\n"
            f"Гос. номер: {car.plate_number or 'Не указан'}\n"
            f"Тип аренды: {rental_type_enum.value}\n"
            f"ID аренды: {uuid_to_sid(new_rental.id)}\n"
            f"Запущено администратором: {current_user.first_name or 'Admin'}"
        )
        
        async def _send_telegram_notification(text: str, chat_id: int, bot_token: str):
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": chat_id, "text": text}
                    )
            except Exception as e:
                print(f"Ошибка отправки Telegram уведомления в {chat_id}: {e}")
        
        # Список чатов для уведомлений
        chat_ids = [965048905, 5941825713, 860991388, 1594112444, 808277096, 7656716395, 964255811, 8522837235, 797693964]
        
        if TELEGRAM_BOT_TOKEN:
            for chat_id in chat_ids:
                asyncio.create_task(_send_telegram_notification(notification_text, chat_id, TELEGRAM_BOT_TOKEN))
        
        if TELEGRAM_BOT_TOKEN_2:
            for chat_id in chat_ids:
                asyncio.create_task(_send_telegram_notification(notification_text, chat_id, TELEGRAM_BOT_TOKEN_2))
                
    except Exception as e:
        print(f"Не удалось отправить Telegram уведомление о начале аренды: {e}")
    
    asyncio.create_task(notify_user_status_update(str(target_user.id)))
    
    return {
        "success": True,
        "rental_id": uuid_to_sid(new_rental.id),
        "user_id": uuid_to_sid(new_rental.user_id),
        "car_id": uuid_to_sid(new_rental.car_id),
        "rental_type": new_rental.rental_type.value,
        "rental_status": new_rental.rental_status.value,
        "start_time": new_rental.start_time.isoformat(),
        "open_fee": open_fee_value,
        "base_price": base_price,
        "total_charged": total_charged,
        "photos_count": len(photos_before),
        "new_balance": float(target_user.wallet_balance),
        "started_by_admin": uuid_to_sid(current_user.id)
    }


@users_router.post("/trips/end", summary="Завершить аренду за клиента (Admin)")
async def admin_end_rental(
    request: Request,
    car_id: str = Form(..., description="ID машины"),
    user_id: str = Form(..., description="ID пользователя"),
    selfie: UploadFile = File(default=None, description="Селфи пользователя после аренды"),
    car_photos: List[UploadFile] = File(default=[], description="Фото кузова после (1-10)"),
    interior_photos: List[UploadFile] = File(default=[], description="Фото салона после (1-10)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Эндпоинт для админа для завершения аренды за клиента.
    
    - Находит активную аренду по car_id и user_id
    - Сохраняет фотографии после аренды (селфи, кузов, салон)
    - Рассчитывает и списывает итоговую стоимость
    - Завершает аренду со статусом COMPLETED
    - Освобождает машину (статус FREE)
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    form = await request.form()
    
    def get_files_from_form(field_name: str) -> List:
        files = []
        for key, value in form.multi_items():
            if key == field_name and hasattr(value, 'filename') and hasattr(value, 'read'):
                if value.filename:
                    files.append(value)
        return files
    
    def get_single_file_from_form(field_name: str):
        for key, value in form.multi_items():
            if key == field_name and hasattr(value, 'filename') and hasattr(value, 'read'):
                if value.filename:
                    return value
        return None
    
    filtered_selfie = get_single_file_from_form("selfie")
    filtered_car_photos = get_files_from_form("car_photos")
    filtered_interior_photos = get_files_from_form("interior_photos")
    
    target_user_uuid = safe_sid_to_uuid(user_id)
    target_user = db.query(User).filter(User.id == target_user_uuid).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    car_uuid = safe_sid_to_uuid(car_id)
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    active_rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == target_user_uuid,
        RentalHistory.car_id == car_uuid,
        RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
    ).first()
    
    if not active_rental:
        raise HTTPException(status_code=404, detail="Активная аренда не найдена для данного пользователя и машины")
    
    photos_after = list(active_rental.photos_after or [])
    
    if filtered_selfie:
        selfie_url = await save_file(filtered_selfie, active_rental.id, f"uploads/rents/{active_rental.id}/after/selfie/")
        photos_after.append(selfie_url)
    
    for photo in filtered_car_photos:
        car_url = await save_file(photo, active_rental.id, f"uploads/rents/{active_rental.id}/after/car/")
        photos_after.append(car_url)
    
    for photo in filtered_interior_photos:
        interior_url = await save_file(photo, active_rental.id, f"uploads/rents/{active_rental.id}/after/interior/")
        photos_after.append(interior_url)
    
    active_rental.photos_after = photos_after
    
    now = get_local_time()
    start_time = active_rental.start_time or active_rental.reservation_time
    
    if start_time:
        duration_minutes = int((now - start_time).total_seconds() / 60)
    else:
        duration_minutes = 0
    
    price_per_minute = car.price_per_minute or 0
    price_per_hour = car.price_per_hour or 0
    price_per_day = car.price_per_day or 0
    
    rental_cost = 0
    if active_rental.rental_type == RentalType.MINUTES:
        rental_cost = duration_minutes * price_per_minute
    elif active_rental.rental_type == RentalType.HOURS:
        hours = max(1, (duration_minutes + 59) // 60)
        rental_cost = hours * price_per_hour
    elif active_rental.rental_type == RentalType.DAYS:
        days = max(1, (duration_minutes + 1439) // 1440)
        rental_cost = days * price_per_day
    
    already_payed = float(active_rental.already_payed or 0)
    open_fee = float(active_rental.open_fee or 0)
    
    total_to_charge = max(0, rental_cost - already_payed + open_fee)
    
    balance_before = float(target_user.wallet_balance or 0)
    if total_to_charge > 0 and balance_before >= total_to_charge:
        target_user.wallet_balance = balance_before - total_to_charge
        
        record_wallet_transaction(
            db,
            user=target_user,
            amount=-total_to_charge,
            ttype=WalletTransactionType.RENT_BASE_CHARGE,
            description=f"Оплата аренды",
            related_rental=active_rental,
            balance_before_override=balance_before
        )
    
    active_rental.rental_status = RentalStatus.COMPLETED
    active_rental.end_time = now
    active_rental.end_latitude = car.latitude
    active_rental.end_longitude = car.longitude
    active_rental.total_price = rental_cost + open_fee
    active_rental.already_payed = already_payed + total_to_charge
    
    car.status = CarStatus.PENDING  
    car.current_renter_id = None
    
    target_user.last_activity_at = now
    
    db.commit()

    # ========== ВЕРИФИКАЦИЯ И ИСПРАВЛЕНИЕ БАЛАНСА ==========
    # Пересчитываем все транзакции, синхронизируем поля аренды и исправляем баланс
    is_owner = car.owner_id == target_user.id
    if not is_owner:
        try:
            import logging
            logger = logging.getLogger(__name__)
            
            verification_result = verify_and_fix_rental_balance(
                user=target_user,
                rental=active_rental,
                car=car,
                db=db
            )
            
            if verification_result.get("corrected"):
                logger.info(
                    f"🔧 Admin end rental - verification applied for user {target_user.id}: "
                    f"balance_before_rental={verification_result.get('balance_before_rental')}, "
                    f"old_balance={verification_result.get('old_balance')}, "
                    f"new_balance={verification_result.get('new_balance')}, "
                    f"rental_fields_updated={verification_result.get('rental_fields_updated')}"
                )
            elif verification_result.get("success"):
                logger.info(
                    f"✅ Admin end rental - balance verified for user {target_user.id}: "
                    f"balance_before_rental={verification_result.get('balance_before_rental')}, "
                    f"tx_sums={verification_result.get('tx_sums')}"
                )
            else:
                logger.warning(
                    f"⚠️ Admin end rental - balance verification failed for user {target_user.id}: "
                    f"{verification_result.get('error')}"
                )
            
            db.commit()
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error during balance verification in admin_end_rental: {e}", exc_info=True)
    # ========== КОНЕЦ ВЕРИФИКАЦИИ БАЛАНСА ==========

    log_action(
        db,
        actor_id=current_user.id,
        action="admin_end_rental",
        entity_type="rental",
        entity_id=active_rental.id,
        details={
            "total_price": active_rental.total_price,
            "already_payed": active_rental.already_payed,
            "end_latitude": car.latitude,
            "end_longitude": car.longitude
        }
    )
    db.commit()
    db.refresh(active_rental)
    
    # Отправляем WebSocket уведомления
    asyncio.create_task(notify_user_status_update(str(target_user.id)))
    if car.owner_id:
        asyncio.create_task(notify_user_status_update(str(car.owner_id)))
    
    # Отправляем уведомление всем механикам о новой машине для проверки
    try:
        await send_localized_notification_to_all_mechanics(
            db,
            "new_car_for_inspection",
            "new_car_for_inspection",
            car_name=car.name,
            plate_number=car.plate_number
        )
    except Exception as e:
        print(f"Error sending notification to mechanics: {e}")
    
    # Обновляем данные из БД после верификации
    db.refresh(active_rental)
    db.refresh(target_user)
    
    return {
        "success": True,
        "rental_id": uuid_to_sid(active_rental.id),
        "user_id": uuid_to_sid(active_rental.user_id),
        "car_id": uuid_to_sid(active_rental.car_id),
        "rental_status": active_rental.rental_status.value,
        "start_time": start_time.isoformat() if start_time else None,
        "end_time": active_rental.end_time.isoformat(),
        "duration_minutes": duration_minutes,
        # Берём значения из пересчитанной аренды (после verify_and_fix_rental_balance)
        "base_price": active_rental.base_price or 0,
        "open_fee": active_rental.open_fee or 0,
        "delivery_fee": active_rental.delivery_fee or 0,
        "waiting_fee": active_rental.waiting_fee or 0,
        "overtime_fee": active_rental.overtime_fee or 0,
        "total_price": active_rental.total_price or 0,
        "already_payed": active_rental.already_payed or 0,
        "photos_after_count": len(photos_after),
        "new_balance": float(target_user.wallet_balance),
        "ended_by_admin": uuid_to_sid(current_user.id)
    }


@users_router.get("/contracts/{signature_id}/download")
async def download_user_contract(
    signature_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Скачивание подписанного договора с данными пользователя.
    Генерирует HTML договор с заполненными данными пользователя и аренды.
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
    
    # Маппинг типов контрактов на файлы шаблонов
    CONTRACT_FILES = {
        "rental_main_contract": "rental_main_contract.html",
        "appendix_7_1": "acceptance_certificate.html",
        "appendix_7_2": "return_certificate.html",
        "main_contract": "main_contract.html",
        "user_agreement": "user_agreement.html",
        "consent_to_data_processing": "consent_to_the_processing_of_personaldata.html",
        "main_contract_for_guarantee": "main_contract_for_guarantee.html",
        "guarantor_contract": "main_contract_for_guarantee.html",
        "guarantor_main_contract": "main_contract_for_guarantee.html",
    }
    
    contract_type_value = contract_file.contract_type.value if contract_file.contract_type else None
    template_filename = CONTRACT_FILES.get(contract_type_value)
    
    if not template_filename:
        raise HTTPException(status_code=404, detail=f"Шаблон для типа договора '{contract_type_value}' не найден")
    
    template_path = os.path.join("uploads/docs", template_filename)
    
    if not os.path.exists(template_path):
        raise HTTPException(status_code=404, detail="Файл шаблона договора не найден")
    
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()
    
    # Получаем данные пользователя
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.phone_number
    login = user.phone_number
    client_id = str(user.id)
    digital_signature = signature.digital_signature or user.digital_signature
    
    # Получаем данные аренды и авто если есть
    car_name = None
    plate_number = None
    car_uuid = None
    car_year = None
    body_type = None
    vin = None
    color = None
    rental_id_str = None
    
    if signature.rental_id:
        rental = db.query(RentalHistory).filter(RentalHistory.id == signature.rental_id).first()
        if rental:
            rental_id_str = str(rental.id)
            car = db.query(Car).filter(Car.id == rental.car_id).first()
            if car:
                car_name = car.name
                plate_number = car.plate_number
                car_uuid = str(car.id)
                car_year = str(car.year) if car.year else None
                body_type = car.body_type.value if car.body_type else None
                vin = car.vin
                color = car.color
    
    # Функция форматирования
    def format_data(value, fallback="не указано"):
        if value is None or value == "":
            return fallback
        return str(value)
    
    def translate_body_type(bt):
        if not bt:
            return "не указан"
        body_type_map = {
            "SEDAN": "Седан", "SUV": "Внедорожник", "CROSSOVER": "Кроссовер",
            "COUPE": "Купе", "HATCHBACK": "Хэтчбек", "CONVERTIBLE": "Кабриолет",
            "WAGON": "Универсал", "MINIBUS": "Микроавтобус", "ELECTRIC": "Электромобиль",
        }
        return body_type_map.get(bt.upper(), bt)
    
    from datetime import datetime
    current_date = datetime.now().strftime("%d.%m.%Y")
    
    # Заменяем плейсхолдеры
    html = html.replace("${full_name}", format_data(full_name, "ФИО не указано"))
    html = html.replace("${login}", format_data(login, "логин не указан"))
    html = html.replace("${client_id}", format_data(client_id, "ID не указан"))
    html = html.replace("${client_uuid}", format_data(client_id, "ID не указан"))
    html = html.replace("${digital_signature}", format_data(digital_signature, "подпись не указана"))
    html = html.replace("${rental_id}", format_data(rental_id_str, "ID аренды не указан"))
    html = html.replace("${rent_uuid}", format_data(rental_id_str, "ID аренды не указан"))
    html = html.replace("${rent_id}", format_data(rental_id_str, "ID аренды не указан"))
    html = html.replace("${car_name}", format_data(car_name, "не указано"))
    html = html.replace("${plate_number}", format_data(plate_number, "не указан"))
    html = html.replace("${car_uuid}", format_data(car_uuid, "не указан"))
    html = html.replace("${car_year}", format_data(car_year, "выпуска: не указан"))
    html = html.replace("${body_type}", translate_body_type(body_type))
    html = html.replace("${vin}", format_data(vin, "VIN не указан"))
    html = html.replace("${color}", format_data(color, "Цвет: не указан"))
    html = html.replace("${date}", current_date)
    html = html.replace("{date}", current_date)
    
    # Дополнительные плейсхолдеры из шаблонов
    html = html.replace("{___car_name_____}", format_data(car_name, "не указано"))
    html = html.replace("{____car_plate_number______}", format_data(plate_number, "не указан"))
    html = html.replace("{_______car_id________}", format_data(car_uuid, "не указан"))
    html = html.replace("{_____car_year___________}", format_data(car_year, "выпуска: не указан"))
    html = html.replace("{______car_body_type_____________}", translate_body_type(body_type))
    html = html.replace("{______car_vin_________}", format_data(vin, "VIN не указан"))
    html = html.replace("{________car_color_________}", format_data(color, "Цвет: не указан"))
    
    # Возвращаем HTML как файл
    filename = f"{contract_type_value or 'contract'}_{signature_id}.html"
    
    return {
        "success": True,
        "signature_id": uuid_to_sid(signature.id),
        "contract_type": contract_type_value,
        "file_name": filename,
        "html_content": html,
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


@users_router.get("/contracts/generate")
async def generate_contract_by_type(
    contract_type: str = Query(..., description="Тип договора: rental_main_contract, appendix_7_1, appendix_7_2, main_contract, user_agreement, consent_to_data_processing, main_contract_for_guarantee"),
    user_id: Optional[str] = Query(None, description="ID пользователя (для обычных договоров)"),
    rental_id: Optional[str] = Query(None, description="ID аренды (для rental_main_contract, appendix_7_1, appendix_7_2)"),
    guarantor_relationship_id: Optional[str] = Query(None, description="ID связи гаранта (для main_contract_for_guarantee)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Генерация договора по типу с данными.
    
    Для rental_main_contract, appendix_7_1, appendix_7_2: передать user_id и rental_id
    Для main_contract, user_agreement, consent_to_data_processing: передать user_id
    Для main_contract_for_guarantee: передать guarantor_relationship_id
    
    Возвращает HTML файл для скачивания.
    """
    from fastapi.responses import Response
    from app.models.guarantor_model import Guarantor
    
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    CONTRACT_FILES = {
        "rental_main_contract": "rental_main_contract.html",
        "appendix_7_1": "acceptance_certificate.html",
        "appendix_7_2": "return_certificate.html",
        "main_contract": "main_contract.html",
        "user_agreement": "user_agreement.html",
        "consent_to_data_processing": "consent_to_the_processing_of_personaldata.html",
        "main_contract_for_guarantee": "main_contract_for_guarantee.html",
    }
    
    # Договоры, требующие rental_id
    RENTAL_CONTRACTS = ["rental_main_contract", "appendix_7_1", "appendix_7_2"]
    # Договоры гаранта
    GUARANTOR_CONTRACTS = ["main_contract_for_guarantee"]
    
    template_filename = CONTRACT_FILES.get(contract_type)
    if not template_filename:
        raise HTTPException(
            status_code=400, 
            detail=f"Неизвестный тип договора: {contract_type}. Доступные типы: {', '.join(CONTRACT_FILES.keys())}"
        )
    
    template_path = os.path.join("uploads/docs", template_filename)
    
    if not os.path.exists(template_path):
        raise HTTPException(status_code=404, detail="Файл шаблона договора не найден")
    
    def format_data(value, fallback="не указано"):
        if value is None or value == "":
            return fallback
        return str(value)
    
    def translate_body_type(bt):
        if not bt:
            return "не указан"
        body_type_map = {
            "SEDAN": "Седан", "SUV": "Внедорожник", "CROSSOVER": "Кроссовер",
            "COUPE": "Купе", "HATCHBACK": "Хэтчбек", "CONVERTIBLE": "Кабриолет",
            "WAGON": "Универсал", "MINIBUS": "Микроавтобус", "ELECTRIC": "Электромобиль",
        }
        return body_type_map.get(bt.upper(), bt)
    
    from datetime import datetime as dt_module
    current_date = dt_module.now().strftime("%d.%m.%Y")
    
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()
    
    full_name = None
    login = None
    client_id = None
    digital_signature = None
    car_name = None
    plate_number = None
    car_uuid = None
    car_year = None
    body_type = None
    vin = None
    color = None
    rental_id_str = None
    
    guarantor_fullname = None
    guarantor_iin = None
    guarantor_phone = None
    guarantor_email = None
    guarantor_id_str = None
    client_fullname = None
    client_iin = None
    client_phone = None
    client_email = None
    guarantee_id = None
    
    if contract_type in GUARANTOR_CONTRACTS:
        if not guarantor_relationship_id:
            raise HTTPException(status_code=400, detail="Для договора гаранта необходимо передать guarantor_relationship_id")
        
        guarantor_rel_uuid = safe_sid_to_uuid(guarantor_relationship_id)
        guarantor_rel = db.query(Guarantor).filter(Guarantor.id == guarantor_rel_uuid).first()
        if not guarantor_rel:
            raise HTTPException(status_code=404, detail="Связь гаранта не найдена")
        
        guarantor_user = db.query(User).filter(User.id == guarantor_rel.guarantor_id).first()
        if guarantor_user:
            guarantor_fullname = f"{guarantor_user.first_name or ''} {guarantor_user.last_name or ''}".strip()
            guarantor_iin = guarantor_user.iin
            guarantor_phone = guarantor_user.phone_number
            guarantor_email = guarantor_user.email
            guarantor_id_str = str(guarantor_user.id)
            digital_signature = guarantor_user.digital_signature
            full_name = guarantor_fullname
            login = guarantor_phone
        
        client_user = db.query(User).filter(User.id == guarantor_rel.client_id).first()
        if client_user:
            client_fullname = f"{client_user.first_name or ''} {client_user.last_name or ''}".strip()
            client_iin = client_user.iin
            client_phone = client_user.phone_number
            client_email = client_user.email
            client_id = str(client_user.id)
        
        guarantee_id = str(guarantor_rel.id)
        
    else:
        if not user_id:
            raise HTTPException(status_code=400, detail="Для данного типа договора необходимо передать user_id")
        
        user_uuid = safe_sid_to_uuid(user_id)
        user = db.query(User).filter(User.id == user_uuid).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.phone_number
        login = user.phone_number
        client_id = str(user.id)
        digital_signature = user.digital_signature
        
        if contract_type in RENTAL_CONTRACTS:
            if not rental_id:
                raise HTTPException(status_code=400, detail="Для договора аренды необходимо передать rental_id")
            
            rental_uuid = safe_sid_to_uuid(rental_id)
            rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
            if not rental:
                raise HTTPException(status_code=404, detail="Аренда не найдена")
            
            rental_id_str = str(rental.id)
            car = db.query(Car).filter(Car.id == rental.car_id).first()
            if car:
                car_name = car.name
                plate_number = car.plate_number
                car_uuid = str(car.id)
                car_year = str(car.year) if car.year else None
                body_type = car.body_type.value if car.body_type else None
                vin = car.vin
                color = car.color
    
    html = html.replace("${full_name}", format_data(full_name, "ФИО не указано"))
    html = html.replace("${login}", format_data(login, "логин не указан"))
    html = html.replace("${client_id}", format_data(client_id, "ID не указан"))
    html = html.replace("${client_uuid}", format_data(client_id, "ID не указан"))
    html = html.replace("${digital_signature}", format_data(digital_signature, "подпись не указана"))
    html = html.replace("${rental_id}", format_data(rental_id_str, "ID аренды не указан"))
    html = html.replace("${rent_uuid}", format_data(rental_id_str, "ID аренды не указан"))
    html = html.replace("${rent_id}", format_data(rental_id_str, "ID аренды не указан"))
    html = html.replace("${car_name}", format_data(car_name, "не указано"))
    html = html.replace("${plate_number}", format_data(plate_number, "не указан"))
    html = html.replace("${car_uuid}", format_data(car_uuid, "не указан"))
    html = html.replace("${car_year}", format_data(car_year, "выпуска: не указан"))
    html = html.replace("${body_type}", translate_body_type(body_type))
    html = html.replace("${vin}", format_data(vin, "VIN не указан"))
    html = html.replace("${color}", format_data(color, "Цвет: не указан"))
    html = html.replace("${date}", current_date)
    html = html.replace("{date}", current_date)
    
    html = html.replace("{___car_name_____}", format_data(car_name, "не указано"))
    html = html.replace("{____car_plate_number______}", format_data(plate_number, "не указан"))
    html = html.replace("{_______car_id________}", format_data(car_uuid, "не указан"))
    html = html.replace("{_____car_year___________}", format_data(car_year, "выпуска: не указан"))
    html = html.replace("{______car_body_type_____________}", translate_body_type(body_type))
    html = html.replace("{______car_vin_________}", format_data(vin, "VIN не указан"))
    html = html.replace("{________car_color_________}", format_data(color, "Цвет: не указан"))
    
    html = html.replace("{_____guarantor_fullname_______}", format_data(guarantor_fullname))
    html = html.replace("{____guarantor_iin________}", format_data(guarantor_iin))
    html = html.replace("{_____guarantor_phone_______}", format_data(guarantor_phone))
    html = html.replace("{____guarantor_phone____}", format_data(guarantor_phone))
    html = html.replace("{__ guarantor_email__}", format_data(guarantor_email))
    html = html.replace("{___guarantor_id____}", format_data(guarantor_id_str))
    html = html.replace("${guarantor_id}", format_data(guarantor_id_str))
    html = html.replace("${guarantor_phone}", format_data(guarantor_phone))
    
    html = html.replace("{_____client_fullname_______}", format_data(client_fullname))
    html = html.replace("{___client_iin____}", format_data(client_iin))
    html = html.replace("{___client_phone______}", format_data(client_phone))
    html = html.replace("{____client_email______}", format_data(client_email))
    html = html.replace("{__client_id___}", format_data(client_id))
    html = html.replace("${guarantee_id}", format_data(guarantee_id))
    html = html.replace("${renter}", format_data(client_fullname))
    
    filename = f"{contract_type}.html"
    
    return Response(
        content=html,
        media_type="text/html",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Cache-Control": "no-cache, no-store, must-revalidate"
        }
    )

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

    log_action(
        db,
        actor_id=current_user.id,
        action="balance_topup",
        entity_type="user",
        entity_id=user.id,
        details={
            "amount": payload.amount,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "description": payload.description
        }
    )
    
    db.commit()
    db.refresh(transaction)
    
    notification_message = f"Ваш баланс пополнен на {payload.amount:.0f} ₸. Новый баланс: {balance_after:.0f} ₸"
    if payload.description:
        notification_message += f"\nПричина: {payload.description}"
    
    try:
        await send_push_to_user_by_id(
            db_session=db,
            user_id=user_uuid,
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


@users_router.post("/{user_id}/balance/deduct")
async def deduct_user_balance(
    user_id: str,
    payload: BalanceTopUpSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Списание средств со счёта пользователя администратором.
    
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
    
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма списания должна быть положительной")
    
    balance_before = float(user.wallet_balance or 0)
    balance_after = balance_before - payload.amount
    
    transaction = WalletTransaction(
        user_id=user_uuid,
        amount=-payload.amount,
        transaction_type=WalletTransactionType.ADMIN_DEDUCTION,
        description=payload.description or f"Списание средств администратором ({current_user.phone_number})",
        balance_before=balance_before,
        balance_after=balance_after
    )
    db.add(transaction)
    
    user.wallet_balance = balance_after

    log_action(
        db,
        actor_id=current_user.id,
        action="balance_deduct",
        entity_type="user",
        entity_id=user.id,
        details={
            "amount": payload.amount,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "description": payload.description
        }
    )
    
    db.commit()
    db.refresh(transaction)
    
    notification_message = f"С вашего баланса списано {payload.amount:.0f} ₸. Новый баланс: {balance_after:.0f} ₸"
    if payload.description:
        notification_message += f"\nПричина: {payload.description}"
    
    try:
        await send_push_to_user_by_id(
            db_session=db,
            user_id=user_uuid,
            title="Списание средств",
            body=notification_message
        )
    except Exception as e:
        pass
    
    notification = Notification(
        user_id=user_uuid,
        title="Списание средств",
        body=notification_message
    )
    db.add(notification)
    db.commit()
    
    return {
        "success": True,
        "transaction_id": uuid_to_sid(transaction.id),
        "user_id": uuid_to_sid(user_uuid),
        "amount": -payload.amount,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "description": payload.description
    }


@users_router.put("/{user_id}/balance")
async def set_user_balance(
    user_id: str,
    new_balance: float = Form(..., description="Новый баланс кошелька"),
    description: Optional[str] = Form(None, description="Причина изменения"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Установка нового баланса кошелька пользователя (только для ADMIN).
    
    Создаёт транзакцию корректировки с разницей между старым и новым балансом.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав. Только ADMIN может изменять баланс.")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    old_balance = float(user.wallet_balance or 0)
    diff = new_balance - old_balance
    
    if diff != 0:
        transaction = WalletTransaction(
            user_id=user_uuid,
            amount=diff,
            transaction_type=WalletTransactionType.MANUAL_ADJUSTMENT,
            description=description or f"Пересчёт",
            balance_before=old_balance,
            balance_after=new_balance
        )
        db.add(transaction)
    
    user.wallet_balance = new_balance

    log_action(
        db,
        actor_id=current_user.id,
        action="balance_set",
        entity_type="user",
        entity_id=user.id,
        details={
            "old_balance": old_balance,
            "new_balance": new_balance,
            "difference": diff,
            "description": description
        }
    )

    db.commit()
    
    return {
        "success": True,
        "user_id": uuid_to_sid(user_uuid),
        "old_balance": old_balance,
        "new_balance": new_balance,
        "difference": diff,
        "description": description
    }


@users_router.post("/{user_id}/balance/recalculate")
async def recalculate_user_balance(
    user_id: str,
    initial_balance: Optional[float] = Form(0.0, description="Начальный баланс перед первой транзакцией (по умолчанию 0)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Пересчёт балансов всех транзакций пользователя.
    
    Пересчитывает balance_before и balance_after для всех транзакций пользователя,
    начиная с первой транзакции. Устанавливает правильную последовательность балансов.
    После пересчёта обновляет финальный баланс пользователя.
    
    Алгоритм:
    1. Получает все транзакции пользователя, отсортированные по created_at
    2. Начинает с initial_balance (по умолчанию 0)
    3. Для каждой транзакции:
       - balance_before = баланс после предыдущей транзакции (или initial_balance для первой)
       - balance_after = balance_before + amount
    4. Обновляет все транзакции
    5. Обновляет wallet_balance пользователя на balance_after последней транзакции
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав. Только ADMIN может пересчитывать балансы.")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Получаем все транзакции пользователя, отсортированные по времени создания
    all_transactions = (
        db.query(WalletTransaction)
        .filter(WalletTransaction.user_id == user_uuid)
        .order_by(WalletTransaction.created_at.asc())
        .all()
    )
    
    if not all_transactions:
        raise HTTPException(status_code=400, detail="У пользователя нет транзакций для пересчёта")
    
    # Сохраняем старый баланс для логирования
    old_balance = float(user.wallet_balance or 0)
    
    # Начинаем пересчёт с начального баланса
    running_balance = float(initial_balance or 0)
    
    # Пересчитываем каждую транзакцию
    updated_count = 0
    for tx in all_transactions:
        tx.balance_before = running_balance
        tx.balance_after = running_balance + float(tx.amount)
        running_balance = tx.balance_after
        updated_count += 1
    
    # Обновляем финальный баланс пользователя
    new_balance = running_balance
    user.wallet_balance = new_balance
    
    # Логируем действие
    log_action(
        db,
        actor_id=current_user.id,
        action="balance_recalculate",
        entity_type="user",
        entity_id=user.id,
        details={
            "user_id": user_id,
            "initial_balance": initial_balance,
            "old_balance": old_balance,
            "new_balance": new_balance,
            "transactions_count": updated_count,
            "balance_difference": new_balance - old_balance
        }
    )
    
    db.commit()
    
    return {
        "success": True,
        "message": "Балансы транзакций успешно пересчитаны",
        "user_id": uuid_to_sid(user_uuid),
        "initial_balance": initial_balance,
        "old_balance": old_balance,
        "new_balance": new_balance,
        "balance_difference": new_balance - old_balance,
        "transactions_updated": updated_count
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
    
    log_action(
        db,
        actor_id=current_user.id,
        action="update_user_auto_class",
        entity_type="user",
        entity_id=user.id,
        details={"old_classes": list(old_classes), "new_classes": payload.auto_class}
    )

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
    
    log_action(
        db,
        actor_id=current_user.id,
        action="update_zone_permission",
        entity_type="user",
        entity_id=user.id,
        details={"can_exit_zone": can_exit_zone}
    )

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
    
    log_action(
        db,
        actor_id=current_user.id,
        action="update_user_comment",
        entity_type="user",
        entity_id=user.id,
        details={"comment": comment_data.admin_comment}
    )

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
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
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

    log_action(
        db,
        actor_id=current_user.id,
        action="edit_user_profile",
        entity_type="user",
        entity_id=user.id,
        details={"edit_data": edit_data.dict(exclude_unset=True)}
    )

    db.commit()
    
    asyncio.create_task(notify_user_status_update(str(user.id)))
    
    return {"message": "Пользователь обновлен"}


@users_router.patch("/{user_id}/edit-full", summary="Полное редактирование пользователя (Admin)")
async def edit_user_full(
    user_id: str,
    first_name: Optional[str] = Form(None, description="Имя"),
    last_name: Optional[str] = Form(None, description="Фамилия"),
    middle_name: Optional[str] = Form(None, description="Отчество"),
    phone_number: Optional[str] = Form(None, description="Номер телефона"),
    email: Optional[str] = Form(None, description="Email"),
    iin: Optional[str] = Form(None, description="ИИН (12 цифр)"),
    passport_number: Optional[str] = Form(None, description="Номер паспорта"),
    birth_date: Optional[str] = Form(None, description="Дата рождения (YYYY-MM-DD)"),
    drivers_license_expiry: Optional[str] = Form(None, description="Срок действия прав (YYYY-MM-DD)"),
    id_card_expiry: Optional[str] = Form(None, description="Срок действия ID карты (YYYY-MM-DD)"),
    locale: Optional[str] = Form(None, description="Язык (ru/en/kz/zh)"),
    admin_comment: Optional[str] = Form(None, description="Комментарий администратора"),
    role: Optional[str] = Form(None, description="Роль пользователя"),
    auto_class: Optional[str] = Form(None, description="Классы авто через запятую (A,B,C)"),
    is_active: Optional[bool] = Form(None, description="Активен"),
    is_blocked: Optional[bool] = Form(None, description="Заблокирован"),
    is_verified_email: Optional[bool] = Form(None, description="Email подтвержден"),
    is_citizen_kz: Optional[bool] = Form(None, description="Гражданин РК"),
    documents_verified: Optional[bool] = Form(None, description="Документы проверены"),
    is_consent_to_data_processing: Optional[bool] = Form(None, description="Согласие на обработку данных"),
    is_contract_read: Optional[bool] = Form(None, description="Договор прочитан"),
    is_user_agreement: Optional[bool] = Form(None, description="Пользовательское соглашение"),
    can_exit_zone: Optional[bool] = Form(None, description="Разрешение на выезд за зону"),
    wallet_balance: Optional[float] = Form(None, description="Баланс кошелька"),
    rating: Optional[float] = Form(None, description="Рейтинг"),
    selfie: Optional[UploadFile] = File(None, description="Селфи"),
    selfie_with_license: Optional[UploadFile] = File(None, description="Селфи с правами"),
    drivers_license: Optional[UploadFile] = File(None, description="Водительские права"),
    id_card_front: Optional[UploadFile] = File(None, description="Лицевая сторона ID карты"),
    id_card_back: Optional[UploadFile] = File(None, description="Обратная сторона ID карты"),
    psych_neurology_certificate: Optional[UploadFile] = File(None, description="Справка из ПНД"),
    narcology_certificate: Optional[UploadFile] = File(None, description="Справка из НД"),
    pension_contributions_certificate: Optional[UploadFile] = File(None, description="Справка о пенсионных отчислениях"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Полное редактирование всех данных пользователя.
    Поддерживает загрузку файлов (фото, справки).
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Только для администраторов")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    changes = {}
    
    if first_name is not None:
        user.first_name = first_name
        changes["first_name"] = first_name
    if last_name is not None:
        user.last_name = last_name
        changes["last_name"] = last_name
    if middle_name is not None:
        user.middle_name = middle_name
        changes["middle_name"] = middle_name
    if phone_number is not None:
        user.phone_number = phone_number
        changes["phone_number"] = phone_number
    if email is not None:
        user.email = email.lower().strip() if email else None
        changes["email"] = email
    if iin is not None:
        user.iin = iin
        changes["iin"] = iin
    if passport_number is not None:
        user.passport_number = passport_number
        changes["passport_number"] = passport_number
    if locale is not None:
        user.locale = locale
        changes["locale"] = locale
    if admin_comment is not None:
        user.admin_comment = admin_comment
        changes["admin_comment"] = admin_comment
    
    if birth_date is not None:
        try:
            user.birth_date = datetime.strptime(birth_date, "%Y-%m-%d")
            changes["birth_date"] = birth_date
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат даты рождения (YYYY-MM-DD)")
    
    if drivers_license_expiry is not None:
        try:
            user.drivers_license_expiry = datetime.strptime(drivers_license_expiry, "%Y-%m-%d")
            changes["drivers_license_expiry"] = drivers_license_expiry
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат даты прав (YYYY-MM-DD)")
    
    if id_card_expiry is not None:
        try:
            user.id_card_expiry = datetime.strptime(id_card_expiry, "%Y-%m-%d")
            changes["id_card_expiry"] = id_card_expiry
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат даты ID карты (YYYY-MM-DD)")
    
    if role is not None:
        try:
            old_role = user.role
            new_role = UserRole(role)
            user.role = new_role
            changes["role"] = role
            
            if (new_role in [UserRole.REJECTFIRST, UserRole.REJECTSECOND, UserRole.REJECTFIRSTDOC, UserRole.REJECTFIRSTCERT] 
                and old_role != new_role):
                from app.guarantor.router import cancel_guarantor_requests_on_rejection
                await cancel_guarantor_requests_on_rejection(str(user.id), db)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Неверная роль: {role}")
    
    if auto_class is not None:
        user.auto_class = [c.strip().upper() for c in auto_class.split(",") if c.strip()]
        changes["auto_class"] = user.auto_class
    
    if is_active is not None:
        user.is_active = is_active
        changes["is_active"] = is_active
    if is_blocked is not None:
        user.is_blocked = is_blocked
        changes["is_blocked"] = is_blocked
    if is_verified_email is not None:
        user.is_verified_email = is_verified_email
        changes["is_verified_email"] = is_verified_email
    if is_citizen_kz is not None:
        user.is_citizen_kz = is_citizen_kz
        changes["is_citizen_kz"] = is_citizen_kz
    if documents_verified is not None:
        user.documents_verified = documents_verified
        changes["documents_verified"] = documents_verified
    if is_consent_to_data_processing is not None:
        user.is_consent_to_data_processing = is_consent_to_data_processing
        changes["is_consent_to_data_processing"] = is_consent_to_data_processing
    if is_contract_read is not None:
        user.is_contract_read = is_contract_read
        changes["is_contract_read"] = is_contract_read
    if is_user_agreement is not None:
        user.is_user_agreement = is_user_agreement
        changes["is_user_agreement"] = is_user_agreement
    if can_exit_zone is not None:
        user.can_exit_zone = can_exit_zone
        changes["can_exit_zone"] = can_exit_zone
    
    if wallet_balance is not None:
        user.wallet_balance = wallet_balance
        changes["wallet_balance"] = wallet_balance
    if rating is not None:
        user.rating = rating
        changes["rating"] = rating
    
    ALLOWED_FILE_TYPES = ["image/jpeg", "image/png", "application/pdf"]
    
    async def save_if_provided(file: Optional[UploadFile], field_name: str) -> Optional[str]:
        if file is None or file.filename is None or file.filename == "":
            return None
        if file.content_type not in ALLOWED_FILE_TYPES:
            raise HTTPException(status_code=400, detail=f"Файл {field_name} должен быть JPEG, PNG или PDF")
        path = await save_file(file, user.id, "uploads/documents")
        changes[field_name] = path
        return path
    
    if selfie:
        path = await save_if_provided(selfie, "selfie_url")
        if path:
            user.selfie_url = path
    
    if selfie_with_license:
        path = await save_if_provided(selfie_with_license, "selfie_with_license_url")
        if path:
            user.selfie_with_license_url = path
    
    if drivers_license:
        path = await save_if_provided(drivers_license, "drivers_license_url")
        if path:
            user.drivers_license_url = path
    
    if id_card_front:
        path = await save_if_provided(id_card_front, "id_card_front_url")
        if path:
            user.id_card_front_url = path
    
    if id_card_back:
        path = await save_if_provided(id_card_back, "id_card_back_url")
        if path:
            user.id_card_back_url = path
    
    if psych_neurology_certificate:
        path = await save_if_provided(psych_neurology_certificate, "psych_neurology_certificate_url")
        if path:
            user.psych_neurology_certificate_url = path
    
    if narcology_certificate:
        path = await save_if_provided(narcology_certificate, "narcology_certificate_url")
        if path:
            user.narcology_certificate_url = path
    
    if pension_contributions_certificate:
        path = await save_if_provided(pension_contributions_certificate, "pension_contributions_certificate_url")
        if path:
            user.pension_contributions_certificate_url = path
    
    db.commit()
    
    log_action(
        db,
        actor_id=current_user.id,
        action="admin_edit_user_full",
        entity_type="user",
        entity_id=user.id,
        details={"changes": changes}
    )
    
    db.commit()
    
    asyncio.create_task(notify_user_status_update(str(user.id)))
    
    return {
        "message": "Пользователь обновлен",
        "user_id": uuid_to_sid(user.id),
        "changes_count": len(changes),
        "changed_fields": list(changes.keys())
    }


@users_router.patch("/{user_id}/block")
async def block_user(
    user_id: str,
    block_data: UserBlockSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Блокировка/разблокировка пользователя по ИИН/паспорту"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Если блокируем и причина не указана
    if block_data.is_blocked and not block_data.block_reason:
        raise HTTPException(status_code=400, detail="При блокировке обязательно указать причину")
    
    # Обновляем статус блокировки
    user.is_blocked = block_data.is_blocked
    
    # Сохраняем причину блокировки в комментарии
    if block_data.is_blocked:
        block_reason = f"Блокировка: {block_data.block_reason}"
        if user.admin_comment:
            user.admin_comment = f"{user.admin_comment}\n{block_reason}"
        else:
            user.admin_comment = block_reason
    
    db.commit()

    log_action(
        db,
        actor_id=current_user.id,
        action="block_user",
        entity_type="user",
        entity_id=user.id,
        details={
            "is_blocked": block_data.is_blocked,
            "reason": block_data.block_reason
        }
    )

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
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
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
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
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
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав. Только администраторы или техподдержка могут удалять аренды")

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


@users_router.post("/rentals/{rental_id}/admin-upload-photos-before")
async def admin_upload_photos_before(
    rental_id: str,
    selfie: Optional[UploadFile] = File(None, description="Селфи клиента (необязательно для владельца)"),
    car_photos: List[UploadFile] = File(..., description="Фотографии кузова автомобиля"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Загрузить фотографии ДО начала аренды от имени клиента (только для админа).
    
    - selfie: селфи клиента (необязательно для владельца)
    - car_photos: фотографии кузова автомобиля (обязательно)
    
    Без проверки ГЛОНАСС и без отправки GPS-команд — просто загрузка файлов.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Только администратор или техподдержка может загружать фотографии от имени клиентов")
    
    try:
        rental_uuid = safe_sid_to_uuid(rental_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Неверный формат rental_id: {str(e)}")
    
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")
    
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    validate_photos(car_photos, "car_photos")
    if selfie:
        validate_photos([selfie], "selfie")
    
    uploaded_files = []
    try:
        urls = list(rental.photos_before or [])
        
        if selfie:
            selfie_url = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/before/selfie/")
            urls.append(selfie_url)
            uploaded_files.append(selfie_url)
        
        for p in car_photos:
            car_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/before/car/")
            urls.append(car_url)
            uploaded_files.append(car_url)
        
        rental.photos_before = urls
        db.commit()
        
        db.expire_all()
        db.refresh(rental)
        
        try:
            if rental.user_id:
                await notify_user_status_update(str(rental.user_id))
            if car.owner_id:
                await notify_user_status_update(str(car.owner_id))
        except Exception as e:
            print(f"Error sending WebSocket notifications: {e}")
        
        return {
            "message": "Фотографии до аренды (selfie+car) загружены",
            "rental_id": rental_id,
            "photo_count": len(urls),
            "selfie_uploaded": selfie is not None
        }
    except HTTPException:
        db.rollback()
        # Удаляем загруженные файлы из MinIO
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        # Удаляем загруженные файлы из MinIO
        delete_uploaded_files(uploaded_files)
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке фотографий: {str(e)}")


@users_router.post("/rentals/{rental_id}/admin-upload-photos-before-interior")
async def admin_upload_photos_before_interior(
    rental_id: str,
    interior_photos: List[UploadFile] = File(..., description="Фотографии салона автомобиля"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Загрузить фотографии салона ДО начала аренды от имени клиента (только для админа).
    
    - interior_photos: фотографии салона автомобиля (обязательно)
    
    Без проверки ГЛОНАСС и без отправки GPS-команд — просто загрузка файлов.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Только администратор или техподдержка может загружать фотографии от имени клиентов")
    
    try:
        rental_uuid = safe_sid_to_uuid(rental_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Неверный формат rental_id: {str(e)}")
    
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")
    
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    validate_photos(interior_photos, "interior_photos")
    
    uploaded_files = []
    try:
        urls = list(rental.photos_before or [])
        
        for p in interior_photos:
            interior_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/before/interior/")
            urls.append(interior_url)
            uploaded_files.append(interior_url)
        
        rental.photos_before = urls
        db.commit()
        
        db.expire_all()
        db.refresh(rental)
        
        try:
            if rental.user_id:
                await notify_user_status_update(str(rental.user_id))
            if car.owner_id:
                await notify_user_status_update(str(car.owner_id))
        except Exception as e:
            print(f"Error sending WebSocket notifications: {e}")
        
        return {
            "message": "Фотографии салона до аренды загружены",
            "rental_id": rental_id,
            "photo_count": len(interior_photos)
        }
    except HTTPException:
        db.rollback()
        # Удаляем загруженные файлы из MinIO
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        # Удаляем загруженные файлы из MinIO
        delete_uploaded_files(uploaded_files)
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке фотографий салона: {str(e)}")


@users_router.post("/rentals/{rental_id}/admin-upload-photos-after")
async def admin_upload_photos_after(
    rental_id: str,
    selfie: Optional[UploadFile] = File(None, description="Селфи клиента (необязательно для владельца)"),
    interior_photos: List[UploadFile] = File(..., description="Фотографии салона автомобиля"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Загрузить фотографии ПОСЛЕ аренды от имени клиента (только для админа).
    
    - selfie: селфи клиента (необязательно для владельца)
    - interior_photos: фотографии салона автомобиля (обязательно)
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Только администратор или техподдержка может загружать фотографии от имени клиентов")
    
    try:
        rental_uuid = safe_sid_to_uuid(rental_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Неверный формат rental_id: {str(e)}")
    
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")
    
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    validate_photos(interior_photos, "interior_photos")
    if selfie:
        validate_photos([selfie], "selfie")
    
    uploaded_files = []
    try:
        urls = list(rental.photos_after or [])
        
        if selfie:
            selfie_url = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/after/selfie/")
            urls.append(selfie_url)
            uploaded_files.append(selfie_url)
        
        for p in interior_photos:
            interior_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/after/interior/")
            urls.append(interior_url)
            uploaded_files.append(interior_url)
        
        rental.photos_after = urls
        db.commit()
        
        db.expire_all()
        db.refresh(rental)
        
        try:
            if rental.user_id:
                await notify_user_status_update(str(rental.user_id))
            if car.owner_id:
                await notify_user_status_update(str(car.owner_id))
        except Exception as e:
            print(f"Error sending WebSocket notifications: {e}")
        
        return {
            "message": "Фотографии после аренды (selfie+interior) загружены",
            "rental_id": rental_id,
            "photo_count": len(urls),
            "selfie_uploaded": selfie is not None
        }
    except HTTPException:
        db.rollback()
        # Удаляем загруженные файлы из MinIO
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        # Удаляем загруженные файлы из MinIO
        delete_uploaded_files(uploaded_files)
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке фотографий: {str(e)}")


@users_router.post("/rentals/{rental_id}/admin-upload-photos-after-car")
async def admin_upload_photos_after_car(
    rental_id: str,
    car_photos: List[UploadFile] = File(..., description="Фотографии кузова автомобиля"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Загрузить фотографии кузова ПОСЛЕ аренды от имени клиента (только для админа).
    
    - car_photos: фотографии кузова автомобиля (обязательно)
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Только администратор или техподдержка может загружать фотографии от имени клиентов")
    
    try:
        rental_uuid = safe_sid_to_uuid(rental_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Неверный формат rental_id: {str(e)}")
    
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")
    
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    validate_photos(car_photos, "car_photos")
    
    uploaded_files = []
    try:
        urls = list(rental.photos_after or [])
        
        for p in car_photos:
            car_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/after/car/")
            urls.append(car_url)
            uploaded_files.append(car_url)
        
        rental.photos_after = urls
        db.commit()
        
        db.expire_all()
        db.refresh(rental)
        
        try:
            if rental.user_id:
                await notify_user_status_update(str(rental.user_id))
            if car.owner_id:
                await notify_user_status_update(str(car.owner_id))
        except Exception as e:
            print(f"Error sending WebSocket notifications: {e}")
        
        return {
            "message": "Фотографии кузова после аренды загружены",
            "rental_id": rental_id,
            "photo_count": len(car_photos)
        }
    except HTTPException:
        db.rollback()
        # Удаляем загруженные файлы из MinIO
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        # Удаляем загруженные файлы из MinIO
        delete_uploaded_files(uploaded_files)
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке фотографий кузова: {str(e)}")



@users_router.post("/rentals/review", response_model=AdminRentalReviewResponse)
async def admin_submit_rental_review(
    request: AdminRentalReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> AdminRentalReviewResponse:
    """
    Добавить/обновить оценку и комментарий к аренде от имени клиента (только для админа).
    После добавления отзыва аренда автоматически завершается, а машина переходит в статус PENDING.
    
    - rental_id: ID аренды
    - rating: оценка от 1 до 5
    - comment: текстовый комментарий (опционально)
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Только администратор или техподдержка может добавлять оценки от имени клиентов")
    
    try:
        rental_uuid = safe_sid_to_uuid(request.rental_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Неверный формат rental_id: {str(e)}")
    
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")
    
    # 1. Сохраняем отзыв
    existing_review = db.query(RentalReview).filter(RentalReview.rental_id == rental.id).first()
    is_update = False
    
    if existing_review:
        existing_review.rating = request.rating
        existing_review.comment = request.comment
        is_update = True
    else:
        review = RentalReview(
            rental_id=rental.id,
            rating=request.rating,
            comment=request.comment
        )
        db.add(review)
    
    # 2. Завершаем аренду, если она активна
    rental_completed = False
    total_charged = None
    
    if rental.rental_status == RentalStatus.IN_USE:
        # Получаем машину и пользователя
        car = db.query(Car).filter(Car.id == rental.car_id).first()
        user = db.query(User).filter(User.id == rental.user_id).first()
        
        if car and user:
            now = get_local_time()
            start_time = rental.start_time or rental.reservation_time
            
            # Рассчитываем фактическую длительность в минутах
            if start_time:
                total_seconds = (now - start_time).total_seconds()
                actual_minutes = total_seconds / 60
                rounded_minutes = ceil(actual_minutes)
            else:
                rounded_minutes = 0
                actual_minutes = 0
            
            # Сохраняем оригинальное значение duration (часы/дни) до перезаписи
            original_duration = rental.duration
            
            price_per_minute = car.price_per_minute or 0
            price_per_hour = car.price_per_hour or 0
            price_per_day = car.price_per_day or 0
            
            # Базовая плата по типу аренды
            if rental.rental_type == RentalType.MINUTES:
                rental.base_price = rounded_minutes * price_per_minute
            elif rental.rental_type == RentalType.HOURS:
                rental.base_price = original_duration * price_per_hour
            else:  # DAYS
                rental.base_price = original_duration * price_per_day
            
            # Переработка (сверхтариф) для часов/дней
            if rental.rental_type in (RentalType.HOURS, RentalType.DAYS):
                planned_minutes = (
                    original_duration * 60
                    if rental.rental_type == RentalType.HOURS
                    else original_duration * 24 * 60
                )
                overtime_mins = max(0, rounded_minutes - planned_minutes)
                rental.overtime_fee = overtime_mins * price_per_minute
            else:
                rental.overtime_fee = 0
            
            # Расчет платного ожидания (waiting_fee)
            waiting_fee = 0
            waiting_minutes = 0
            extra_minutes = 0
            
            if rental.reservation_time and rental.start_time:
                waiting_seconds = (rental.start_time - rental.reservation_time).total_seconds()
                waiting_minutes = waiting_seconds / 60
                
                if waiting_minutes > 15:
                    extra_minutes = ceil(waiting_minutes - 15)
                    waiting_fee = int(extra_minutes * price_per_minute * 0.5)
            
            # Проверяем существующую транзакцию waiting_fee
            existing_waiting_tx = db.query(WalletTransaction).filter(
                WalletTransaction.related_rental_id == rental.id,
                WalletTransaction.transaction_type == WalletTransactionType.RENT_WAITING_FEE
            ).first()
            
            if waiting_fee > 0:
                if existing_waiting_tx:
                    already_charged_waiting = float(abs(existing_waiting_tx.amount)) if existing_waiting_tx.amount else 0
                    difference_waiting = waiting_fee - already_charged_waiting
                    
                    if abs(difference_waiting) > 0.01:
                        if difference_waiting > 0 and user.wallet_balance >= difference_waiting:
                            balance_before_waiting = float(user.wallet_balance)
                            user.wallet_balance -= difference_waiting
                            existing_waiting_tx.amount = -waiting_fee
                            existing_waiting_tx.description = f"Платное ожидание {int(extra_minutes)} мин"
                            existing_waiting_tx.balance_before = balance_before_waiting
                            existing_waiting_tx.balance_after = float(user.wallet_balance)
                        elif difference_waiting < 0:
                            refund = abs(difference_waiting)
                            balance_before_waiting = float(user.wallet_balance)
                            user.wallet_balance += refund
                            existing_waiting_tx.amount = -waiting_fee
                            existing_waiting_tx.description = f"Платное ожидание {int(extra_minutes)} мин (перерасчёт)"
                            existing_waiting_tx.balance_before = balance_before_waiting
                            existing_waiting_tx.balance_after = float(user.wallet_balance)
                else:
                    if user.wallet_balance >= waiting_fee:
                        balance_before_waiting = float(user.wallet_balance)
                        user.wallet_balance -= waiting_fee
                        waiting_tx = WalletTransaction(
                            user_id=user.id,
                            amount=-waiting_fee,
                            transaction_type=WalletTransactionType.RENT_WAITING_FEE,
                            description=f"Платное ожидание {int(extra_minutes)} мин",
                            balance_before=balance_before_waiting,
                            balance_after=float(user.wallet_balance),
                            related_rental_id=rental.id,
                            created_at=get_local_time()
                        )
                        db.add(waiting_tx)
            
            rental.waiting_fee = waiting_fee
            
            # Убедиться, что все сборы не None
            rental.open_fee = rental.open_fee or 0
            rental.delivery_fee = rental.delivery_fee or 0
            rental.distance_fee = rental.distance_fee or 0
            
            # Расчет топлива (только для часового/суточного тарифа)
            fuel_fee = 0
            if rental.rental_type in (RentalType.HOURS, RentalType.DAYS):
                existing_fuel_tx = db.query(WalletTransaction).filter(
                    WalletTransaction.related_rental_id == rental.id,
                    WalletTransaction.transaction_type == WalletTransactionType.RENT_FUEL_FEE
                ).first()
                
                if existing_fuel_tx:
                    fuel_fee = float(abs(existing_fuel_tx.amount)) if existing_fuel_tx.amount else 0
                elif rental.fuel_before is not None and rental.fuel_after is not None:
                    if rental.fuel_after < rental.fuel_before:
                        fuel_before_rounded = ceil(rental.fuel_before)
                        fuel_after_rounded = floor(rental.fuel_after)
                        fuel_consumed = fuel_before_rounded - fuel_after_rounded
                        if fuel_consumed > 0:
                            if car.body_type == CarBodyType.ELECTRIC:
                                price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
                            else:
                                price_per_liter = FUEL_PRICE_PER_LITER
                            fuel_fee = int(fuel_consumed * price_per_liter)
                            
                            if user.wallet_balance >= fuel_fee:
                                balance_before_fuel = float(user.wallet_balance)
                                user.wallet_balance -= fuel_fee
                                fuel_tx = WalletTransaction(
                                    user_id=user.id,
                                    amount=-fuel_fee,
                                    transaction_type=WalletTransactionType.RENT_FUEL_FEE,
                                    description=f"Оплата топлива: {int(fuel_consumed)} л × {price_per_liter}₸ = {fuel_fee:,}₸" if car.body_type != CarBodyType.ELECTRIC else f"Оплата заряда: {int(fuel_consumed)}% × {price_per_liter}₸ = {fuel_fee:,}₸",
                                    balance_before=balance_before_fuel,
                                    balance_after=float(user.wallet_balance),
                                    related_rental_id=rental.id,
                                    created_at=get_local_time()
                                )
                                db.add(fuel_tx)
            
            # Проверка base_price для часового/суточного тарифа
            if rental.rental_type in (RentalType.HOURS, RentalType.DAYS) and not (car.owner_id == user.id):
                expected_base_price = rental.base_price
                
                # Ищем транзакцию base_price
                base_charge_tx = None
                actual_base_charged = 0
                
                for tx in db.query(WalletTransaction).filter(
                    WalletTransaction.related_rental_id == rental.id,
                    WalletTransaction.transaction_type == WalletTransactionType.RENT_BASE_CHARGE
                ).all():
                    desc = tx.description or ""
                    if "оплат" in desc.lower() and "аренд" in desc.lower() and ("час" in desc.lower() or "день" in desc.lower()):
                        actual_base_charged = float(abs(tx.amount)) if tx.amount else 0
                        base_charge_tx = tx
                        break
                
                if abs(actual_base_charged - expected_base_price) > 0.01:
                    difference_base = expected_base_price - actual_base_charged
                    
                    if base_charge_tx:
                        balance_before_base = float(user.wallet_balance or 0) + float(abs(base_charge_tx.amount) if base_charge_tx.amount else 0)
                        if balance_before_base >= expected_base_price:
                            user.wallet_balance = balance_before_base - expected_base_price
                            base_charge_tx.amount = -expected_base_price
                            base_charge_tx.description = f"Оплата аренды: {original_duration} {'час(ов)' if rental.rental_type == RentalType.HOURS else 'день(дней)'} (перерасчёт)"
                            base_charge_tx.balance_before = balance_before_base
                            base_charge_tx.balance_after = float(user.wallet_balance or 0)
                    else:
                        balance_before_base = float(user.wallet_balance or 0)
                        if balance_before_base >= expected_base_price:
                            user.wallet_balance -= expected_base_price
                            base_charge_tx = WalletTransaction(
                                user_id=user.id,
                                amount=-expected_base_price,
                                transaction_type=WalletTransactionType.RENT_BASE_CHARGE,
                                description=f"Оплата аренды: {original_duration} {'час(ов)' if rental.rental_type == RentalType.HOURS else 'день(дней)'}",
                                balance_before=balance_before_base,
                                balance_after=float(user.wallet_balance or 0),
                                related_rental_id=rental.id,
                                created_at=get_local_time()
                            )
                            db.add(base_charge_tx)
                    
                    rental.base_price = expected_base_price
            
            # Проверка overtime_fee
            if rental.rental_type in (RentalType.HOURS, RentalType.DAYS):
                planned_minutes = (
                    original_duration * 60 if rental.rental_type == RentalType.HOURS
                    else original_duration * 24 * 60
                )
                
                if rounded_minutes > planned_minutes:
                    expected_overtime_minutes = int(rounded_minutes - planned_minutes)
                    expected_overtime_cost = expected_overtime_minutes * price_per_minute
                    
                    overtime_tx = db.query(WalletTransaction).filter(
                        WalletTransaction.related_rental_id == rental.id,
                        WalletTransaction.transaction_type == WalletTransactionType.RENT_OVERTIME_FEE
                    ).order_by(WalletTransaction.created_at.desc()).first()
                    
                    actual_overtime_charged = float(abs(overtime_tx.amount)) if overtime_tx and overtime_tx.amount else 0
                    
                    if abs(actual_overtime_charged - expected_overtime_cost) > 0.01:
                        difference_overtime = expected_overtime_cost - actual_overtime_charged
                        
                        if overtime_tx:
                            balance_before_overtime = float(user.wallet_balance or 0) + float(abs(overtime_tx.amount) if overtime_tx.amount else 0)
                            if balance_before_overtime >= expected_overtime_cost:
                                user.wallet_balance = balance_before_overtime - expected_overtime_cost
                                overtime_tx.amount = -expected_overtime_cost
                                overtime_tx.description = f"Сверхтариф {expected_overtime_minutes} мин (перерасчёт)"
                                overtime_tx.balance_before = balance_before_overtime
                                overtime_tx.balance_after = float(user.wallet_balance or 0)
                        else:
                            balance_before_overtime = float(user.wallet_balance or 0)
                            if balance_before_overtime >= expected_overtime_cost:
                                user.wallet_balance -= expected_overtime_cost
                                overtime_tx = WalletTransaction(
                                    user_id=user.id,
                                    amount=-expected_overtime_cost,
                                    transaction_type=WalletTransactionType.RENT_OVERTIME_FEE,
                                    description=f"Сверхтариф {expected_overtime_minutes} мин",
                                    balance_before=balance_before_overtime,
                                    balance_after=float(user.wallet_balance or 0),
                                    related_rental_id=rental.id,
                                    created_at=get_local_time()
                                )
                                db.add(overtime_tx)
                        
                        rental.overtime_fee = expected_overtime_cost
            
            # Обновляем статус аренды
            rental.end_time = now
            rental.end_latitude = car.latitude
            rental.end_longitude = car.longitude
            rental.rental_status = RentalStatus.COMPLETED
            rental.duration = rounded_minutes
            
            # Рассчитываем total_price и already_payed
            if car.owner_id == user.id:
                rental.base_price = 0
                rental.open_fee = 0
                rental.waiting_fee = 0
                rental.overtime_fee = 0
                rental.distance_fee = 0
                rental.total_price = fuel_fee
                rental.already_payed = 0
            else:
                total_price_without_fuel = (
                    (rental.base_price or 0) +
                    (rental.open_fee or 0) +
                    (rental.delivery_fee or 0) +
                    (rental.waiting_fee or 0) +
                    (rental.overtime_fee or 0) +
                    (rental.distance_fee or 0)
                )
                rental.total_price = total_price_without_fuel + fuel_fee
                
                if user.wallet_balance >= 0:
                    if rental.rental_type in [RentalType.HOURS, RentalType.DAYS]:
                        rental.already_payed = (
                            (rental.base_price or 0) +
                            (rental.open_fee or 0) +
                            (rental.delivery_fee or 0) +
                            (rental.waiting_fee or 0) +
                            (rental.overtime_fee or 0) +
                            fuel_fee
                        )
                    elif rental.rental_type == RentalType.MINUTES:
                        rental.already_payed = (
                            (rental.base_price or 0) +
                            (rental.open_fee or 0) +
                            (rental.delivery_fee or 0) +
                            (rental.waiting_fee or 0) +
                            (rental.distance_fee or 0) +
                            (rental.driver_fee or 0)
                        )
                else:
                    if rental.already_payed is None:
                        rental.already_payed = 0
            
            # Машина переходит в статус PENDING (требуется проверка механиком)
            car.status = CarStatus.PENDING
            car.current_renter_id = None
            
            rental_completed = True
            total_charged = rental.total_price  # Общая сумма аренды
            
            # Обновляем last_activity пользователя
            user.last_activity_at = now
            
            # Отправляем WebSocket уведомления
            try:
                if rental.user_id:
                    await notify_user_status_update(str(rental.user_id))
                if car.owner_id:
                    await notify_user_status_update(str(car.owner_id))
            except Exception as e:
                print(f"Error sending WebSocket notifications: {e}")
            
            # Отправляем уведомление всем механикам о новой машине для проверки
            try:
                await send_localized_notification_to_all_mechanics(
                    db,
                    "new_car_for_inspection",
                    "new_car_for_inspection",
                    car_name=car.name,
                    plate_number=car.plate_number
                )
            except Exception as e:
                print(f"Error sending notification to mechanics: {e}")
    
        db.commit()
        
        return {
        "message": "Отзыв добавлен и аренда завершена" if rental_completed else ("Оценка обновлена" if is_update else "Оценка добавлена"),
            "rental_id": request.rental_id,
        "rating": request.rating,
        "comment": request.comment,
        "updated": is_update,
        "rental_completed": rental_completed,
        "total_charged": total_charged
        }



@users_router.post("/rentals/cancel", response_model=AdminCancelReservationResponse)
async def admin_cancel_reservation(
    request: AdminCancelReservationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> AdminCancelReservationResponse:
    """
    Отменить бронь/аренду клиента от имени админа.
    
    - rental_id: ID аренды
    
    Работает для статусов: RESERVED, DELIVERING, DELIVERY_RESERVED, DELIVERING_IN_PROGRESS, SCHEDULED, IN_USE
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Только администратор или техподдержка может отменять брони")
    
    try:
        rental_uuid = safe_sid_to_uuid(request.rental_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Неверный формат rental_id: {str(e)}")
    
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")
    
    cancellable_statuses = [
        RentalStatus.RESERVED,
        RentalStatus.DELIVERING,
        RentalStatus.DELIVERY_RESERVED,
        RentalStatus.DELIVERING_IN_PROGRESS,
        RentalStatus.SCHEDULED,
        RentalStatus.IN_USE,
    ]
    
    if rental.rental_status not in cancellable_statuses:
        raise HTTPException(
            status_code=400, 
            detail=f"Нельзя отменить аренду со статусом {rental.rental_status.value}"
        )
    
    previous_status = rental.rental_status.value
    
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    rental.rental_status = RentalStatus.CANCELLED
    rental.end_time = datetime.now()
    
    car.current_renter_id = None
    car.status = CarStatus.FREE
    
    client_id = uuid_to_sid(rental.user_id) if rental.user_id else None
    
    db.commit()
    
    try:
        if rental.user_id:
            await notify_user_status_update(str(rental.user_id))
        if car.owner_id:
            await notify_user_status_update(str(car.owner_id))
    except Exception as e:
        print(f"Error sending WebSocket notifications: {e}")
    
    return AdminCancelReservationResponse(
        message="Бронь отменена",
        rental_id=request.rental_id,
        car_name=car.name,
        plate_number=car.plate_number,
        previous_status=previous_status,
        client_id=client_id
    )



@users_router.post("/rentals/extend", response_model=AdminExtendRentalResponse)
async def admin_extend_rental(
    request: AdminExtendRentalRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> AdminExtendRentalResponse:
    """
    Продлить аренду клиента от имени админа.
    
    - Для часовой аренды: добавляет указанное количество часов
    - Для суточной аренды: добавляет указанное количество дней
    
    Создаёт транзакцию, списывает с баланса клиента, отправляет уведомление.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Только администратор или техподдержка может продлевать аренды")
    
    try:
        rental_uuid = safe_sid_to_uuid(request.rental_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Неверный формат rental_id: {str(e)}")
    
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")
    
    if rental.rental_status != RentalStatus.IN_USE:
        raise HTTPException(status_code=400, detail=f"Аренда не активна (статус: {rental.rental_status.value})")
    
    if rental.rental_type not in [RentalType.HOURS, RentalType.DAYS]:
        raise HTTPException(status_code=400, detail="Продление доступно только для часовой и суточной аренды")
    
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    user = db.query(User).filter(User.id == rental.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    
    count = request.count if request.count else 1
    
    if rental.rental_type == RentalType.HOURS:
        price_per_unit = car.price_per_hour or 0
        price_to_charge = price_per_unit * count
        added_duration = count
        if count == 1:
            duration_text = "1 час"
        elif count < 5:
            duration_text = f"{count} часа"
        else:
            duration_text = f"{count} часов"
    else:  
        price_per_unit = car.price_per_day or 0
        price_to_charge = price_per_unit * count
        added_duration = count
        if count == 1:
            duration_text = "1 день"
        elif count < 5:
            duration_text = f"{count} дня"
        else:
            duration_text = f"{count} дней"
    
    balance_before = float(user.wallet_balance or 0)
    if balance_before < price_to_charge:
        raise HTTPException(
            status_code=400, 
            detail=f"Недостаточно средств на балансе клиента. Нужно: {price_to_charge}, доступно: {balance_before}"
        )
    
    user.wallet_balance = balance_before - price_to_charge
    
    record_wallet_transaction(
        db,
        user=user,
        amount=-price_to_charge,
        ttype=WalletTransactionType.RENT_BASE_CHARGE,
        description=f"Продление аренды на {duration_text}",
        related_rental=rental,
        balance_before_override=balance_before
    )
    
    rental.duration = (rental.duration or 0) + added_duration
    rental.already_payed = (rental.already_payed or 0) + price_to_charge
    
    new_balance = float(user.wallet_balance)
    
    db.commit()
    
    try:
        await notify_user_status_update(str(user.id))
        if car.owner_id:
            await notify_user_status_update(str(car.owner_id))
    except Exception as e:
        print(f"Error sending WebSocket notifications: {e}")
    
    try:
        if user_has_push_tokens(db, user.id):
            new_duration = rental.duration or added_duration
            if rental.rental_type == RentalType.HOURS:
                days_text = "час" if count == 1 else ("часа" if count < 5 else "часов")
                days_text2 = "час" if new_duration == 1 else ("часа" if new_duration < 5 else "часов")
            else:
                days_text = "день" if count == 1 else ("дня" if count < 5 else "дней")
                days_text2 = "день" if new_duration == 1 else ("дня" if new_duration < 5 else "дней")
            
            await send_localized_notification_to_user_async(
                user.id,
                "rental_extended",
                "rental_extended",
                days=count,
                days_text=days_text,
                new_duration=new_duration,
                days_text2=days_text2,
                cost=int(price_to_charge)
            )
    except Exception as e:
        print(f"Error sending push notification: {e}")
    
    return AdminExtendRentalResponse(
        message=f"Аренда продлена на {duration_text}",
        rental_id=request.rental_id,
        rental_type=rental.rental_type.value,
        added_duration=added_duration,
        price_charged=price_to_charge,
        new_duration=rental.duration,
        new_balance=new_balance,
        car_name=car.name,
        plate_number=car.plate_number
    )



@users_router.post("/rentals/{rental_id}/mechanic-start-inspection", response_model=MechanicStartInspectionResponse)
async def admin_mechanic_start_inspection(
    rental_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> MechanicStartInspectionResponse:
    """Начало осмотра механиком от имени админа (без GPS команд). Меняет статус с PENDING на IN_USE."""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Только администратор или техподдержка")
    
    rental_uuid = safe_sid_to_uuid(rental_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")
    
    # Проверяем, что механик назначен
    if not rental.mechanic_inspector_id:
        raise HTTPException(status_code=400, detail="Механик-инспектор не назначен для этой аренды")
    
    # Проверяем, что статус осмотра PENDING
    if rental.mechanic_inspection_status != "PENDING":
        raise HTTPException(
            status_code=400, 
            detail=f"Осмотр может быть начат только со статусом PENDING. Текущий статус: {rental.mechanic_inspection_status}"
        )
    
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    # Сохраняем назначенного механика (не меняем mechanic_inspector_id)
    mechanic_id = rental.mechanic_inspector_id
    
    # Устанавливаем время начала осмотра, если еще не установлено
    if not rental.mechanic_inspection_start_time:
        rental.mechanic_inspection_start_time = get_local_time()
        rental.mechanic_inspection_start_latitude = car.latitude
        rental.mechanic_inspection_start_longitude = car.longitude
    
    # Меняем статус осмотра с PENDING на IN_USE
    rental.mechanic_inspection_status = "IN_USE"
    
    # Обновляем статус автомобиля и текущего арендатора
    car.status = CarStatus.IN_USE
    car.current_renter_id = mechanic_id
    
    log_action(
        db,
        actor_id=current_user.id,
        action="mechanic_start_inspection",
        entity_type="rental",
        entity_id=rental.id,
        details={"status": "IN_USE", "mechanic_id": str(mechanic_id)}
    )

    db.commit()
    
    try:
        await notify_user_status_update(str(mechanic_id))
        if rental.user_id:
            await notify_user_status_update(str(rental.user_id))
    except:
        pass
    
    return {"message": "Осмотр начат", "rental_id": rental_id, "inspection_status": "IN_USE"}


@users_router.post("/rentals/{rental_id}/mechanic-photos-before", response_model=MechanicPhotoUploadResponse)
async def admin_mechanic_upload_photos_before(
    rental_id: str,
    selfie: Optional[UploadFile] = File(None),
    car_photos: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> MechanicPhotoUploadResponse:
    """Загрузка фото ДО осмотра: селфи (опционально) + кузов. Без GPS."""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Только администратор или техподдержка")
    
    rental_uuid = safe_sid_to_uuid(rental_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")
    
    validate_photos(car_photos, "car_photos")
    urls = list(rental.mechanic_photos_before or [])
    
    if selfie:
        validate_photos([selfie], "selfie")
        selfie_url = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/mechanic/before/selfie/")
        urls.append(selfie_url)
    
    for p in car_photos:
        photo_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/mechanic/before/car/")
        urls.append(photo_url)
    
    rental.mechanic_photos_before = urls
    
    log_action(
        db,
        actor_id=current_user.id,
        action="mechanic_upload_photos_before",
        entity_type="rental",
        entity_id=rental.id,
        details={"photo_count": len(urls)}
    )
    db.commit()
    
    return {"message": "Фото до осмотра (селфи+кузов) загружены", "photo_count": len(urls)}


@users_router.post("/rentals/{rental_id}/mechanic-photos-before-interior", response_model=MechanicPhotoUploadResponse)
async def admin_mechanic_upload_photos_before_interior(
    rental_id: str,
    interior_photos: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> MechanicPhotoUploadResponse:
    """Загрузка фото ДО осмотра: салон. Без GPS."""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Только администратор или техподдержка")
    
    rental_uuid = safe_sid_to_uuid(rental_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")
    
    validate_photos(interior_photos, "interior_photos")
    urls = list(rental.mechanic_photos_before or [])
    
    for p in interior_photos:
        photo_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/mechanic/before/interior/")
        urls.append(photo_url)
    
    rental.mechanic_photos_before = urls

    log_action(
        db,
        actor_id=current_user.id,
        action="mechanic_upload_photos_before_interior",
        entity_type="rental",
        entity_id=rental.id,
        details={"photo_count": len(urls)}
    )
    db.commit()
    
    return {"message": "Фото салона до осмотра загружены", "photo_count": len(urls)}


@users_router.post("/rentals/{rental_id}/mechanic-photos-after", response_model=MechanicPhotoUploadResponse)
async def admin_mechanic_upload_photos_after(
    rental_id: str,
    selfie: Optional[UploadFile] = File(None),
    interior_photos: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> MechanicPhotoUploadResponse:
    """Загрузка фото ПОСЛЕ осмотра: селфи (опционально) + салон. Без GPS."""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Только администратор или техподдержка")
    
    rental_uuid = safe_sid_to_uuid(rental_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")
    
    validate_photos(interior_photos, "interior_photos")
    urls = list(rental.mechanic_photos_after or [])
    
    if selfie:
        validate_photos([selfie], "selfie")
        selfie_url = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/mechanic/after/selfie/")
        urls.append(selfie_url)
    
    for p in interior_photos:
        photo_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/mechanic/after/interior/")
        urls.append(photo_url)
    
    rental.mechanic_photos_after = urls

    log_action(
        db,
        actor_id=current_user.id,
        action="mechanic_upload_photos_after",
        entity_type="rental",
        entity_id=rental.id,
        details={"photo_count": len(urls)}
    )
    db.commit()
    
    return {"message": "Фото после осмотра (селфи+салон) загружены", "photo_count": len(urls)}


@users_router.post("/rentals/{rental_id}/mechanic-photos-after-car", response_model=MechanicPhotoUploadResponse)
async def admin_mechanic_upload_photos_after_car(
    rental_id: str,
    car_photos: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> MechanicPhotoUploadResponse:
    """Загрузка фото ПОСЛЕ осмотра: кузов. Без GPS."""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Только администратор или техподдержка")
    
    rental_uuid = safe_sid_to_uuid(rental_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")
    
    validate_photos(car_photos, "car_photos")
    urls = list(rental.mechanic_photos_after or [])
    
    for p in car_photos:
        photo_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/mechanic/after/car/")
        urls.append(photo_url)
    
    rental.mechanic_photos_after = urls

    log_action(
        db,
        actor_id=current_user.id,
        action="mechanic_upload_photos_after_car",
        entity_type="rental",
        entity_id=rental.id,
        details={"photo_count": len(urls)}
    )
    db.commit()
    
    return {"message": "Фото кузова после осмотра загружены", "photo_count": len(urls)}



@users_router.post("/rentals/{rental_id}/mechanic-complete-inspection", response_model=MechanicCompleteInspectionResponse)
async def admin_mechanic_complete_inspection(
    rental_id: str,
    request: AdminMechanicCompleteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> MechanicCompleteInspectionResponse:
    """Завершение осмотра механиком от имени админа. Без GPS."""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Только администратор или техподдержка")
    
    rental_uuid = safe_sid_to_uuid(rental_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")
    
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    rental.mechanic_inspection_status = "COMPLETED"
    rental.mechanic_inspection_end_time = get_local_time()
    rental.mechanic_inspection_end_latitude = car.latitude
    rental.mechanic_inspection_end_longitude = car.longitude
    rental.mechanic_inspection_comment = request.comment
    
    # Меняем статус аренды на COMPLETED при завершении осмотра механиком
    rental.rental_status = RentalStatus.COMPLETED
    if not rental.end_time:
        rental.end_time = get_local_time()
    
    if request.rating:
        existing_review = db.query(RentalReview).filter(RentalReview.rental_id == rental.id).first()
        if existing_review:
            existing_review.mechanic_rating = request.rating
            existing_review.mechanic_comment = request.comment
        else:
            review = RentalReview(rental_id=rental.id, mechanic_rating=request.rating, mechanic_comment=request.comment)
            db.add(review)
    
    car.status = CarStatus.FREE
    car.current_renter_id = None
    
    log_action(
        db,
        actor_id=current_user.id,
        action="mechanic_complete_inspection",
        entity_type="rental",
        entity_id=rental.id,
        details={"rating": request.rating, "comment": request.comment}
    )

    db.commit()
    
    try:
        await notify_user_status_update(str(current_user.id))
        if rental.user_id:
            await notify_user_status_update(str(rental.user_id))
    except:
        pass
    
    return {"message": "Осмотр завершён", "rental_id": rental_id, "car_status": "FREE", "rating": request.rating}



@users_router.post("/rentals/{rental_id}/assign-mechanic", response_model=AssignMechanicResponse)
async def admin_assign_mechanic(
    rental_id: str,
    request: AdminAssignMechanicRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> AssignMechanicResponse:
    """
    Назначить механика для осмотра автомобиля.
    Устанавливает mechanic_inspector_id и отправляет уведомление механику.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Только администратор или техподдержка")
    
    rental_uuid = safe_sid_to_uuid(rental_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")
    
    mechanic_uuid = safe_sid_to_uuid(request.mechanic_id)
    mechanic = db.query(User).filter(User.id == mechanic_uuid).first()
    if not mechanic:
        raise HTTPException(status_code=404, detail="Механик не найден")
    
    if mechanic.role != UserRole.MECHANIC:
        raise HTTPException(status_code=400, detail="Указанный пользователь не является механиком")
    
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    rental.mechanic_inspector_id = mechanic.id
    rental.mechanic_inspection_status = "PENDING"
    
    car.status = CarStatus.SERVICE
    car.current_renter_id = mechanic.id
    
    car.current_renter_id = mechanic.id
    
    log_action(
        db,
        actor_id=current_user.id,
        action="assign_mechanic",
        entity_type="rental",
        entity_id=rental.id,
        details={"mechanic_id": str(mechanic.id), "mechanic_name": f"{mechanic.first_name} {mechanic.last_name}"}
    )

    db.commit()
    
    try:
        await notify_user_status_update(str(mechanic.id))
        if rental.user_id:
            await notify_user_status_update(str(rental.user_id))
        if car.owner_id:
            await notify_user_status_update(str(car.owner_id))
    except Exception as e:
        print(f"Error sending WebSocket notifications: {e}")
    
    try:
        if user_has_push_tokens(db, mechanic.id):
            await send_localized_notification_to_user_async(
                mechanic.id,
                "inspection_assigned_by_admin",
                "inspection_assigned_by_admin",
                car_name=car.name,
                plate_number=car.plate_number
            )
    except Exception as e:
        print(f"Error sending push notification: {e}")
    
    return {
        "message": "Механик назначен",
        "rental_id": rental_id,
        "mechanic_id": request.mechanic_id,
        "mechanic_name": f"{mechanic.first_name or ''} {mechanic.last_name or ''}".strip(),
        "car_name": car.name,
        "plate_number": car.plate_number
    }


@users_router.post("/rentals/{rental_id}/unassign-mechanic", response_model=UnassignMechanicResponse)
async def admin_unassign_mechanic(
    rental_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> UnassignMechanicResponse:
    """
    Снять назначение механика с осмотра.
    Работает только если осмотр ещё не завершён (статус != COMPLETED).
    Освобождает машину и сбрасывает mechanic_inspector_id.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Только администратор или техподдержка")
    
    rental_uuid = safe_sid_to_uuid(rental_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")
    
    if not rental.mechanic_inspector_id:
        raise HTTPException(status_code=400, detail="Механик не назначен для этой аренды")
    
    if rental.mechanic_inspection_status == "COMPLETED":
        raise HTTPException(status_code=400, detail="Осмотр уже завершён, нельзя снять назначение")
    
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    mechanic_id = rental.mechanic_inspector_id
    
    rental.mechanic_inspector_id = None
    rental.mechanic_inspection_status = None
    rental.mechanic_inspection_start_time = None
    
    if car.status == CarStatus.SERVICE:
        car.status = CarStatus.PENDING
        car.current_renter_id = None
    
    if car.status == CarStatus.SERVICE:
        car.status = CarStatus.PENDING
        car.current_renter_id = None
    
    log_action(
        db,
        actor_id=current_user.id,
        action="unassign_mechanic",
        entity_type="rental",
        entity_id=rental.id,
        details={"previous_mechanic_id": str(mechanic_id)}
    )

    db.commit()
    
    try:
        await notify_user_status_update(str(mechanic_id))
        if rental.user_id:
            await notify_user_status_update(str(rental.user_id))
        if car.owner_id:
            await notify_user_status_update(str(car.owner_id))
    except Exception as e:
        print(f"Error sending WebSocket notifications: {e}")
    
    try:
        if user_has_push_tokens(db, mechanic_id):
            await send_localized_notification_to_user_async(
                mechanic_id,
                "inspection_unassigned_by_admin",
                "inspection_unassigned_by_admin",
                car_name=car.name,
                plate_number=car.plate_number
            )
    except Exception as e:
        print(f"Error sending push notification: {e}")
    
    return {
        "message": "Назначение механика снято",
        "rental_id": rental_id,
        "car_name": car.name,
        "plate_number": car.plate_number,
        "car_status": car.status.value
    }


@users_router.delete("/{user_id}", response_model=AdminDeleteUserResponse)
async def delete_user(
    user_id: str,
    delete_data: AdminDeleteUserRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Удаление пользователя (доступно только админу)
    
    - **soft**: Логическое удаление (is_deleted = True, deleted_at = now())
    - **hard**: Физическое удаление из БД (каскадное удаление всех связанных данных)
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Только администратор может удалять пользователей")
    
    if delete_data.delete_type not in ["soft", "hard"]:
        raise HTTPException(status_code=400, detail="delete_type должен быть 'soft' или 'hard'")
    
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя удалить свой собственный аккаунт")
    
    deleted_at_str = None
    
    if delete_data.delete_type == "soft":
        user.is_deleted = True
        user.deleted_at = get_local_time()
        deleted_at_str = user.deleted_at.isoformat()
        
        if delete_data.reason:
            delete_reason = f"Удалён: {delete_data.reason}"
            if user.admin_comment:
                user.admin_comment = f"{user.admin_comment}\n{delete_reason}"
            else:
                user.admin_comment = delete_reason
        
        db.commit()
        
        log_action(
            db,
            actor_id=current_user.id,
            action="delete_user_soft",
            entity_type="user",
            entity_id=user.id,
            details={"reason": delete_data.reason}
        )
        db.commit()
        message = "Пользователь мягко удалён"
        
        
    else: 
        db.query(Application).filter(Application.user_id == user.id).delete(synchronize_session=False)
        db.query(RentalHistory).filter(RentalHistory.user_id == user.id).delete(synchronize_session=False)
        db.query(WalletTransaction).filter(WalletTransaction.user_id == user.id).delete(synchronize_session=False)
        db.query(Guarantor).filter(Guarantor.client_id == user.id).delete(synchronize_session=False)
        db.query(Guarantor).filter(Guarantor.guarantor_id == user.id).delete(synchronize_session=False)
        db.query(GuarantorRequest).filter(GuarantorRequest.requestor_id == user.id).delete(synchronize_session=False)
        db.query(GuarantorRequest).filter(GuarantorRequest.guarantor_id == user.id).delete(synchronize_session=False)
        db.query(UserDevice).filter(UserDevice.user_id == user.id).delete(synchronize_session=False)
        db.query(UserContractSignature).filter(UserContractSignature.user_id == user.id).delete(synchronize_session=False)
        
        db.delete(user)
        
        log_action(
            db,
            actor_id=current_user.id,
            action="delete_user_hard",
            entity_type="user",
            entity_id=user_uuid,
            details={"reason": delete_data.reason}
        )

        db.commit()
        message = "Пользователь физически удалён из базы данных"
    
    if delete_data.delete_type == "soft":
        try:
            await notify_user_status_update(str(user.id))
        except Exception as e:
            print(f"Error sending WebSocket notification: {e}")
    
    return AdminDeleteUserResponse(
        message=message,
        user_id=user_id,
        delete_type=delete_data.delete_type,
        deleted_at=deleted_at_str
    )


class ResetApplicationsRequest(BaseModel):
    """Запрос на массовый сброс статусов заявок"""
    phone_numbers: List[str] = Field(..., description="Список номеров телефонов")


@users_router.post("/reset-applications", summary="Массовый сброс статусов заявок")
async def reset_applications(
    request: ResetApplicationsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Массовый сброс статусов заявок по номерам телефонов.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Только для администраторов")
    
    results = {
        "success": [],
        "not_found": [],
        "no_application": [],
        "errors": []
    }
    
    for phone in request.phone_numbers:
        try:
            user = db.query(User).filter(User.phone_number == phone).first()
            if not user:
                results["not_found"].append(phone)
                continue
            
            application = db.query(Application).filter(Application.user_id == user.id).first()
            if not application:
                results["no_application"].append(phone)
                continue
            
            application.financier_status = ApplicationStatus.PENDING
            application.mvd_status = ApplicationStatus.PENDING
            
            application.reason = None
            application.financier_rejected_at = None
            application.financier_user_id = None
            application.financier_approved_at = None
            application.mvd_rejected_at = None
            application.mvd_user_id = None
            application.mvd_approved_at = None
            application.updated_at = get_local_time()
            
            user.role = UserRole.PENDINGTOFIRST
            
            results["success"].append(phone)
            
            log_action(
                db,
                actor_id=current_user.id,
                action="bulk_reset_application",
                entity_type="user",
                entity_id=user.id,
                details={"phone_number": phone}
            )
            
        except Exception as e:
            results["errors"].append({"phone": phone, "error": str(e)})
    
    db.commit()
    
    for phone in results["success"]:
        try:
            user = db.query(User).filter(User.phone_number == phone).first()
            if user:
                asyncio.create_task(notify_user_status_update(str(user.id)))
        except:
            pass
    
    return {
        "message": f"Обработано {len(request.phone_numbers)} номеров",
        "success_count": len(results["success"]),
        "not_found_count": len(results["not_found"]),
        "no_application_count": len(results["no_application"]),
        "error_count": len(results["errors"]),
        "details": results
    }

@users_router.get("/action-logs", summary="История действий админов/техподдержки")
async def get_action_logs(
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(50, ge=1, le=500, description="Количество записей на странице"),
    actor_id: Optional[str] = Query(None, description="Фильтр по ID исполнителя (SID)"),
    action: Optional[str] = Query(None, description="Фильтр по типу действия"),
    entity_type: Optional[str] = Query(None, description="Фильтр по типу сущности (user, car, rental и т.д.)"),
    entity_id: Optional[str] = Query(None, description="Фильтр по ID сущности (SID)"),
    date_from: Optional[str] = Query(None, description="Дата начала (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Дата окончания (YYYY-MM-DD)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получить список всех действий админов и техподдержки.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    query = db.query(ActionLog).join(User, User.id == ActionLog.actor_id)
    
    if actor_id:
        actor_uuid = safe_sid_to_uuid(actor_id)
        query = query.filter(ActionLog.actor_id == actor_uuid)
    
    if action:
        query = query.filter(ActionLog.action == action)
    
    if entity_type:
        query = query.filter(ActionLog.entity_type == entity_type)
    
    if entity_id:
        entity_uuid = safe_sid_to_uuid(entity_id)
        query = query.filter(ActionLog.entity_id == entity_uuid)
    
    if date_from:
        try:
            from_date = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(ActionLog.created_at >= from_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат date_from (YYYY-MM-DD)")
    
    if date_to:
        try:
            to_date = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(ActionLog.created_at < to_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат date_to (YYYY-MM-DD)")
    
    total = query.count()
    offset = (page - 1) * limit
    logs = query.order_by(ActionLog.created_at.desc()).offset(offset).limit(limit).all()
    
    items = []
    for log in logs:
        actor = log.actor
        items.append({
            "id": uuid_to_sid(log.id),
            "actor": {
                "id": uuid_to_sid(actor.id) if actor else None,
                "first_name": actor.first_name if actor else None,
                "last_name": actor.last_name if actor else None,
                "middle_name": actor.middle_name if actor else None,
                "phone_number": actor.phone_number if actor else None,
                "role": actor.role.value if actor and actor.role else None,
                "selfie_url": actor.selfie_url if actor else None
            },
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": uuid_to_sid(log.entity_id) if log.entity_id else None,
            "details": log.details,
            "created_at": log.created_at.isoformat() if log.created_at else None
        })
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": ceil(total / limit) if limit > 0 else 0
    }
