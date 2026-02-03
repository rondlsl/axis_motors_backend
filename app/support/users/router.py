"""Support users — список, бронирование и отмена аренды (тот же контракт, что /admin/users)."""
import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Form
from sqlalchemy.orm import Session

from app.dependencies.database.database import get_db
from app.admin.users.router import get_users_list_impl
from app.admin.users.schemas import (
    UserPaginatedResponse,
    AdminCancelReservationRequest,
    AdminCancelReservationResponse,
)
from app.support.deps import require_support_role
from app.utils.short_id import safe_sid_to_uuid, uuid_to_sid
from app.models.user_model import User
from app.models.history_model import RentalHistory, RentalStatus, RentalType
from app.models.car_model import Car, CarStatus
from app.rent.utils.calculate_price import get_open_price, calc_required_balance
from app.utils.time_utils import get_local_time
from app.websocket.notifications import notify_user_status_update

logger = logging.getLogger(__name__)
users_router = APIRouter(tags=["Support users"])


@users_router.get("/list", response_model=UserPaginatedResponse)
async def get_support_users_list(
    role: Optional[str] = Query(None, description="Фильтр по роли"),
    search_query: Optional[str] = Query(None, description="Поиск по имени, фамилии, телефону, ИИН или паспорту"),
    has_active_rental: Optional[bool] = Query(None, description="Фильтр по активной аренде"),
    is_blocked: Optional[bool] = Query(None, description="Фильтр по заблокированным пользователям"),
    mvd_approved: Optional[bool] = Query(None, description="Фильтр по МВД одобрению"),
    car_status: Optional[str] = Query(None, description="Фильтр по статусу авто"),
    auto_class: Optional[List[str]] = Query(None, description="Фильтр по классу авто (A, B, C, AB, ABC)"),
    balance_filter: Optional[str] = Query(None, description="Фильтр по балансу (positive / negative)"),
    documents_verified: Optional[bool] = Query(None, description="Фильтр по проверке документов"),
    is_active: Optional[bool] = Query(None, description="Фильтр по активности пользователя"),
    is_verified_email: Optional[bool] = Query(None, description="Фильтр по подтверждению email"),
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(50, ge=1, le=200, description="Количество элементов на странице"),
    current_user=Depends(require_support_role),
    db: Session = Depends(get_db),
) -> UserPaginatedResponse:
    """Список пользователей с фильтрацией и поиском (тот же endpoint, что /admin/users/list)."""
    return get_users_list_impl(
        db,
        role=role,
        search_query=search_query,
        has_active_rental=has_active_rental,
        is_blocked=is_blocked,
        mvd_approved=mvd_approved,
        car_status=car_status,
        auto_class=auto_class,
        balance_filter=balance_filter,
        documents_verified=documents_verified,
        is_active=is_active,
        is_verified_email=is_verified_email,
        page=page,
        limit=limit,
    )


@users_router.post("/trips/reserve", summary="Забронировать машину за клиента (Support)")
async def support_reserve_car(
    car_id: str = Form(..., description="ID машины"),
    user_id: str = Form(..., description="ID пользователя"),
    rental_type: str = Form(..., description="Тип аренды: MINUTES, HOURS, DAYS"),
    duration: Optional[str] = Form(None, description="Длительность (для HOURS/DAYS)"),
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """
    Эндпоинт для support для бронирования машины за клиента.
    Точная копия POST /admin/users/trips/reserve.

    - Создает аренду со статусом RESERVED
    - Проверяет минимальный баланс клиента
    - Обновляет статус машины на RESERVED
    """
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


@users_router.post("/rentals/cancel", response_model=AdminCancelReservationResponse)
async def support_cancel_reservation(
    request: AdminCancelReservationRequest,
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
) -> AdminCancelReservationResponse:
    """
    Отменить бронь/аренду клиента от имени support.
    Точная копия POST /admin/users/rentals/cancel.

    - rental_id: ID аренды
    - Работает для статусов: RESERVED, DELIVERING, DELIVERY_RESERVED, DELIVERING_IN_PROGRESS, SCHEDULED, IN_USE
    """
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
        logger.error(f"Error sending WebSocket notifications: {e}")

    return AdminCancelReservationResponse(
        message="Бронь отменена",
        rental_id=request.rental_id,
        car_name=car.name,
        plate_number=car.plate_number,
        previous_status=previous_status,
        client_id=client_id
    )
