from app.models.history_model import RentalType


def calculate_total_price(rental_type: RentalType, duration: int, price_per_hour: float, price_per_day: float) -> float:
    if rental_type == RentalType.MINUTES:
        return None  # For minutes, total price is not calculated initially
    elif rental_type == RentalType.HOURS:
        return price_per_hour * duration
    else:  # RentalType.DAYS
        return price_per_day * duration