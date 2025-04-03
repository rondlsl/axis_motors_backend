from pydantic import BaseModel, Field


class SendSmsRequest(BaseModel):
    phone_number: str


class VerifySmsRequest(BaseModel):
    phone_number: str = Field(default="77472051507")

    sms_code: str = Field(default="6666")
