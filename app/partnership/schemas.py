from typing import Optional
from pydantic import BaseModel, Field, field_validator


class PartnershipRequest(BaseModel):
    """Заявка на сотрудничество."""
    name: str = Field(..., min_length=2, max_length=100, description="Имя")
    phone: str = Field(..., min_length=10, max_length=20, description="Телефон")
    email: Optional[str] = Field(None, min_length=5, max_length=100, description="Email")
    company_name: Optional[str] = Field(None, min_length=2, max_length=200, description="Название компании")
    message: str = Field(..., min_length=10, max_length=1000, description="Сообщение о сотрудничестве")

    @field_validator("name", "message")
    @classmethod
    def normalize_text(cls, v: str) -> str:
        return v.strip()

    @field_validator("company_name")
    @classmethod
    def normalize_company_name(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else None

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: str) -> str:
        return v.strip()

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: Optional[str]) -> Optional[str]:
        return v.strip().lower() if v else None


class PartnershipResponse(BaseModel):
    """Ответ при создании заявки."""
    message: str
    success: bool
