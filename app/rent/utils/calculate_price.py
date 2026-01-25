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
        driver_fee = DRIVER_FEE_PER_HOUR * 2 if with_driver else 0  # 2 часа резерв
        required = open_fee + (car.price_per_minute * 120) + delivery_fee + driver_fee
        return int(required)
    
    elif rental_type == RentalType.HOURS:
        if duration is None:
            raise HTTPException(status_code=400,
                                detail="duration обязателен для почасовой аренды.")
        # Часовой: открытие дверей + price_per_hour * duration + price_per_minute * 60 + топливо
        base_price = car.price_per_hour * duration
        one_hour_minute_cost = car.price_per_minute * 60
        
        # Топливо: электрички 50л, бензиновые 20л
        if car.body_type == CarBodyType.ELECTRIC:
            price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
            tank_liters = 50
        else:
            price_per_liter = FUEL_PRICE_PER_LITER
            tank_liters = 20
        full_tank_cost = tank_liters * price_per_liter
        
        driver_fee = DRIVER_FEE_PER_HOUR * duration if with_driver else 0
        required = open_fee + base_price + one_hour_minute_cost + full_tank_cost + delivery_fee + driver_fee
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
        
        # Топливо: электрички 50л, бензиновые 20л
        if car.body_type == CarBodyType.ELECTRIC:
            price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
            tank_liters = 50
        else:
            price_per_liter = FUEL_PRICE_PER_LITER
            tank_liters = 20
        full_tank_cost = tank_liters * price_per_liter
        
        driver_fee = DRIVER_FEE_PER_DAY * duration if with_driver else 0
        required = base_price + one_hour_minute_cost + full_tank_cost + delivery_fee + driver_fee
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
        minute_cost_reserve = car.price_per_minute * 120  
        fuel_cost = 0
        driver_fee = DRIVER_FEE_PER_HOUR * 2 if with_driver else 0  # 2 часа резерв
        total_minimum_balance = int(open_fee + minute_cost_reserve + delivery_fee + driver_fee)
    elif rental_type == RentalType.HOURS:
        if duration is None:
            raise HTTPException(status_code=400,
                                detail="duration обязателен для почасовой аренды.")
        base_price = car.price_per_hour * duration
        minute_cost_reserve = car.price_per_minute * 60 
        
        # Топливо: электрички 50л, бензиновые 20л (синхронизировано с calc_required_balance)
        if car.body_type == CarBodyType.ELECTRIC:
            price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
            tank_liters = 50
        else:
            price_per_liter = FUEL_PRICE_PER_LITER
            tank_liters = 20
        fuel_cost = tank_liters * price_per_liter
        
        driver_fee = DRIVER_FEE_PER_HOUR * duration if with_driver else 0
        total_minimum_balance = int(open_fee + base_price + minute_cost_reserve + fuel_cost + delivery_fee + driver_fee)
    else:  
        if duration is None:
            raise HTTPException(status_code=400,
                                detail="duration обязателен для посуточной аренды.")
        base_price = car.price_per_day * duration
        minute_cost_reserve = car.price_per_minute * 60 
        
        # Топливо: электрички 50л, бензиновые 20л (синхронизировано с calc_required_balance)
        if car.body_type == CarBodyType.ELECTRIC:
            price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
            tank_liters = 50
        else:
            price_per_liter = FUEL_PRICE_PER_LITER
            tank_liters = 20
        fuel_cost = tank_liters * price_per_liter
        
        driver_fee = DRIVER_FEE_PER_DAY * duration if with_driver else 0
        total_minimum_balance = int(base_price + minute_cost_reserve + fuel_cost + delivery_fee + driver_fee)
    
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
