from sqlalchemy import Column, Integer, String, Float, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship
from app.dependencies.database.database import Base


class Car(Base):
    __tablename__ = "cars"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    plate_number = Column(String, nullable=False, unique=True)
    latitude = Column(Float)
    longitude = Column(Float)
    gps_id = Column(String)
    gps_imei = Column(String)
    fuel_level = Column(Float)
    mileage = Column(Integer)
    course = Column(Integer, nullable=True)

    price_per_minute = Column(Integer, nullable=False)
    price_per_hour = Column(Integer, nullable=False)
    price_per_day = Column(Integer, nullable=False)
    car_class = Column(Integer, nullable=True, default=1)

    engine_volume = Column(Float, nullable=True)
    year = Column(Integer, nullable=True)
    drive_type = Column(Integer, nullable=True)

    photos = Column(JSON, nullable=True)

    description = Column(Text, nullable=True)

    owner_id = Column(Integer, ForeignKey("users.id"))
    current_renter_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    status = Column(String, default="FREE", nullable=True)

    owner = relationship("User", foreign_keys=[owner_id], back_populates="owned_cars")
    current_renter = relationship("User", foreign_keys=[current_renter_id], back_populates="active_rental")
    rental_history = relationship("RentalHistory", back_populates="car")
