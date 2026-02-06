"""
Доступность тарифов и минимальные часы для часового тарифа привязаны к машине.
Настройки хранятся в полях Car, управляются через админку (по каждой машине).
"""
from fastapi import HTTPException

from app.models.car_model import Car
from app.models.history_model import RentalType
from app.core.logging_config import get_logger

logger = get_logger(__name__)


def get_tariff_settings_for_car(car: Car) -> dict:
    """Возвращает настройки тарифов для машины (для API ответов)."""
    return {
        "minutes_tariff_enabled": getattr(car, "minutes_tariff_enabled", True) is not False,
        "hourly_tariff_enabled": getattr(car, "hourly_tariff_enabled", True) is not False,
        "hourly_min_hours": max(1, getattr(car, "hourly_min_hours", 1) or 1),
    }


def validate_tariff_for_booking(
    rental_type: RentalType,
    duration: int | None,
    car: Car,
) -> None:
    """
    Проверяет, что тариф доступен для данной машины и (для часового) duration >= min_hours.
    Иначе выбрасывает HTTPException 400.
    """
    minutes_enabled = getattr(car, "minutes_tariff_enabled", True) is not False
    hourly_enabled = getattr(car, "hourly_tariff_enabled", True) is not False
    min_hours = max(1, getattr(car, "hourly_min_hours", 1) or 1)

    car_id = getattr(car, "id", None)
    if rental_type == RentalType.MINUTES:
        if not minutes_enabled:
            logger.warning(
                "validate_tariff_for_booking: минутный тариф недоступен car_id=%s",
                car_id,
            )
            raise HTTPException(
                status_code=400,
                detail="Минутный тариф для этого автомобиля недоступен.",
            )
        logger.debug("validate_tariff_for_booking: MINUTES ok car_id=%s", car_id)
        return
    if rental_type == RentalType.HOURS:
        if not hourly_enabled:
            logger.warning(
                "validate_tariff_for_booking: часовой тариф недоступен car_id=%s",
                car_id,
            )
            raise HTTPException(
                status_code=400,
                detail="Часовой тариф для этого автомобиля недоступен.",
            )
        if duration is None:
            logger.warning("validate_tariff_for_booking: HOURS без duration car_id=%s", car_id)
            raise HTTPException(status_code=400, detail="duration обязателен для почасовой аренды.")
        if duration < min_hours:
            logger.warning(
                "validate_tariff_for_booking: duration=%s < min_hours=%s car_id=%s",
                duration,
                min_hours,
                car_id,
            )
            raise HTTPException(
                status_code=400,
                detail=f"Для часового тарифа этого автомобиля минимальное количество часов — {min_hours}. Указано: {duration}.",
            )
        logger.debug("validate_tariff_for_booking: HOURS ok car_id=%s duration=%s", car_id, duration)
        return
    # DAYS — без ограничений по настройкам тарифа
    logger.debug("validate_tariff_for_booking: DAYS ok car_id=%s", car_id)
