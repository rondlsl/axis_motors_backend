from typing import Optional, Dict

from fastapi import HTTPException

from app.models.car_model import Car, CarBodyType
from app.models.history_model import RentalType

FUEL_PRICE_PER_LITER = 400
ELECTRIC_FUEL_PRICE_PER_LITER = 100
FULL_TANK_LITERS = 100  # Стандартный объем полного бака

# Стоимость водителя
DRIVER_FEE_PER_HOUR = 2000  # 2000₸ за каждый час (поминутный/часовой тариф)
DRIVER_FEE_PER_DAY = 20000  # 20000₸ за каждые сутки (суточный тариф)

# Минимальное время бронирования минутного тарифа (минуты)
MINUTE_TARIFF_MIN_MINUTES = 60


def get_open_price(car: Car) -> int:
    """
    Возвращает стоимость открытия дверей из базы данных.
    Если open_fee не задан, возвращает 4000 по умолчанию.
    """
    if car.open_fee is not None:
        return car.open_fee
    # Fallback на случай если open_fee не задан (старые записи)
    return 4000


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


def get_days_discount_multiplier(duration: int) -> float:
    """
    Множитель к базовой цене за сутки с учётом скидки по длительности.
    < 3 дней — 1.0, >= 3 дней — 0.95, >= 7 дней — 0.90, >= 30 дней — 0.85.
    """
    if duration >= 30:
        return 0.85
    if duration >= 7:
        return 0.90
    if duration >= 3:
        return 0.95
    return 1.0


DELIVERY_EXTRA_FEE = 10_000


def calc_required_balance(
        *,
        rental_type: RentalType,
        duration: Optional[int],
        car: Car,
        include_delivery: bool,
        is_owner: bool,
        with_driver: bool = False,
) -> int:
    """
    Рассчитывает минимальный баланс для аренды:
    - MINUTES: открытие дверей + price_per_minute * 60 (без дополнительного часа)
    - HOURS: открытие дверей + price_per_hour * duration + топливо (без доп. 60 мин)
    - DAYS: price_per_day * duration (со скидкой) + топливо (без доп. 60 мин)
    """
    if is_owner:
        # Для владельца минимальный баланс = 0
        return 0
    
    # open_fee (открытие дверей) - для всех типов аренды
    open_fee = get_open_price(car)
    delivery_fee = DELIVERY_EXTRA_FEE if include_delivery else 0
    
    # Стоимость аренды
    if rental_type == RentalType.MINUTES:
        # Минутный: открытие дверей + price_per_minute * 60 (минимум 60 минут)
        driver_fee = DRIVER_FEE_PER_HOUR * 2 if with_driver else 0  # 2 часа резерв
        required = open_fee + (car.price_per_minute * MINUTE_TARIFF_MIN_MINUTES) + delivery_fee + driver_fee
        return int(required)
    
    elif rental_type == RentalType.HOURS:
        if duration is None:
            raise HTTPException(status_code=400,
                                detail="duration обязателен для почасовой аренды.")
        # Часовой: открытие дверей + price_per_hour * duration + топливо (без доп. 60 мин)
        base_price = car.price_per_hour * duration
        # Топливо: ДВС 20*400=8000₸, электромобили 50*100=5000₸
        if car.body_type == CarBodyType.ELECTRIC:
            price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
            tank_liters = 50
        else:
            price_per_liter = FUEL_PRICE_PER_LITER
            tank_liters = 20
        full_tank_cost = tank_liters * price_per_liter

        driver_fee = DRIVER_FEE_PER_HOUR * duration if with_driver else 0
        required = open_fee + base_price + full_tank_cost + delivery_fee + driver_fee
        return int(required)
    
    else:  # RentalType.DAYS
        if duration is None:
            raise HTTPException(status_code=400,
                                detail="duration обязателен для посуточной аренды.")
        # Суточный: (price_per_day * duration) со скидкой + топливо (без доп. 60 мин)
        base = car.price_per_day * duration
        base_price = int(base * get_days_discount_multiplier(duration))
        # Топливо: ДВС 20*400=8000₸, электромобили 50*100=5000₸
        if car.body_type == CarBodyType.ELECTRIC:
            price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
            tank_liters = 50
        else:
            price_per_liter = FUEL_PRICE_PER_LITER
            tank_liters = 20
        full_tank_cost = tank_liters * price_per_liter

        driver_fee = DRIVER_FEE_PER_DAY * duration if with_driver else 0
        required = base_price + full_tank_cost + delivery_fee + driver_fee
    return int(required)


def calculate_rental_cost_breakdown(
        *,
        rental_type: RentalType,
        duration: Optional[int],
        car: Car,
        include_delivery: bool,
        is_owner: bool = False,
        with_driver: bool = False,
) -> Dict[str, any]:
    """
    Рассчитывает детализированную стоимость аренды для калькулятора.
    Возвращает разбивку по компонентам стоимости.
    """
    if is_owner:
        return {
            "base_price": 0,
            "open_fee": 0,
            "fuel_cost": 0,
            "delivery_fee": 0,
            "minute_cost_reserve": 0,
            "driver_fee": 0,
            "rebooking_fee": 0,
            "total_minimum_balance": 0,
            "breakdown": {
                "base_price": 0,
                "open_fee": 0,
                "fuel_cost": 0,
                "delivery_fee": 0,
                "minute_cost_reserve": 0,
                "driver_fee": 0,
                "rebooking_fee": 0
            }
        }
    
    open_fee = get_open_price(car)
    delivery_fee = DELIVERY_EXTRA_FEE if include_delivery else 0
    
    if rental_type == RentalType.MINUTES:
        base_price = 0
        minute_cost_reserve = car.price_per_minute * MINUTE_TARIFF_MIN_MINUTES
        fuel_cost = 0
        driver_fee = DRIVER_FEE_PER_HOUR * 2 if with_driver else 0  # 2 часа резерв
        total_minimum_balance = int(open_fee + minute_cost_reserve + delivery_fee + driver_fee)
    elif rental_type == RentalType.HOURS:
        if duration is None:
            raise HTTPException(status_code=400,
                                detail="duration обязателен для почасовой аренды.")
        base_price = car.price_per_hour * duration
        minute_cost_reserve = 0  # Часовой тариф без доп. 60 минут
        # Топливо: ДВС 8000₸, электромобили 5000₸
        if car.body_type == CarBodyType.ELECTRIC:
            price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
            tank_liters = 50
        else:
            price_per_liter = FUEL_PRICE_PER_LITER
            tank_liters = 20
        fuel_cost = tank_liters * price_per_liter

        driver_fee = DRIVER_FEE_PER_HOUR * duration if with_driver else 0
        total_minimum_balance = int(open_fee + base_price + fuel_cost + delivery_fee + driver_fee)
    else:  # RentalType.DAYS
        if duration is None:
            raise HTTPException(status_code=400,
                                detail="duration обязателен для посуточной аренды.")
        base = car.price_per_day * duration
        base_price = int(base * get_days_discount_multiplier(duration))
        minute_cost_reserve = 0  # Суточный тариф без доп. 60 минут
        # Топливо: ДВС 8000₸, электромобили 5000₸
        if car.body_type == CarBodyType.ELECTRIC:
            price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
            tank_liters = 50
        else:
            price_per_liter = FUEL_PRICE_PER_LITER
            tank_liters = 20
        fuel_cost = tank_liters * price_per_liter

        driver_fee = DRIVER_FEE_PER_DAY * duration if with_driver else 0
        total_minimum_balance = int(base_price + fuel_cost + delivery_fee + driver_fee)
    
    breakdown_open_fee = int(open_fee) if rental_type != RentalType.DAYS else 0
    
    return {
        "base_price": int(base_price),
        "open_fee": int(open_fee), 
        "fuel_cost": int(fuel_cost),
        "delivery_fee": int(delivery_fee),
        "minute_cost_reserve": int(minute_cost_reserve),
        "driver_fee": int(driver_fee),
        "rebooking_fee": 0,
        "total_minimum_balance": total_minimum_balance,
        "breakdown": {
            "base_price": int(base_price),
            "open_fee": breakdown_open_fee,  
            "fuel_cost": int(fuel_cost),
            "delivery_fee": int(delivery_fee),
            "minute_cost_reserve": int(minute_cost_reserve),
            "driver_fee": int(driver_fee),
            "rebooking_fee": 0
        }
    }
