"""
Глобальные настройки тарифов: доступность минутного/часового и минимум часов для часового.
Одна запись (singleton), управляется через админку.
"""
from sqlalchemy import Column, Integer, Boolean

from app.dependencies.database.database import Base


class TariffSettings(Base):
    __tablename__ = "tariff_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Минутный тариф доступен для бронирования
    minutes_tariff_enabled = Column(Boolean, nullable=False, default=True)
    # Часовой тариф доступен для бронирования
    hourly_tariff_enabled = Column(Boolean, nullable=False, default=True)
    # Минимальное количество часов для часового тарифа (от 1)
    hourly_min_hours = Column(Integer, nullable=False, default=1)
