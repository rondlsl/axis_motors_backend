from typing import Optional

from pydantic import BaseModel, Field

from app.models.user_model import UserRole


class SendSmsRequest(BaseModel):
    phone_number: str


class VerifySmsRequest(BaseModel):
    phone_number: str = Field(default="77472051507")

    sms_code: str = Field(default="6666")


class UserMeResponse(BaseModel):
    phone_number: str
    full_name: Optional[str]
    role: UserRole
    wallet_balance: float
