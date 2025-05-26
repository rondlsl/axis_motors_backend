from app.models.history_model import RentalType


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
