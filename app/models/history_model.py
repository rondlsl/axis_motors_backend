import enum
from datetime import datetime

from sqlalchemy import Column, Integer, ForeignKey, Enum, Float, DateTime, ARRAY, String, Text
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
    DELIVERING = "delivering"
    DELIVERING_IN_PROGRESS = "delivering_in_progress"
    DELIVERY_RESERVED = "delivery_reserved"
    CANCELLED = "cancelled"
    SCHEDULED = "scheduled"  # Забронировано заранее


class RentalHistory(Base):
    __tablename__ = "rental_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="rental_history", foreign_keys=[user_id])

    car_id = Column(Integer, ForeignKey("cars.id"), nullable=False)
    car = relationship("Car", back_populates="rental_history")

    rental_type = Column(Enum(RentalType), nullable=False)
    duration = Column(Integer, nullable=True)

    start_latitude = Column(Float, nullable=False)
    start_longitude = Column(Float, nullable=False)
    end_latitude = Column(Float, nullable=True)
    end_longitude = Column(Float, nullable=True)

    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime)
    reservation_time = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Поля для бронирования заранее
    scheduled_start_time = Column(DateTime, nullable=True)  # Запланированное время начала аренды
    scheduled_end_time = Column(DateTime, nullable=True)    # Запланированное время окончания аренды
    is_advance_booking = Column(String, default="false", nullable=False)  # Флаг бронирования заранее

    base_price = Column(Integer, nullable=True)
    open_fee = Column(Integer, nullable=True)
    delivery_fee = Column(Integer, nullable=True)
    waiting_fee = Column(Integer, nullable=True, default=0)
    overtime_fee = Column(Integer, nullable=True, default=0)
    distance_fee = Column(Integer, nullable=True, default=0)

    photos_before = Column(ARRAY(String))
    photos_after = Column(ARRAY(String))

    fuel_before = Column(Float, nullable=True)
    fuel_after = Column(Float, nullable=True)
    mileage_before = Column(Integer, nullable=True)
    mileage_after = Column(Integer, nullable=True)

    already_payed = Column(Integer, nullable=True)
    total_price = Column(Integer, nullable=True)

    rental_status = Column(Enum(RentalStatus), nullable=False, default=RentalStatus.RESERVED)

    # Новые поля для доставки
    delivery_latitude = Column(Float, nullable=True)
    delivery_longitude = Column(Float, nullable=True)
    delivery_mechanic_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Время доставки
    delivery_start_time = Column(DateTime, nullable=True)  # Когда механик начал доставку
    delivery_end_time = Column(DateTime, nullable=True)    # Когда механик завершил доставку
    delivery_penalty_fee = Column(Integer, nullable=True, default=0)  # Штраф за задержку доставки

    # Поля для хранения фотографий перед и после доставки
    delivery_photos_before = Column(ARRAY(String), nullable=True)
    delivery_photos_after = Column(ARRAY(String), nullable=True)

    # Поля для хранения фотографий механика при осмотре
    mechanic_photos_before = Column(ARRAY(String), nullable=True)
    mechanic_photos_after = Column(ARRAY(String), nullable=True)
    
    # Поля для осмотра механиком
    mechanic_inspector_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    mechanic_inspection_start_time = Column(DateTime, nullable=True)
    mechanic_inspection_end_time = Column(DateTime, nullable=True)
    mechanic_inspection_status = Column(String, nullable=True, default="PENDING")
    mechanic_inspection_comment = Column(Text, nullable=True)

    # Явно задаём связь для механика доставки:
    delivery_mechanic = relationship("User", foreign_keys=[delivery_mechanic_id])
    
    # Связь для механика-инспектора:
    mechanic_inspector = relationship("User", foreign_keys=[mechanic_inspector_id])

    review = relationship("RentalReview", back_populates="rental", uselist=False)

    actions = relationship(
        "RentalAction",
        back_populates="rental",
        cascade="all, delete-orphan"
    )


class RentalReview(Base):
    __tablename__ = "rental_reviews"

    id = Column(Integer, primary_key=True, index=True)

    rental_id = Column(Integer, ForeignKey("rental_history.id"), nullable=False)
    rental = relationship("RentalHistory", back_populates="review")

    # Отзыв от клиента
    rating = Column(Integer, nullable=True)  # от 1 до 5
    comment = Column(String(255), nullable=True)
    
    # Отзыв от механика осмотра
    mechanic_rating = Column(Integer, nullable=True)  # от 1 до 5
    mechanic_comment = Column(String(255), nullable=True)
    
    # Отзыв от механика доставки
    delivery_mechanic_rating = Column(Integer, nullable=True)  # от 1 до 5
    delivery_mechanic_comment = Column(String(255), nullable=True)

    # Через rental -> user / car
    @property
    def user(self):
        return self.rental.user if self.rental else None

    @property
    def car(self):
        return self.rental.car if self.rental else None
