import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, Integer, ForeignKey, Float, DateTime, ARRAY, String, Text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.dependencies.database.database import Base
from app.utils.short_id import uuid_to_sid


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
    SCHEDULED = "scheduled"


class RentalHistory(Base):
    __tablename__ = "rental_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="rental_history", foreign_keys=[user_id])

    car_id = Column(Integer, ForeignKey("cars.id"), nullable=False)
    car = relationship("Car", back_populates="rental_history")

    rental_type = Column(ENUM(RentalType), nullable=False)
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

    rental_status = Column(ENUM(RentalStatus), nullable=False, default=RentalStatus.RESERVED)

    # Новые поля для доставки
    delivery_latitude = Column(Float, nullable=True)
    delivery_longitude = Column(Float, nullable=True)
    delivery_mechanic_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    
    # Время доставки
    delivery_start_time = Column(DateTime, nullable=True)  # Когда механик начал доставку
    delivery_end_time = Column(DateTime, nullable=True)    # Когда механик завершил доставку
    delivery_penalty_fee = Column(Integer, nullable=True, default=0)  # Штраф за задержку доставки

    # Координаты начала/окончания доставки (фиксируются у механика-доставщика)
    delivery_start_latitude = Column(Float, nullable=True)
    delivery_start_longitude = Column(Float, nullable=True)
    delivery_end_latitude = Column(Float, nullable=True)
    delivery_end_longitude = Column(Float, nullable=True)

    # Поля для хранения фотографий перед и после доставки
    delivery_photos_before = Column(ARRAY(String), nullable=True)
    delivery_photos_after = Column(ARRAY(String), nullable=True)

    # Поля для хранения фотографий механика при осмотре
    mechanic_photos_before = Column(ARRAY(String), nullable=True)
    mechanic_photos_after = Column(ARRAY(String), nullable=True)
    
    # Поля для осмотра механиком
    mechanic_inspector_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    mechanic_inspection_start_time = Column(DateTime, nullable=True)
    mechanic_inspection_end_time = Column(DateTime, nullable=True)
    mechanic_inspection_status = Column(String, nullable=True, default="PENDING")
    mechanic_inspection_comment = Column(Text, nullable=True)

    # Координаты начала/окончания осмотра механиком
    mechanic_inspection_start_latitude = Column(Float, nullable=True)
    mechanic_inspection_start_longitude = Column(Float, nullable=True)
    mechanic_inspection_end_latitude = Column(Float, nullable=True)
    mechanic_inspection_end_longitude = Column(Float, nullable=True)

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
    
    # Связь для подписанных договоров аренды
    contract_signatures = relationship(
        "UserContractSignature",
        foreign_keys="[UserContractSignature.rental_id]",
        back_populates="rental",
        cascade="all, delete-orphan"
    )
    
    @property
    def sid(self) -> str:
        """Короткий ID для использования в API"""
        return uuid_to_sid(self.id)


class RentalReview(Base):
    __tablename__ = "rental_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    rental_id = Column(UUID(as_uuid=True), ForeignKey("rental_history.id"), nullable=False)
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
    
    @property
    def sid(self) -> str:
        """Короткий ID для использования в API"""
        return uuid_to_sid(self.id)
