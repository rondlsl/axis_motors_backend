from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator


# ─── User endpoint schemas ───────────────────────────────────────────

class PromoApplyRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=64, description="Промокод")

    @field_validator("code")
    @classmethod
    def normalize_code(cls, v: str) -> str:
        return v.strip()


class PromoApplyResponse(BaseModel):
    message: str
    bonus_amount: int
    new_balance: float


# ─── Admin endpoint schemas ──────────────────────────────────────────

class PromoCreateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    description: Optional[str] = None
    bonus_amount: int = Field(..., gt=0)
    valid_from: datetime
    valid_to: datetime
    max_uses: Optional[int] = Field(None, gt=0)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, v: str) -> str:
        return v.strip()

    @field_validator("valid_to")
    @classmethod
    def dates_order(cls, v: datetime, info) -> datetime:
        if "valid_from" in info.data and v <= info.data["valid_from"]:
            raise ValueError("valid_to должен быть позже valid_from")
        return v


class PromoUpdateRequest(BaseModel):
    description: Optional[str] = None
    bonus_amount: Optional[int] = Field(None, gt=0)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    max_uses: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None


class PromoOut(BaseModel):
    id: str
    code: str
    description: Optional[str] = None
    bonus_amount: int
    valid_from: datetime
    valid_to: datetime
    max_uses: Optional[int] = None
    used_count: int
    is_active: bool
    created_at: datetime
    unique_users: Optional[int] = None

    class Config:
        from_attributes = True


class PromoListResponse(BaseModel):
    promo_codes: List[PromoOut]
    total: int


class PromoUsageOut(BaseModel):
    id: str
    user_id: str
    user_phone: Optional[str] = None
    user_name: Optional[str] = None
    used_at: datetime


class PromoDetailResponse(PromoOut):
    usages: List[PromoUsageOut] = []
