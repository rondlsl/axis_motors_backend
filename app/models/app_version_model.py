import uuid
from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID

from app.dependencies.database.database import Base
from app.utils.time_utils import get_local_time


class AppVersion(Base):
    __tablename__ = "app_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    android_version = Column(String(64), nullable=True)
    ios_version = Column(String(64), nullable=True)
    ios_link = Column(String(512), nullable=True)
    android_link = Column(String(512), nullable=True)
    created_at = Column(DateTime, nullable=False, default=get_local_time)
    updated_at = Column(DateTime, nullable=False, default=get_local_time)

    def update_timestamp(self):
        self.updated_at = get_local_time()

