from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.car_model import Car
from app.models.history_model import RentalHistory, RentalStatus
from app.models.user_model import User


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



def get_open_price(car: Car) -> int:
    if car.car_class == 1:
        return 4000
    elif car.car_class == 2:
        return 6000
    elif car.car_class == 3:
        return 8000
    else:
        return 0  # или можно вернуть None
