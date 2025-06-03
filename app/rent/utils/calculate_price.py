from typing import Optional

from fastapi import HTTPException

from app.models.car_model import Car
from app.models.history_model import RentalType


def get_open_price(car: Car) -> int:
    if car.car_class == 1:
        return 4000
    elif car.car_class == 2:
        return 6000
    elif car.car_class == 3:
        return 8000
    else:
        return 0  # или можно вернуть None


def calculate_total_price(
        rental_type: RentalType,
        duration: int,
        price_per_hour: float,
        price_per_day: float
) -> float:
    """
    Возвращает итоговую стоимость с учётом скидки:
      - < 3 дней: без скидки
      - >= 3 дней: 5%
      - >= 7 дней: 10%
      - >= 30 дней: 15%
    """
    if rental_type == RentalType.MINUTES:
        return 0  # для поминутной аренды цена не считается заранее
    if rental_type == RentalType.HOURS:
        return price_per_hour * duration

    # DAYS
    base = price_per_day * duration
    if duration >= 30:
        discount = 0.15
    elif duration >= 7:
        discount = 0.10
    elif duration >= 3:
        discount = 0.05
    else:
        discount = 0.0

    return int(base * (1 - discount))


DELIVERY_EXTRA_FEE = 10_000


def calc_required_balance(
        *,
        rental_type: RentalType,
        duration: Optional[int],
        car: Car,
        include_delivery: bool,
        is_owner: bool,
) -> int:
    """Считаем, сколько должно лежать на кошельке до брони/доставки."""
    open_fee = getattr(car, "open_fee", 0)  # плата за «открыть»
    two_hours_cost = car.price_per_hour * 2  # запас на +2 ч

    if rental_type == RentalType.MINUTES:
        required = open_fee + two_hours_cost  # минута +2 ч + open
    elif rental_type == RentalType.HOURS:
        if duration is None:
            raise HTTPException(status_code=400,
                                detail="duration обязателен для почасовой аренды.")
        required = open_fee + (duration + 2) * car.price_per_hour
    else:  # RentalType.DAYS
        if duration is None:
            raise HTTPException(status_code=400,
                                detail="duration обязателен для посуточной аренды.")
        required = duration * car.price_per_day + two_hours_cost  # без open_fee

    if include_delivery and not is_owner:
        required += DELIVERY_EXTRA_FEE

    return required
