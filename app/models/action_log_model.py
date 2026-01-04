import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.dependencies.database.database import Base
from app.utils.time_utils import get_local_time
from app.utils.short_id import uuid_to_sid

class ActionLog(Base):
    __tablename__ = "action_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String(128), nullable=False)
    entity_type = Column(String(64), nullable=True)
    entity_id = Column(UUID(as_uuid=True), nullable=True)
    details = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=get_local_time, nullable=False, index=True)

    actor = relationship("User", foreign_keys=[actor_id])

    @property
    def sid(self) -> str:
        return uuid_to_sid(self.id)
