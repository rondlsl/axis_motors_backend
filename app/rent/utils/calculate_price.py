from typing import Optional

from fastapi import HTTPException

from app.models.car_model import Car, CarBodyType
from app.models.history_model import RentalType

FUEL_PRICE_PER_LITER = 350
ELECTRIC_FUEL_PRICE_PER_LITER = 100
FULL_TANK_LITERS = 100  # Стандартный объем полного бака


def get_open_price(car: Car) -> int:
    if car.gps_imei == "860803068155890":
        return 8000
    
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
    - MINUTES: открытие дверей + price_per_minute * 120
    - HOURS: открытие дверей + price_per_hour * duration + price_per_minute * 60 + топливо
    - DAYS: price_per_day * duration + price_per_minute * 60 + топливо
    """
    if is_owner:
        # Для владельца минимальный баланс = 0
        return 0
    
    # open_fee (открытие дверей) - для всех типов аренды
    open_fee = get_open_price(car)
    delivery_fee = DELIVERY_EXTRA_FEE if include_delivery else 0
    
    # Стоимость аренды
    if rental_type == RentalType.MINUTES:
        # Минутный: открытие дверей + price_per_minute * 120
        required = open_fee + (car.price_per_minute * 120) + delivery_fee
        return int(required)
    
    elif rental_type == RentalType.HOURS:
        if duration is None:
            raise HTTPException(status_code=400,
                                detail="duration обязателен для почасовой аренды.")
        # Часовой: открытие дверей + price_per_hour * duration + price_per_minute * 60 + топливо
        base_price = car.price_per_hour * duration
        one_hour_minute_cost = car.price_per_minute * 60
        
        # Топливо
        if car.body_type == CarBodyType.ELECTRIC:
            price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
        else:
            price_per_liter = FUEL_PRICE_PER_LITER
        # Для Tucson (IMEI 860803068146253, vehicle_id 800339176) используем 20 литров вместо 100
        # Для Hongqi (IMEI 860803068139548, vehicle_id 800283232) используем 50 литров вместо 100
        if car.gps_imei == "860803068146253":
            tank_liters = 20
        elif car.gps_imei == "860803068139548":
            tank_liters = 50
        else:
            tank_liters = FULL_TANK_LITERS
        full_tank_cost = tank_liters * price_per_liter
        
        required = open_fee + base_price + one_hour_minute_cost + full_tank_cost + delivery_fee
        return int(required)
    
    else:  # RentalType.DAYS
        if duration is None:
            raise HTTPException(status_code=400,
                                detail="duration обязателен для посуточной аренды.")
        # Дневной: price_per_day * duration + price_per_minute * 60 + топливо
        # base = car.price_per_day * duration
        # if duration >= 30:
        #     discount = 0.15
        # elif duration >= 7:
        #     discount = 0.10
        # elif duration >= 3:
        #     discount = 0.05
        # else:
        #     discount = 0.0
        # base_price = int(base * (1 - discount))
        base_price = car.price_per_day * duration
        
        one_hour_minute_cost = car.price_per_minute * 60
        
        # Топливо
        if car.body_type == CarBodyType.ELECTRIC:
            price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
        else:
            price_per_liter = FUEL_PRICE_PER_LITER
        # Для Tucson (IMEI 860803068146253, vehicle_id 800339176) используем 20 литров вместо 100
        # Для Hongqi (IMEI 860803068139548, vehicle_id 800283232) используем 50 литров вместо 100
        if car.gps_imei == "860803068146253":
            tank_liters = 20
        elif car.gps_imei == "860803068139548":
            tank_liters = 50
        else:
            tank_liters = FULL_TANK_LITERS
        full_tank_cost = tank_liters * price_per_liter
        
        required = base_price + one_hour_minute_cost + full_tank_cost + delivery_fee
    return int(required)
