import enum

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Numeric, ForeignKey, Enum
from datetime import datetime

from sqlalchemy.orm import relationship

from app.dependencies.database.database import Base


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False)
    discount_percent = Column(Numeric(5, 2), nullable=False, default=15)  # можно менять, но сейчас =15%
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class UserPromoStatus(enum.Enum):
    ACTIVATED = "activated"
    USED = "used"


class UserPromoCode(Base):
    __tablename__ = "user_promo_codes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id"), nullable=False)
    status = Column(Enum(UserPromoStatus), default=UserPromoStatus.ACTIVATED, nullable=False)
    activated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    used_at = Column(DateTime, nullable=True)

    promo = relationship("PromoCode")
    user = relationship("User", back_populates="promos")
