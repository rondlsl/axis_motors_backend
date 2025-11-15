from typing import Optional

from fastapi import HTTPException

from app.models.car_model import Car, CarBodyType
from app.models.history_model import RentalType

FUEL_PRICE_PER_LITER = 350
ELECTRIC_FUEL_PRICE_PER_LITER = 100
FULL_TANK_LITERS = 100  # Стандартный объем полного бака


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
    """
    Рассчитывает минимальный баланс для аренды:
    - Стоимость аренды (base_price)
    - 2 часа минутной аренды (120 минут * price_per_minute)
    - Полный бак топлива (100 литров * цена за литр)
    - open_fee (для MINUTES и HOURS)
    - delivery_fee (если есть)
    """
    if is_owner:
        # Для владельца минимальный баланс = только delivery_fee (если есть)
        if include_delivery:
            return 5000  # только доставка для владельца
        return 0
    
    # Определяем цену за литр в зависимости от типа автомобиля
    if car.body_type == CarBodyType.ELECTRIC:
        price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
    else:
        price_per_liter = FUEL_PRICE_PER_LITER
    
    # Полный бак топлива
    # Для Tucson (IMEI 860803068146253, vehicle_id 800339176) используем 20 литров вместо 100
    if car.gps_imei == "860803068146253":
        tank_liters = 20
    else:
        tank_liters = FULL_TANK_LITERS
    full_tank_cost = tank_liters * price_per_liter
    
    # 2 часа минутной аренды (120 минут)
    two_hours_minute_cost = 120 * car.price_per_minute
    
    # open_fee (только для MINUTES и HOURS)
    open_fee = get_open_price(car) if rental_type in (RentalType.MINUTES, RentalType.HOURS) else 0
    
    # Стоимость аренды
    if rental_type == RentalType.MINUTES:
        base_price = 0  # для минутной аренды базовая цена не списывается сразу
    elif rental_type == RentalType.HOURS:
        if duration is None:
            raise HTTPException(status_code=400,
                                detail="duration обязателен для почасовой аренды.")
        base_price = calculate_total_price(rental_type, duration, car.price_per_hour, car.price_per_day)
    else:  # RentalType.DAYS
        if duration is None:
            raise HTTPException(status_code=400,
                                detail="duration обязателен для посуточной аренды.")
        base_price = calculate_total_price(rental_type, duration, car.price_per_hour, car.price_per_day)
    
    # delivery_fee
    delivery_fee = DELIVERY_EXTRA_FEE if include_delivery else 0
    
    # Итого минимальный баланс
    required = base_price + two_hours_minute_cost + full_tank_cost + open_fee + delivery_fee
    
    return int(required)
