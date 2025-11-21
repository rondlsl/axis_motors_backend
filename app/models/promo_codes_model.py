import enum
import uuid

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Numeric, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID

from sqlalchemy.orm import relationship

from app.dependencies.database.database import Base
from app.utils.time_utils import get_local_time


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    code = Column(String, unique=True, nullable=False)
    discount_percent = Column(Numeric(5, 2), nullable=False, default=15)  # можно менять, но сейчас =15%
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=get_local_time, nullable=False)

    @property
    def sid(self) -> str:
        from app.utils.short_id import uuid_to_sid
        return uuid_to_sid(self.id)


class UserPromoStatus(enum.Enum):
    ACTIVATED = "activated"
    USED = "used"


class UserPromoCode(Base):
    __tablename__ = "user_promo_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    promo_code_id = Column(UUID(as_uuid=True), ForeignKey("promo_codes.id"), nullable=False)
    status = Column(Enum(UserPromoStatus), default=UserPromoStatus.ACTIVATED, nullable=False)
    activated_at = Column(DateTime, default=get_local_time, nullable=False)
    used_at = Column(DateTime, nullable=True)

    promo = relationship("PromoCode")
    user = relationship("User", back_populates="promos")

    @property
    def sid(self) -> str:
        from app.utils.short_id import uuid_to_sid
        return uuid_to_sid(self.id)
