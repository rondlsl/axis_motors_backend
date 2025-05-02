from sqlalchemy import Column, Integer, String, DateTime, Enum, Numeric, Boolean
import enum
from datetime import datetime
from sqlalchemy.orm import relationship
from app.dependencies.database.database import Base


class UserRole(enum.Enum):
    ADMIN = "admin"
    USER = "user"
    REJECTED = "rejected"
    FIRST = "first"
    PENDING = "pending"
    MECHANIC = "mechanic"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=True)
    phone_number = Column(String, nullable=False, unique=False)
    birth_date = Column(DateTime, nullable=True)
    iin = Column(String(12), nullable=True, unique=False)
    drivers_license_expiry = Column(DateTime, nullable=True)
    wallet_balance = Column(Numeric(10, 2), nullable=False, default=0)
    selfie_with_license_url = Column(String, nullable=True)
    drivers_license_url = Column(String, nullable=True)
    id_card_front_url = Column(String, nullable=True)
    id_card_back_url = Column(String, nullable=True)
    id_card_expiry = Column(DateTime, nullable=True)
    role = Column(Enum(UserRole), default=UserRole.FIRST)
    last_sms_code = Column(String)
    sms_code_valid_until = Column(DateTime)
    is_active = Column(Boolean, default=True, nullable=False)
    fcm_token = Column(String, nullable=True)

    rental_history = relationship("RentalHistory", back_populates="user",
                                  foreign_keys="[RentalHistory.user_id]")

    delivery_rentals = relationship("RentalHistory",
                                    foreign_keys="[RentalHistory.delivery_mechanic_id]",
                                    back_populates="delivery_mechanic")

    from app.models.car_model import Car
    owned_cars = relationship("Car", foreign_keys=[Car.owner_id], back_populates="owner")
    active_rental = relationship("Car", foreign_keys=[Car.current_renter_id],
                                 back_populates="current_renter", uselist=False)
