import uuid

from sqlalchemy import (
    Column, Integer, String, DateTime, Boolean, UniqueConstraint,
    ForeignKey, CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.dependencies.database.database import Base
from app.utils.time_utils import get_local_time


class BonusPromoCode(Base):
    """
    Бонусные промокоды — начисляют фиксированную сумму на баланс.
    Пример: код "Damir" → +5000 на баланс.
    """
    __tablename__ = "bonus_promo_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    code = Column(String(64), unique=True, nullable=False, index=True)
    description = Column(String(512), nullable=True)
    bonus_amount = Column(Integer, nullable=False)
    valid_from = Column(DateTime, nullable=False)
    valid_to = Column(DateTime, nullable=False)
    max_uses = Column(Integer, nullable=True)       # NULL = безлимит
    used_count = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=get_local_time)

    usages = relationship("BonusPromoUsage", back_populates="promo_code", lazy="dynamic")

    __table_args__ = (
        CheckConstraint("bonus_amount > 0", name="ck_bonus_promo_amount_positive"),
        CheckConstraint("valid_to > valid_from", name="ck_bonus_promo_dates_order"),
    )

    @property
    def sid(self) -> str:
        from app.utils.short_id import uuid_to_sid
        return uuid_to_sid(self.id)


class BonusPromoUsage(Base):
    """
    Журнал использования бонусных промокодов.
    Уникальный constraint (user_id, promo_code_id) предотвращает повторную активацию.
    """
    __tablename__ = "bonus_promo_usages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    promo_code_id = Column(UUID(as_uuid=True), ForeignKey("bonus_promo_codes.id"), nullable=False, index=True)
    used_at = Column(DateTime, nullable=False, default=get_local_time)

    user = relationship("User")
    promo_code = relationship("BonusPromoCode", back_populates="usages")

    __table_args__ = (
        UniqueConstraint("user_id", "promo_code_id", name="uq_bonus_promo_user_code"),
    )

    @property
    def sid(self) -> str:
        from app.utils.short_id import uuid_to_sid
        return uuid_to_sid(self.id)
