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
    DELIVERING = "delivering"
    DELIVERING_IN_PROGRESS = "delivering_in_progress"
    DELIVERY_RESERVED = "delivery_reserved"
    CANCELLED = "cancelled"


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

    # Поля для хранения фотографий перед и после доставки
    delivery_photos_before = Column(ARRAY(String), nullable=True)
    delivery_photos_after = Column(ARRAY(String), nullable=True)

    # Явно задаём связь для механика доставки:
    delivery_mechanic = relationship("User", foreign_keys=[delivery_mechanic_id])

    review = relationship("RentalReview", back_populates="rental", uselist=False)

    actions = relationship(
        "RentalAction",
        back_populates="rental",
        cascade="all, delete-orphan"
    )


class RentalReview(Base):
    __tablename__ = "rental_reviews"

    id = Column(Integer, primary_key=True, index=True)

    rental_id = Column(Integer, ForeignKey("rental_history.id"), nullable=False, unique=True)
    rental = relationship("RentalHistory", back_populates="review")

    rating = Column(Integer, nullable=False)  # от 1 до 5
    comment = Column(String(255), nullable=True)

    # Через rental -> user / car
    @property
    def user(self):
        return self.rental.user if self.rental else None

    @property
    def car(self):
        return self.rental.car if self.rental else None
