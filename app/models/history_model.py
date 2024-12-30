import enum
from datetime import datetime

from sqlalchemy import Column, Integer, ForeignKey, Enum, Float, DateTime, ARRAY, String
from sqlalchemy.orm import relationship

from app.dependencies.database.database import Base


class RentalType(enum.Enum):
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"


class RentalHistory(Base):
    __tablename__ = "rental_history"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="rental_history")

    car_id = Column(Integer, ForeignKey("cars.id"), nullable=False)
    car = relationship("Car", back_populates="rental_history")

    # Детали аренды
    rental_type = Column(Enum(RentalType), nullable=False)
    duration = Column(Integer, nullable=False)  # количество минут/часов/дней

    # Геолокация
    start_latitude = Column(Float, nullable=False)
    start_longitude = Column(Float, nullable=False)
    end_latitude = Column(Float, nullable=False)
    end_longitude = Column(Float, nullable=False)

    # Время
    start_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    end_time = Column(DateTime)

    # Фотографии
    photos_before = Column(ARRAY(String))  # массив URL фотографий до начала аренды
    photos_after = Column(ARRAY(String))  # массив URL фотографий после завершения

    # Стоимость
    total_price = Column(Integer, nullable=False)  # в тенге
