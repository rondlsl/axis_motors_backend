from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.car_model import Car
from app.models.history_model import RentalHistory, RentalStatus
from app.models.user_model import User


def get_active_rental_car(db: Session, current_user: User) -> Car:
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
