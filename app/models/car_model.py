from enum import Enum
import uuid

from sqlalchemy import Column, Integer, String, Float, ForeignKey, JSON, Text, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.dependencies.database.database import Base
from app.utils.time_utils import get_local_time


class CarBodyType(str, Enum):
    SEDAN = "SEDAN"  # Седан
    SUV = "SUV"  # Внедорожник
    CROSSOVER = "CROSSOVER"  # Кроссовер
    COUPE = "COUPE"  # Купе
    HATCHBACK = "HATCHBACK"  # Хэтчбек
    CONVERTIBLE = "CONVERTIBLE"  # Кабриолет
    WAGON = "WAGON"  # Универсал
    MINIBUS = "MINIBUS"
    ELECTRIC = "ELECTRIC"


class CarAutoClass(str, Enum):
    A = "A"  # До 25 млн
    B = "B"  # До 40 млн
    C = "C"  # 40+ млн


class TransmissionType(str, Enum):
    MANUAL = "manual"  # Механическая
    AUTOMATIC = "automatic"  # Автоматическая
    CVT = "cvt"  # Вариатор
    SEMI_AUTOMATIC = "semi_automatic"  # Полуавтоматическая


class CarStatus(str, Enum):
    FREE = "FREE"  # Свободна
    PENDING = "PENDING"  # Ожидает механика
    IN_USE = "IN_USE"  # В использовании
    DELIVERING = "DELIVERING"  # Доставляется
    SERVICE = "SERVICE"  # На обслуживании
    RESERVED = "RESERVED"  # Зарезервирована
    SCHEDULED = "SCHEDULED"  # Забронирована заранее
    OWNER = "OWNER"  # У владельца
    OCCUPIED = "OCCUPIED"  # Занята (не отображается)


class Car(Base):
    __tablename__ = "cars"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=False)
    plate_number = Column(String, nullable=False, unique=True)
    latitude = Column(Float)
    longitude = Column(Float)
    gps_id = Column(String)
    gps_imei = Column(String)
    fuel_level = Column(Float)
    mileage = Column(Integer)
    course = Column(Integer, nullable=True)
    speed = Column(Float, nullable=True)  # Скорость в км/ч

    price_per_minute = Column(Integer, nullable=False)
    price_per_hour = Column(Integer, nullable=False)
    price_per_day = Column(Integer, nullable=False)
    open_fee = Column(Integer, nullable=False, default=4000)  # Стоимость открытия дверей
    car_class = Column(Integer, nullable=True, default=1)
    auto_class = Column(
        SAEnum(CarAutoClass, name="car_auto_class"),
        default=CarAutoClass.A,
        nullable=False
    )

    engine_volume = Column(Float, nullable=True)
    year = Column(Integer, nullable=True)
    drive_type = Column(Integer, nullable=True)
    transmission_type = Column(
        SAEnum(TransmissionType, name="transmission_type"),
        nullable=True
    )
    body_type = Column(
        SAEnum(CarBodyType, name="car_body_type"),
        default=CarBodyType.SEDAN,
        nullable=False
    )

    vin = Column(String, nullable=True) 
    color = Column(String, nullable=True)
    photos = Column(JSON, nullable=True)
    description = Column(Text, nullable=True)

    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    current_renter_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    status = Column(SAEnum(CarStatus), default=CarStatus.FREE, nullable=True)
    available_minutes = Column(Integer, default=0, nullable=False)
    availability_updated_at = Column(DateTime, default=get_local_time, nullable=True)
    created_at = Column(DateTime, default=get_local_time, nullable=False)
    updated_at = Column(DateTime, default=get_local_time, nullable=True)
    rating = Column(Float, nullable=True) 

    owner = relationship("User", foreign_keys=[owner_id], back_populates="owned_cars")
    current_renter = relationship("User", foreign_keys=[current_renter_id], back_populates="active_rental")
    rental_history = relationship("RentalHistory", back_populates="car")
    
    # Связь для комментариев
    comments = relationship("CarComment", back_populates="car", cascade="all, delete-orphan")

    @property
    def sid(self) -> str:
        from app.utils.short_id import uuid_to_sid
        return uuid_to_sid(self.id)


class CarAvailabilityHistory(Base):
    __tablename__ = "car_availability_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    car_id = Column(UUID(as_uuid=True), ForeignKey("cars.id"), nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    available_minutes = Column(Integer, default=0, nullable=False)
    
    created_at = Column(DateTime, default=get_local_time, nullable=False)
    updated_at = Column(DateTime, default=get_local_time, onupdate=get_local_time, nullable=True)

    car = relationship("Car", backref="availability_history")
