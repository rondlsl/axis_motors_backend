from sqlalchemy import Column, Integer, String, Float, ForeignKey, Enum
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
    price_per_minute = Column(Integer, nullable=False)
    price_per_hour = Column(Integer, nullable=False)
    price_per_day = Column(Integer, nullable=False)

    owner_id = Column(Integer, ForeignKey("users.id"))
    current_renter_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # В car_model.py добавляем:
    owner = relationship("User", foreign_keys=[owner_id], back_populates="owned_cars")
    current_renter = relationship("User", foreign_keys=[current_renter_id],
                                  back_populates="active_rental")

    rental_history = relationship("RentalHistory", back_populates="car")
