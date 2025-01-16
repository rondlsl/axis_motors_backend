import enum
from datetime import datetime

from sqlalchemy import Column, Integer, ForeignKey, Enum, Float, DateTime, ARRAY, String
from sqlalchemy.orm import relationship

from app.dependencies.database.database import Base


class RentalType(enum.Enum):
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"


class RentalStatus(enum.Enum):
    RESERVED = "reserved"
    IN_USE = "in_use"
    COMPLETED = "completed"


class RentalHistory(Base):
    __tablename__ = "rental_history"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="rental_history")

    car_id = Column(Integer, ForeignKey("cars.id"), nullable=False)
    car = relationship("Car", back_populates="rental_history")

    # Детали аренды
    rental_type = Column(Enum(RentalType), nullable=False)
    duration = Column(Integer, nullable=True)  # количество минут/часов/дней

    # Геолокация
    start_latitude = Column(Float, nullable=False)
    start_longitude = Column(Float, nullable=False)
    end_latitude = Column(Float, nullable=True)
    end_longitude = Column(Float, nullable=True)

    # Время
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime)

    # Фотографии
    photos_before = Column(ARRAY(String))  # массив URL фотографий до начала аренды
    photos_after = Column(ARRAY(String))  # массив URL фотографий после завершения

    # Стоимость
    already_payed = Column(Integer, nullable=True)  # в тенге
    total_price = Column(Integer, nullable=True)  # в тенге

    # Статус аренды
    rental_status = Column(Enum(RentalStatus), nullable=False, default=RentalStatus.RESERVED)
