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

    rental_type = Column(Enum(RentalType), nullable=False)
    duration = Column(Integer, nullable=True)

    start_latitude = Column(Float, nullable=False)
    start_longitude = Column(Float, nullable=False)
    end_latitude = Column(Float, nullable=True)
    end_longitude = Column(Float, nullable=True)

    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime)

    reservation_time = Column(DateTime, default=datetime.utcnow, nullable=False)

    photos_before = Column(ARRAY(String))
    photos_after = Column(ARRAY(String))

    already_payed = Column(Integer, nullable=True)
    total_price = Column(Integer, nullable=True)

    rental_status = Column(Enum(RentalStatus), nullable=False, default=RentalStatus.RESERVED)

    review = relationship("RentalReview", back_populates="rental", uselist=False)


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
