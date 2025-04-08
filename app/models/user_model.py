from sqlalchemy import Column, Integer, String, DateTime, Enum, Numeric
from sqlalchemy.orm import relationship
from app.dependencies.database.database import Base
import enum


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
    full_name = Column(String, nullable=True)  # делаем nullable так как заполняется при регистрации
    phone_number = Column(String, nullable=False, unique=True)
    birth_date = Column(DateTime, nullable=True)  # будет заполнено при регистрации
    iin = Column(String(12), nullable=True, unique=True)  # будет заполнено при регистрации
    drivers_license_expiry = Column(DateTime, nullable=True)  # будет заполнено при регистрации
    wallet_balance = Column(Numeric(10, 2), nullable=False, default=0)

    # URLs для документов - все могут быть nullable
    selfie_with_license_url = Column(String, nullable=True)
    drivers_license_url = Column(String, nullable=True)
    id_card_front_url = Column(String, nullable=True)
    id_card_back_url = Column(String, nullable=True)

    role = Column(Enum(UserRole), default=UserRole.FIRST)

    # Поля для SMS авторизации
    last_sms_code = Column(String)
    sms_code_valid_until = Column(DateTime)

    rental_history = relationship("RentalHistory", back_populates="user")

    # Relationships остаются без изменений

    # Определяем relationship после импорта всех моделей
    from app.models.car_model import Car  # импортируем здесь для избежания циклических импортов

    owned_cars = relationship("Car", foreign_keys=[Car.owner_id], back_populates="owner")
    active_rental = relationship("Car", foreign_keys=[Car.current_renter_id],
                                 back_populates="current_renter", uselist=False)
