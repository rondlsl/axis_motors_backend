"""
Управление настройками тарифов по машине через админку: доступность минутного/часового, минимум часов для часового.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.car_model import Car
from app.utils.short_id import safe_sid_to_uuid
from app.rent.utils.tariff_settings import get_tariff_settings_for_car
from app.core.logging_config import get_logger

logger = get_logger(__name__)
tariff_settings_router = APIRouter(tags=["Admin Tariff Settings"])


class TariffSettingsResponse(BaseModel):
    car_id: str
    minutes_tariff_enabled: bool
    hourly_tariff_enabled: bool
    hourly_min_hours: int


class TariffSettingsUpdate(BaseModel):
    minutes_tariff_enabled: bool | None = None
    hourly_tariff_enabled: bool | None = None
    hourly_min_hours: int | None = Field(None, ge=1, le=168, description="Минимум часов для часового тарифа (1–168)")


def _car_id_to_sid(car):
    from app.utils.short_id import uuid_to_sid
    return uuid_to_sid(car.id)


@tariff_settings_router.get("/{car_id}", response_model=TariffSettingsResponse)
async def get_tariff_settings_for_car_admin(
    car_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Получить настройки тарифов для машины (минутный/часовой доступны, мин. часов)."""
    if current_user.role not in (UserRole.ADMIN, UserRole.SUPPORT):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    car_uuid = safe_sid_to_uuid(car_id)
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    settings = get_tariff_settings_for_car(car)
    logger.info(
        "admin tariff_settings GET: car_id=%s minutes=%s hourly=%s min_hours=%s user_id=%s",
        car_id, settings["minutes_tariff_enabled"], settings["hourly_tariff_enabled"],
        settings["hourly_min_hours"], current_user.id,
    )
    return TariffSettingsResponse(
        car_id=_car_id_to_sid(car),
        minutes_tariff_enabled=settings["minutes_tariff_enabled"],
        hourly_tariff_enabled=settings["hourly_tariff_enabled"],
        hourly_min_hours=settings["hourly_min_hours"],
    )


@tariff_settings_router.patch("/{car_id}", response_model=TariffSettingsResponse)
async def update_tariff_settings_for_car(
    car_id: str,
    payload: TariffSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Обновить настройки тарифов для машины (вкл/выкл минутный и часовой, минимум часов)."""
    if current_user.role not in (UserRole.ADMIN, UserRole.SUPPORT):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    car_uuid = safe_sid_to_uuid(car_id)
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    if payload.minutes_tariff_enabled is not None:
        car.minutes_tariff_enabled = payload.minutes_tariff_enabled
    if payload.hourly_tariff_enabled is not None:
        car.hourly_tariff_enabled = payload.hourly_tariff_enabled
    if payload.hourly_min_hours is not None:
        car.hourly_min_hours = max(1, payload.hourly_min_hours)
    db.commit()
    db.refresh(car)
    settings = get_tariff_settings_for_car(car)
    logger.info(
        "admin tariff_settings PATCH: car_id=%s minutes=%s hourly=%s min_hours=%s user_id=%s",
        car_id,
        settings["minutes_tariff_enabled"],
        settings["hourly_tariff_enabled"],
        settings["hourly_min_hours"],
        current_user.id,
    )
    return TariffSettingsResponse(
        car_id=_car_id_to_sid(car),
        minutes_tariff_enabled=settings["minutes_tariff_enabled"],
        hourly_tariff_enabled=settings["hourly_tariff_enabled"],
        hourly_min_hours=settings["hourly_min_hours"],
    )
