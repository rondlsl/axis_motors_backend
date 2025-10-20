from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status
import uuid

from app.models.car_model import Car
from app.models.history_model import RentalHistory, RentalStatus
from app.models.user_model import User


def get_active_rental(db: Session, user_id: uuid.UUID) -> RentalHistory:
    """
    Находит текущую аренду (IN_USE или DELIVERING_IN_PROGRESS) для пользователя.
    """
    rental = (
        db.query(RentalHistory)
        .filter(
            RentalHistory.user_id == user_id,
            RentalHistory.rental_status.in_([
                RentalStatus.IN_USE,
                RentalStatus.DELIVERING_IN_PROGRESS,
                RentalStatus.DELIVERING
            ])
        )
        .order_by(RentalHistory.start_time.desc())
        .first()
    )
    if not rental:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Активная аренда не найдена"
        )
    return rental


def get_active_rental_car(db: Session, current_user: User) -> Car:
    # Выполняем JOIN между Car и RentalHistory, чтобы за один запрос получить машину из активной аренды
    car = (
        db.query(Car)
        .join(RentalHistory, RentalHistory.car_id == Car.id)
        .filter(
            RentalHistory.user_id == current_user.id,
            RentalHistory.rental_status == RentalStatus.IN_USE
        )
        .first()
    )
    if not car or not car.gps_id:
        raise HTTPException(status_code=404, detail="Car or GPS ID not found")
    return car


def get_active_rental_by_car_id(db: Session, car_id: uuid.UUID) -> RentalHistory:
    """
    Находит активную аренду для конкретного автомобиля.
    """
    rental = (
        db.query(RentalHistory)
        .filter(
            RentalHistory.car_id == car_id,
            RentalHistory.rental_status.in_([
                RentalStatus.IN_USE,
                RentalStatus.DELIVERING_IN_PROGRESS,
                RentalStatus.DELIVERING
            ])
        )
        .order_by(RentalHistory.start_time.desc())
        .first()
    )
    if not rental:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Активная аренда для данного автомобиля не найдена"
        )
    return rental