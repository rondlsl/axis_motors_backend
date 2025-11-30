import uuid
from sqlalchemy import Column, String, Boolean, DateTime, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.dependencies.database.database import Base
from app.utils.time_utils import get_local_time


class UserDevice(Base):
    __tablename__ = "user_devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    device_id = Column(String(128), nullable=True, unique=True)
    fcm_token = Column(String, nullable=False, unique=True)
    platform = Column(String(32), nullable=True)
    model = Column(String(128), nullable=True)
    os_version = Column(String(64), nullable=True)
    app_version = Column(String(32), nullable=True)
    last_ip = Column(String(64), nullable=True)
    last_lat = Column(Float, nullable=True)
    last_lng = Column(Float, nullable=True)
    last_active_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=get_local_time)
    updated_at = Column(DateTime, nullable=False, default=get_local_time)

    user = relationship("User", back_populates="devices")

    def update_timestamp(self):
        self.updated_at = get_local_time()

