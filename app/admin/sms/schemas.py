from pydantic import BaseModel, Field
from typing import Optional


class SendSmsRequest(BaseModel):
    """Схема запроса для отправки SMS"""
    phone_number: str = Field(..., description="Номер телефона получателя (только цифры, например 77771234567)")
    message_text: str = Field(..., description="Текст SMS сообщения", min_length=1, max_length=500)

    class Config:
        json_schema_extra = {
            "example": {
                "phone_number": "77771234567",
                "message_text": "Здравствуйте! Это тестовое сообщение от AZV Motors."
            }
        }


class SendSmsResponse(BaseModel):
    """Схема ответа при отправке SMS"""
    success: bool
    message: str
    result: Optional[str] = None
    error: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "SMS sent successfully",
                "result": "Message sent"
            }
        }

