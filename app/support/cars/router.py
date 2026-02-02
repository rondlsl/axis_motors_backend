from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from typing import List

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_support
from app.models.user_model import User
from app.models.history_model import RentalHistory, RentalStatus
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
)
from app.admin.cars.router import (
    get_car_by_id,
    get_car_details_response,
    change_car_status_impl,
    toggle_car_notifications_impl,
)
from app.gps_api.utils.auth_api import get_auth_token
from app.gps_api.utils.car_data import (
    send_open,
    send_close,
    send_lock_engine,
    send_unlock_engine,
    send_give_key,
)
from app.core.config import GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD
from app.utils.action_logger import log_action
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
    body: dict = Body(..., embed=True),
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
):
    """Изменить описание автомобиля (для роли SUPPORT)."""
    car = get_car_by_id(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    description = body.get("description")
    if description is None:
        raise HTTPException(status_code=400, detail="Поле description обязательно")
    car.description = description if isinstance(description, str) else str(description)
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
