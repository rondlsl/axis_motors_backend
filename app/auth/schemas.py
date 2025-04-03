from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.user_model import UserRole


class SendSmsRequest(BaseModel):
    phone_number: str


class VerifySmsRequest(BaseModel):
    phone_number: str = Field(default="77472051507")

    sms_code: str = Field(default="6666")


class CarDetails(BaseModel):
    name: str
    plate_number: str
    fuel_level: Optional[float]


class RentalDetails(BaseModel):
    start_time: datetime
    rental_type: str
    duration: int
    already_payed: float


class CurrentRental(BaseModel):
    rental_details: RentalDetails
    car_details: CarDetails


class UserMeResponse(BaseModel):
    phone_number: str
    full_name: str
    role: str
    wallet_balance: float
    current_rental: Optional[CurrentRental] = None
