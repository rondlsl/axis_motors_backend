from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import uuid

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.application_model import Application, ApplicationStatus
from app.models.history_model import RentalHistory, RentalStatus
from app.models.car_model import Car
from app.models.guarantor_model import GuarantorRequest
from app.admin.users.schemas import (
    UserProfileSchema, UserRoleUpdateSchema, UserCardSchema, 
    UserListSchema, UserMapPositionSchema, UserCommentUpdateSchema,
    UserSearchFiltersSchema, GuarantorInfoSchema, TripSummarySchema,
    TripListItemSchema, TripDetailSchema, OwnerCarListItemSchema,
    UserEditSchema, UserBlockSchema
)
from app.owner.router import calculate_owner_earnings

users_router = APIRouter(tags=["Admin Users"])


@users_router.get("/pending", response_model=List[UserProfileSchema])
async def get_pending_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение пользователей, ожидающих одобрения"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    # Получаем пользователей с ролью PENDING
    users = db.query(User).filter(User.role == UserRole.PENDING).all()
    
    result = []
    for user in users:
        result.append(UserProfileSchema(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            phone_number=user.phone_number,
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
            auto_class=user.auto_class or []
        ))
    
    return result


@users_router.post("/{user_id}/approve")
async def approve_or_reject_user(
    user_id: uuid.UUID,
    approved: bool,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Одобрение или отклонение пользователя"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    if approved:
        user.role = UserRole.CLIENT
        user.documents_verified = True
        
        # Создаем заявку для одобренного пользователя
        application = Application(
            user_id=user.id,
            status=ApplicationStatus.APPROVED,
            created_at=datetime.utcnow()
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
        result.append(UserProfileSchema(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            phone_number=user.phone_number,
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
            auto_class=user.auto_class or []
        ))
    
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
        result.append(UserProfileSchema(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            phone_number=user.phone_number,
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
            auto_class=user.auto_class or []
        ))
    
    return result


@users_router.patch("/{user_id}/role")
async def update_employee_role(
    user_id: uuid.UUID,
    role_data: UserRoleUpdateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Обновление роли сотрудника"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    user.role = role_data.role
    db.commit()
    
    return {"message": f"Роль пользователя изменена на {role_data.role.value}"}


# === User Profile ===
@users_router.get("/{user_id}/profile", response_model=UserProfileSchema)
async def get_user_profile(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> UserProfileSchema:
    """Получить профиль пользователя"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

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

    return UserProfileSchema(
        id=user.id,
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
    )


def _get_mvd_approved_status(user: User, db: Session) -> bool:
    """Определяет, одобрен ли пользователь МВД"""
    # Если роль USER - точно одобрен
    if user.role == UserRole.USER:
        return True
    
    # Проверяем через Application
    application = db.query(Application).filter(Application.user_id == user.id).first()
    if application and application.mvd_status == ApplicationStatus.APPROVED:
        return True
    
    return False


def _get_current_rental_car(user: User, db: Session) -> Optional[Dict[str, Any]]:
    """Получает информацию о текущей аренде пользователя"""
    # Ищем активную аренду
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
        "id": car.id,
        "name": car.name,
        "plate_number": car.plate_number,
        "brand": car.name.split()[0] if car.name else "Unknown"
    }


def _calculate_owner_earnings(user: User, db: Session) -> Dict[str, float]:
    """Рассчитывает заработок владельца"""
    if user.role not in [UserRole.USER]:  # Только для одобренных пользователей
        return {"current_month": 0.0, "total": 0.0}
    
    # Получаем автомобили владельца
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


@users_router.get("/list", response_model=List[UserListSchema])
async def get_users_list(
    role: Optional[str] = Query(None, description="Фильтр по роли"),
    search_query: Optional[str] = Query(None, description="Поиск по имени, фамилии, телефону, ИИН или паспорту"),
    has_active_rental: Optional[bool] = Query(None, description="Фильтр по активной аренде"),
    is_blocked: Optional[bool] = Query(None, description="Фильтр по заблокированным пользователям"),
    mvd_approved: Optional[bool] = Query(None, description="Фильтр по МВД одобрению"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
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
        
        result.append(UserListSchema(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            phone_number=user.phone_number,
            iin=user.iin,
            passport_number=user.passport_number,
            role=user.role.value,
            auto_class=auto_class_list,
            selfie_url=user.selfie_url,
            is_blocked=not user.is_active,
            current_rental_car=current_car
        ))
    
    # Сортировка: сначала с активной арендой, потом без
    result.sort(key=lambda x: x.current_rental_car is None)
    
    return result


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
        
        result.append(UserMapPositionSchema(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            selfie_url=user.selfie_url,
            last_rental_end_latitude=float(last_rental.end_latitude),
            last_rental_end_longitude=float(last_rental.end_longitude),
            last_activity_at=last_rental.end_time,
            is_active_rental=current_car is not None
        ))
    
    return result


@users_router.get("/{user_id}/card", response_model=UserCardSchema)
async def get_user_card(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение полной карточки пользователя"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user = db.query(User).filter(User.id == user_id).first()
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
    
    return UserCardSchema(
        id=user.id,
        phone_number=user.phone_number,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        iin=user.iin,
        passport_number=user.passport_number,
        birth_date=user.birth_date,
        drivers_license_expiry=user.drivers_license_expiry,
        id_card_expiry=user.id_card_expiry,
        locale=user.locale,
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
        wallet_balance=float(user.wallet_balance) if user.wallet_balance else 0.0,
        created_at=user.created_at,
        last_activity_at=user.last_activity_at,
        mvd_approved=mvd_approved,
        is_blocked=not user.is_active,
        admin_comment=user.admin_comment,
        current_rental_car=current_car,
        owner_earnings_current_month=owner_earnings["current_month"] if owner_earnings else None,
        owner_earnings_total=owner_earnings["total"] if owner_earnings else None
    )


@users_router.patch("/{user_id}/comment")
async def update_user_comment(
    user_id: uuid.UUID,
    comment_data: UserCommentUpdateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Обновление комментария пользователя"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Обновляем комментарий
    user.admin_comment = comment_data.admin_comment
    db.commit()
    
    return {"message": "Комментарий обновлен", "admin_comment": comment_data.admin_comment}


@users_router.get("/{user_id}/guarantors/he-is-guarantor", response_model=List[GuarantorInfoSchema])
async def get_users_he_is_guarantor_for(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка пользователей, для которых текущий пользователь является гарантом"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Получаем клиентов, для которых этот пользователь является гарантом
    from app.models.guarantor_model import Guarantor
    guarantor_relations = db.query(Guarantor).filter(
        and_(
            Guarantor.guarantor_id == user_id,
            Guarantor.is_active == True
        )
    ).all()
    
    result = []
    for relation in guarantor_relations:
        client = db.query(User).filter(User.id == relation.client_id).first()
        if client:
            result.append(GuarantorInfoSchema(
                id=client.id,
                first_name=client.first_name,
                last_name=client.last_name,
                phone_number=client.phone_number,
                iin=client.iin,
                passport_number=client.passport_number,
                selfie_url=client.selfie_url
            ))
    
    return result


@users_router.get("/{user_id}/guarantors/his-guarantors", response_model=List[GuarantorInfoSchema])
async def get_his_guarantors(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка гарантов текущего пользователя"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Получаем гарантов этого пользователя
    from app.models.guarantor_model import Guarantor
    guarantor_relations = db.query(Guarantor).filter(
        and_(
            Guarantor.client_id == user_id,
            Guarantor.is_active == True
        )
    ).all()
    
    result = []
    for relation in guarantor_relations:
        guarantor = db.query(User).filter(User.id == relation.guarantor_id).first()
        if guarantor:
            result.append(GuarantorInfoSchema(
                id=guarantor.id,
                first_name=guarantor.first_name,
                last_name=guarantor.last_name,
                phone_number=guarantor.phone_number,
                iin=guarantor.iin,
                passport_number=guarantor.passport_number,
                selfie_url=guarantor.selfie_url
            ))
    
    return result


@users_router.get("/{user_id}/trips/summary", response_model=TripSummarySchema)
async def get_user_trips_summary(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение сводки по поездкам пользователя"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Получаем все завершенные поездки пользователя
    completed_trips = db.query(RentalHistory).filter(
        and_(
            RentalHistory.user_id == user_id,
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
    user_id: uuid.UUID,
    month: Optional[int] = Query(None, description="Месяц (1-12). Если не указан, возвращается текущий месяц"),
    year: Optional[int] = Query(None, description="Год. Если не указан, возвращается текущий год"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка поездок пользователя с фильтром по месяцам"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user = db.query(User).filter(User.id == user_id).first()
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
            RentalHistory.user_id == user_id,
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
            id=trip.id,
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
    user_id: uuid.UUID,
    trip_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение детальной информации о поездке"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Получаем поездку
    trip = db.query(RentalHistory).filter(
        and_(
            RentalHistory.id == trip_id,
            RentalHistory.user_id == user_id
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
        id=trip.id,
        rental_type=trip.rental_type.value,
        start_date=trip.start_time,
        end_date=trip.end_time,
        duration_minutes=duration_minutes,
        total_price=float(trip.total_price or 0),
        car_id=car.id,
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
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка автомобилей владельца"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Получаем автомобили владельца
    cars = db.query(Car).filter(Car.owner_id == user_id).all()
    
    result = []
    now = datetime.now()
    current_month_start = datetime(now.year, now.month, 1)
    
    for car in cars:
        # Рассчитываем доступные минуты для текущего месяца
        available_minutes = _calculate_month_availability_minutes(
            car_id=car.id,
            year=now.year,
            month=now.month,
            owner_id=user_id,
            db=db
        )
        
        # Рассчитываем заработок
        earnings_data = _calculate_car_earnings(car.id, user_id, db, current_month_start)
        
        result.append(OwnerCarListItemSchema(
            id=car.id,
            name=car.name,
            plate_number=car.plate_number,
            available_minutes=available_minutes,
            earnings_current_month=earnings_data["current_month"],
            earnings_total=earnings_data["total"],
            photos=car.photos if car.photos else []
        ))
    
    return result


@users_router.patch("/{user_id}/edit")
async def edit_user(
    user_id: uuid.UUID,
    edit_data: UserEditSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Редактирование пользователя (смена класса допуска и роли)"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Обновляем класс допуска
    if edit_data.auto_class is not None:
        user.auto_class = edit_data.auto_class
    
    # Обновляем роль
    if edit_data.role is not None:
        user.role = edit_data.role
    
    db.commit()
    
    return {"message": "Пользователь обновлен"}


@users_router.patch("/{user_id}/block")
async def block_user(
    user_id: uuid.UUID,
    block_data: UserBlockSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Блокировка/разблокировка пользователя по ИИН/паспорту"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user = db.query(User).filter(User.id == user_id).first()
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
    
    action = "заблокирован" if block_data.is_blocked else "разблокирован"
    return {"message": f"Пользователь {action}"}


def _calculate_month_availability_minutes(
    car_id: int,
    year: int,
    month: int,
    owner_id: uuid.UUID,
    db: Session
) -> int:
    """Рассчитывает доступные минуты для автомобиля в месяце"""
    # Импортируем функцию из owner.utils
    from app.owner.utils import calculate_month_availability_minutes
    return calculate_month_availability_minutes(car_id, year, month, owner_id, db)


def _calculate_car_earnings(car_id: int, owner_id: uuid.UUID, db: Session, month_start: datetime) -> Dict[str, float]:
    """Рассчитывает заработок с автомобиля"""
    # Получаем поездки клиентов (исключаем поездки самого владельца)
    client_rentals = db.query(RentalHistory).filter(
        and_(
            RentalHistory.car_id == car_id,
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