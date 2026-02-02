from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_support
from app.models.user_model import User
from app.models.history_model import RentalHistory, RentalStatus
from app.utils.short_id import uuid_to_sid
from app.admin.cars.schemas import CarDetailSchema, CarAvailabilityTimerSchema
from app.admin.cars.router import get_car_by_id, get_car_details_response
from app.utils.action_logger import log_action

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
