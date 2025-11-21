from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from app.dependencies.database.database import Base
from app.utils.time_utils import get_local_time


class TokenRecord(Base):
    __tablename__ = "auth_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_type = Column(String(20), nullable=False, index=True)  # 'access' | 'refresh'
    token = Column(String, nullable=False, unique=True, index=True)
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=get_local_time)
    updated_at = Column(DateTime, nullable=False, default=get_local_time)

    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("token", name="uq_auth_tokens_token"),
    )


