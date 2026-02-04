from fastapi import APIRouter, Depends, HTTPException, Query
from math import ceil, floor
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import List
from datetime import datetime
from collections import defaultdict

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_support
from app.models.user_model import User
from app.models.history_model import RentalHistory, RentalStatus, RentalReview
from app.models.car_model import CarStatus
from app.models.car_comment_model import CarComment
from app.models.support_action_model import SupportAction
from app.utils.short_id import safe_sid_to_uuid, uuid_to_sid
from app.utils.time_utils import get_local_time
from app.admin.cars.schemas import (
    CarDetailSchema,
    CarAvailabilityTimerSchema,
    CarCommentSchema,
    CarCommentCreateSchema,
    CarCommentUpdateSchema,
    DescriptionUpdateSchema,
)
from app.admin.cars.router import (
    get_car_by_id,
    get_car_details_response,
    change_car_status_impl,
    toggle_car_notifications_impl,
)
from app.models.car_model import CarAvailabilityHistory, CarStatus, CarBodyType
from app.owner.availability import update_car_availability_snapshot
from app.owner.router import calculate_fuel_cost, calculate_delivery_cost
from app.gps_api.utils.auth_api import get_auth_token
from app.gps_api.utils.route_data import get_gps_route_data
from app.gps_api.utils.car_data import (
    send_open,
    send_close,
    send_lock_engine,
    send_unlock_engine,
    send_give_key,
    send_take_key,
)
from app.core.config import GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD
from app.utils.action_logger import log_action
from app.models.contract_model import UserContractSignature, ContractFile, ContractType
from app.utils.telegram_logger import log_error_to_telegram

BASE_URL = "https://regions.glonasssoft.ru"

support_cars_router = APIRouter(tags=["Support Cars"])


@support_cars_router.get("/{car_id}/details", response_model=CarDetailSchema)
async def get_car_details_support(
    car_id: str,
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
) -> CarDetailSchema:
    """Получить детальную информацию об автомобиле (для роли SUPPORT)."""
    return await get_car_details_response(car_id, db)


@support_cars_router.get("/{car_id}/availability-timer", response_model=CarAvailabilityTimerSchema)
async def get_car_availability_timer_support(
    car_id: str,
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
) -> CarAvailabilityTimerSchema:
    """Получить таймер доступности автомобиля (для роли SUPPORT)."""
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    available_minutes = car.available_minutes or 0

    last_rental = (
        db.query(RentalHistory)
        .filter(
            RentalHistory.car_id == car.id,
            RentalHistory.rental_status == RentalStatus.COMPLETED,
            RentalHistory.end_time.isnot(None),
        )
        .order_by(RentalHistory.end_time.desc())
        .first()
    )

    return CarAvailabilityTimerSchema(
        car_id=uuid_to_sid(car.id),
        available_minutes=available_minutes,
        last_rental_end=last_rental.end_time.isoformat() if last_rental else None,
        current_status=car.status.value if car.status else "FREE",
    )


@support_cars_router.post("/{car_id}/toggle-exit-zone")
async def toggle_car_exit_zone_support(
    car_id: str,
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
):
    """
    Включить/выключить разрешение на выезд за зону карты для машины (для роли SUPPORT).
    """
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

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
            "plate_number": car.plate_number,
        },
    )

    status_text = "разрешён" if new_value else "запрещён"
    return {
        "success": True,
        "car_id": uuid_to_sid(car.id),
        "can_exit_zone": new_value,
        "message": f"Выезд за зону для {car.name} ({car.plate_number}) {status_text}",
    }


@support_cars_router.patch("/{car_id}/status", summary="Изменить статус автомобиля")
async def change_car_status_support(
    car_id: str,
    new_status: CarStatus = Query(..., alias="new_status"),
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
):
    """Изменить статус автомобиля (для роли SUPPORT)."""
    return await change_car_status_impl(car_id, new_status, db, current_user)


@support_cars_router.post("/{car_id}/toggle-notifications", summary="Включить/выключить уведомления")
async def toggle_car_notifications_support(
    car_id: str,
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
):
    """Включить/выключить уведомления для машины (для роли SUPPORT)."""
    return await toggle_car_notifications_impl(car_id, db, current_user)


@support_cars_router.patch("/{car_id}/description", summary="Изменить описание автомобиля")
async def update_car_description_support(
    car_id: str,
    body: DescriptionUpdateSchema,
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
):
    """Изменить описание автомобиля (для роли SUPPORT)."""
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    car.description = body.description
    db.commit()
    db.refresh(car)
    log_action(db=db, actor_id=current_user.id, action="update_car_description", entity_type="car",
               entity_id=car.id, details={"car_name": car.name, "plate_number": car.plate_number})
    return {"success": True, "car_id": uuid_to_sid(car.id), "description": car.description}


def _comment_to_schema(comment: CarComment, db: Session) -> CarCommentSchema:
    """Преобразовать CarComment в CarCommentSchema."""
    author = comment.author
    author_name = f"{author.first_name or ''} {author.last_name or ''} {author.middle_name or ''}".strip() or author.phone_number
    return CarCommentSchema(
        id=comment.sid,
        car_id=uuid_to_sid(comment.car_id),
        author_id=str(comment.author_id),
        author_name=author_name,
        author_role=author.role.value,
        comment=comment.comment,
        created_at=comment.created_at.isoformat(),
        is_internal=comment.is_internal,
    )


@support_cars_router.get("/{car_id}/comments", response_model=List[CarCommentSchema])
async def get_car_comments_support(
    car_id: str,
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
) -> List[CarCommentSchema]:
    """Получить комментарии к автомобилю (для роли SUPPORT)."""
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    comments = (
        db.query(CarComment)
        .filter(CarComment.car_id == car.id)
        .order_by(CarComment.created_at.desc())
        .all()
    )
    return [_comment_to_schema(c, db) for c in comments]


@support_cars_router.post("/{car_id}/comments", response_model=CarCommentSchema)
async def create_car_comment_support(
    car_id: str,
    comment_data: CarCommentCreateSchema,
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
) -> CarCommentSchema:
    """Добавить комментарий к автомобилю (для роли SUPPORT)."""
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    comment = CarComment(
        car_id=car.id,
        author_id=current_user.id,
        comment=comment_data.comment,
        is_internal=comment_data.is_internal,
    )
    db.add(comment)
    log_action(db, actor_id=current_user.id, action="add_car_comment", entity_type="car_comment",
               entity_id=comment.id, details={"car_id": car_id, "comment": comment.comment})
    db.commit()
    db.refresh(comment)
    sa = SupportAction(user_id=current_user.id, action="create_car_comment", entity_type="car_comment", entity_id=comment.id)
    db.add(sa)
    db.commit()
    return _comment_to_schema(comment, db)


@support_cars_router.put("/{car_id}/comments/{comment_id}", response_model=CarCommentSchema)
async def update_car_comment_support(
    car_id: str,
    comment_id: str,
    comment_data: CarCommentUpdateSchema,
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
) -> CarCommentSchema:
    """Обновить комментарий к автомобилю (для роли SUPPORT)."""
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    comment_uuid = safe_sid_to_uuid(comment_id)
    comment = db.query(CarComment).filter(
        CarComment.id == comment_uuid,
        CarComment.car_id == car.id,
        CarComment.author_id == current_user.id,
    ).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Комментарий не найден")
    comment.comment = comment_data.comment
    comment.updated_at = get_local_time()
    db.commit()
    log_action(db, actor_id=current_user.id, action="update_car_comment", entity_type="car_comment",
               entity_id=comment.id, details={"car_id": car_id, "new_comment": comment.comment})
    sa = SupportAction(user_id=current_user.id, action="update_car_comment", entity_type="car_comment", entity_id=comment.id)
    db.add(sa)
    db.commit()
    db.refresh(comment)
    return _comment_to_schema(comment, db)


@support_cars_router.delete("/{car_id}/comments/{comment_id}")
async def delete_car_comment_support(
    car_id: str,
    comment_id: str,
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
):
    """Удалить комментарий к автомобилю (для роли SUPPORT)."""
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    comment_uuid = safe_sid_to_uuid(comment_id)
    comment = db.query(CarComment).filter(
        CarComment.id == comment_uuid,
        CarComment.car_id == car.id,
        CarComment.author_id == current_user.id,
    ).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Комментарий не найден")
    db.delete(comment)
    log_action(db, actor_id=current_user.id, action="delete_car_comment", entity_type="car_comment",
               entity_id=comment_uuid, details={"car_id": car_id})
    db.commit()
    sa = SupportAction(user_id=current_user.id, action="delete_car_comment", entity_type="car_comment", entity_id=comment_uuid)
    db.add(sa)
    db.commit()
    return {"message": "Комментарий удален"}


async def _send_gps_command(car_id: str, db: Session, current_user: User, send_fn, log_action_name: str):
    """Общая логика отправки GPS-команды (open, close, unlock_engine, give_key)."""
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    if not car.gps_imei:
        raise HTTPException(status_code=400, detail="У автомобиля не настроен GPS IMEI")
    auth_token = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
    if not auth_token:
        raise HTTPException(status_code=500, detail="Не удалось получить токен авторизации GPS")
    result = await send_fn(car.gps_imei, auth_token)
    log_action(db, actor_id=current_user.id, action=log_action_name, entity_type="car", entity_id=car.id,
               details={"gps_imei": car.gps_imei, "command_id": result.get("command_id")})
    db.commit()
    return {"car_id": uuid_to_sid(car.id), "car_name": car.name, "command_id": result.get("command_id")}


@support_cars_router.post("/{car_id}/open", summary="Открыть автомобиль")
async def support_open_vehicle(
    car_id: str,
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
):
    """Открыть автомобиль (разблокировать двери) для SUPPORT."""
    try:
        result = await _send_gps_command(car_id, db, current_user, send_open, "open_vehicle")
        return {"message": "Команда на открытие отправлена", **result}
    except HTTPException:
        raise
    except Exception as e:
        car = get_car_by_id(db, car_id)
        await log_error_to_telegram(error=e, request=None, user=current_user,
                                   additional_context={"action": "support_open_vehicle", "car_id": car_id,
                                                       "gps_imei": car.gps_imei if car else None})
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")


@support_cars_router.post("/{car_id}/close", summary="Закрыть автомобиль")
async def support_close_vehicle(
    car_id: str,
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
):
    """Закрыть автомобиль (заблокировать двери) для SUPPORT."""
    try:
        result = await _send_gps_command(car_id, db, current_user, send_close, "close_vehicle")
        return {"message": "Команда на закрытие отправлена", **result}
    except HTTPException:
        raise
    except Exception as e:
        car = get_car_by_id(db, car_id)
        await log_error_to_telegram(error=e, request=None, user=current_user,
                                   additional_context={"action": "support_close_vehicle", "car_id": car_id,
                                                       "gps_imei": car.gps_imei if car else None})
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")


@support_cars_router.post("/{car_id}/lock_engine", summary="Заблокировать двигатель")
async def support_lock_engine(
    car_id: str,
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
):
    """Заблокировать двигатель для SUPPORT."""
    try:
        car = get_car_by_id(db, car_id)
        if not car:
            raise HTTPException(status_code=404, detail="Автомобиль не найден")
        if not car.gps_imei:
            raise HTTPException(status_code=400, detail="У автомобиля не настроен GPS IMEI")
        auth_token = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        if not auth_token:
            raise HTTPException(status_code=500, detail="Не удалось получить токен авторизации GPS")
        result = await send_lock_engine(car.gps_imei, auth_token)
        log_action(db, actor_id=current_user.id, action="lock_engine", entity_type="car", entity_id=car.id,
                   details={"gps_imei": car.gps_imei, "command_id": result.get("command_id"), "skipped": False})
        db.commit()
        if result.get("skipped"):
            return {"message": "Блокировка двигателя отключена для этого автомобиля", "car_id": uuid_to_sid(car.id),
                    "car_name": car.name, "skipped": True, "reason": result.get("reason")}
        return {"message": "Команда на блокировку двигателя отправлена", "car_id": uuid_to_sid(car.id),
                "car_name": car.name, "command_id": result.get("command_id")}
    except HTTPException:
        raise
    except Exception as e:
        car = get_car_by_id(db, car_id)
        await log_error_to_telegram(error=e, request=None, user=current_user,
                                   additional_context={"action": "support_lock_engine", "car_id": car_id,
                                                       "gps_imei": car.gps_imei if car else None})
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")


@support_cars_router.post("/{car_id}/unlock_engine", summary="Разблокировать двигатель")
async def support_unlock_engine(
    car_id: str,
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
):
    """Разблокировать двигатель для SUPPORT."""
    try:
        result = await _send_gps_command(car_id, db, current_user, send_unlock_engine, "unlock_engine")
        return {"message": "Команда на разблокировку двигателя отправлена", **result}
    except HTTPException:
        raise
    except Exception as e:
        car = get_car_by_id(db, car_id)
        await log_error_to_telegram(error=e, request=None, user=current_user,
                                   additional_context={"action": "support_unlock_engine", "car_id": car_id,
                                                       "gps_imei": car.gps_imei if car else None})
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")


@support_cars_router.post("/{car_id}/give_key", summary="Выдать ключ")
async def support_give_key(
    car_id: str,
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
):
    """Выдать ключ автомобиля для SUPPORT."""
    try:
        result = await _send_gps_command(car_id, db, current_user, send_give_key, "give_key")
        return {"message": "Команда на выдачу ключа отправлена", **result}
    except HTTPException:
        raise
    except Exception as e:
        car = get_car_by_id(db, car_id)
        await log_error_to_telegram(error=e, request=None, user=current_user,
                                   additional_context={"action": "support_give_key", "car_id": car_id,
                                                       "gps_imei": car.gps_imei if car else None})
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")


@support_cars_router.post("/{car_id}/take_key", summary="Забрать ключ")
async def support_take_key(
    car_id: str,
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
):
    """Забрать ключ автомобиля для SUPPORT."""
    try:
        result = await _send_gps_command(car_id, db, current_user, send_take_key, "take_key")
        return {"message": "Команда на забор ключа отправлена", **result}
    except HTTPException:
        raise
    except Exception as e:
        car = get_car_by_id(db, car_id)
        await log_error_to_telegram(error=e, request=None, user=current_user,
                                   additional_context={"action": "support_take_key", "car_id": car_id,
                                                       "gps_imei": car.gps_imei if car else None})
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {e}")


@support_cars_router.get("/{car_id}/history/summary")
async def get_car_history_summary_support(
    car_id: str,
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(12, ge=1, le=60, description="Количество месяцев на странице"),
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
):
    """
    Агрегированные данные по месяцам для автомобиля (для SUPPORT).
    Возвращает информацию по всем месяцам, в которых были поездки (все статусы).
    """
    from calendar import monthrange

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    rentals = db.query(RentalHistory).filter(RentalHistory.car_id == car.id).all()

    monthly_data = defaultdict(lambda: {
        "total_income": 0,
        "owner_earnings": 0,
        "deductions": 0.0,
        "trips_count": 0,
        "_trip_details": [],
    })

    for r in rentals:
        date_for_grouping = r.end_time or r.start_time or r.reservation_time
        if not date_for_grouping:
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
        owner_income = data["owner_earnings"] - int(data["deductions"])

        months_result.append({
            "year": year,
            "month": month,
            "available_minutes": availability_by_month.get((year, month), 0),
            "total_income": data["total_income"],
            "owner_income": owner_income,
            "trips_count": data["trips_count"],
            "is_current_month": (year, month) == current_month_key,
        })

    return {
        "car_id": uuid_to_sid(car.id),
        "car_name": car.name,
        "plate_number": car.plate_number,
        "current_month": {"year": now.year, "month": now.month},
        "months": months_result,
        "total": total_months,
        "page": page,
        "limit": limit,
        "pages": ceil(total_months / limit) if limit > 0 else 0,
    }


@support_cars_router.get("/{car_id}/history/trips")
async def get_car_trips_list_support(
    car_id: str,
    month: int = Query(..., ge=1, le=12, description="Месяц (1-12)"),
    year: int = Query(..., description="Год"),
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(50, ge=1, le=200, description="Количество элементов на странице"),
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
):
    """Список поездок автомобиля за выбранный месяц с пагинацией (для SUPPORT)"""
    from calendar import monthrange

    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    start_dt = datetime(year, month, 1)
    end_dt = datetime(year, month, monthrange(year, month)[1], 23, 59, 59)

    base_query = (
        db.query(RentalHistory, User)
        .outerjoin(User, User.id == RentalHistory.user_id)
        .filter(
            RentalHistory.car_id == car.id,
            or_(
                and_(RentalHistory.reservation_time >= start_dt, RentalHistory.reservation_time <= end_dt),
                and_(RentalHistory.start_time >= start_dt, RentalHistory.start_time <= end_dt),
                and_(RentalHistory.end_time >= start_dt, RentalHistory.end_time <= end_dt),
            ),
        )
        .order_by(RentalHistory.reservation_time.desc())
    )

    total = base_query.count()
    rentals = base_query.offset((page - 1) * limit).limit(limit).all()

    def get_status_display(status, has_inspection=True, is_mechanic_inspecting=False, inspection_status=None):
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
            tariff_value = r.rental_type.value if hasattr(r.rental_type, "value") else str(r.rental_type)
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
            r.mechanic_inspection_status == "COMPLETED"
            or r.mechanic_inspector_id is not None
            or (r.mechanic_photos_after and len(r.mechanic_photos_after) > 0)
        )

        is_mechanic_inspecting = (
            car.status == CarStatus.SERVICE
            and r.mechanic_inspector_id is not None
            and r.mechanic_inspection_status is not None
            and r.mechanic_inspection_status != "COMPLETED"
            and r.mechanic_inspection_status != "CANCELLED"
        )

        if r.mechanic_inspection_status == "IN_USE":
            display_rental_status = "in_progress"
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
            } if renter else None,
        })

    return {
        "trips": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": ceil(total / limit) if limit > 0 else 0,
    }


@support_cars_router.get("/{car_id}/history/trips/{rental_id}")
async def get_trip_detail_support(
    car_id: str,
    rental_id: str,
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
):
    """Детальная информация о поездке (для SUPPORT)"""
    from app.rent.utils.calculate_price import FUEL_PRICE_PER_LITER, ELECTRIC_FUEL_PRICE_PER_LITER

    rental_uuid = safe_sid_to_uuid(rental_id)
    car = get_car_by_id(db, car_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid, RentalHistory.car_id == car.id).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Поездка не найдена")
    renter = db.query(User).filter(User.id == rental.user_id).first()

    photos = {
        "client_before": rental.photos_before or [],
        "client_after": rental.photos_after or [],
        "mechanic_before": rental.mechanic_photos_before or [],
        "mechanic_after": rental.mechanic_photos_after or [],
    }

    review = db.query(RentalReview).filter(RentalReview.rental_id == rental.id).first()

    fuel_fee = 0
    if rental.fuel_before is not None and rental.fuel_after is not None and rental.fuel_after < rental.fuel_before:
        fuel_consumed = ceil(rental.fuel_before) - floor(rental.fuel_after)
        if fuel_consumed > 0:
            fuel_price = ELECTRIC_FUEL_PRICE_PER_LITER if car.body_type == CarBodyType.ELECTRIC else FUEL_PRICE_PER_LITER
            fuel_fee = int(fuel_consumed * fuel_price)

    total_price_without_fuel = (
        (rental.base_price or 0)
        + (rental.open_fee or 0)
        + (rental.delivery_fee or 0)
        + (rental.waiting_fee or 0)
        + (rental.overtime_fee or 0)
        + (rental.distance_fee or 0)
    )

    tariff_display = ""
    if rental.rental_type:
        tariff_value = rental.rental_type.value if hasattr(rental.rental_type, "value") else str(rental.rental_type)
        if tariff_value == "minutes":
            tariff_display = "Минутный"
        elif tariff_value == "hours":
            tariff_display = "Часовой"
        elif tariff_value == "days":
            tariff_display = "Суточный"
        else:
            tariff_display = tariff_value

    has_inspection = (
        rental.mechanic_inspection_status == "COMPLETED"
        or rental.mechanic_inspector_id is not None
        or (rental.mechanic_photos_after and len(rental.mechanic_photos_after) > 0)
    )

    rental_status_value = rental.rental_status.value if rental.rental_status else None

    is_mechanic_inspecting = (
        car.status == CarStatus.SERVICE
        and rental.mechanic_inspector_id is not None
        and rental.mechanic_inspection_status is not None
        and rental.mechanic_inspection_status != "COMPLETED"
        and rental.mechanic_inspection_status != "CANCELLED"
    )

    if rental.mechanic_inspector_id is not None:
        display_rental_status = "service"
    elif rental.mechanic_inspection_status == "IN_USE":
        display_rental_status = "in_progress"
    elif is_mechanic_inspecting:
        display_rental_status = "in_progress"
    else:
        display_rental_status = rental_status_value if has_inspection or rental_status_value != "completed" else "pending"

    result = {
        "rental_id": uuid_to_sid(rental.id),
        "car_name": car.name,
        "plate_number": car.plate_number,
        "car_status": car.status.value if car.status else None,
        "reservation_time": rental.reservation_time.isoformat() if rental.reservation_time else None,
        "start_time": rental.start_time.isoformat() if rental.start_time else None,
        "end_time": rental.end_time.isoformat() if rental.end_time else None,
        "duration": rental.duration,
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
        "rental_type": rental.rental_type.value if rental.rental_type else None,
        "tariff": rental.rental_type.value if rental.rental_type else None,
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
        } if renter else None,
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
        rental.delivery_start_time is not None
        or rental.delivery_end_time is not None
        or rental.delivery_mechanic_id is not None
        or (rental.delivery_photos_before and len(rental.delivery_photos_before) > 0)
        or (rental.delivery_photos_after and len(rental.delivery_photos_after) > 0)
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
            UserContractSignature.user_id == rental.mechanic_inspector_id,
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


@support_cars_router.get("/{car_id}/history/trips/{rental_id}/get_maps")
async def get_trip_maps_support(
    car_id: str,
    rental_id: str,
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
):
    """Получение координат маршрута поездки для отображения на карте (Support). Аналог GET /admin/cars/.../get_maps."""
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
