from typing import Optional

from pydantic import BaseModel

from app.models.user_model import UserRole


class SendSmsRequest(BaseModel):
    phone_number: str


class VerifySmsRequest(BaseModel):
    phone_number: str
    sms_code: str


class UserMeResponse(BaseModel):
    phone_number: str
    full_name: Optional[str]
    role: UserRole
    wallet_balance: float
