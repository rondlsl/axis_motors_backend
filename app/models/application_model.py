from enum import Enum
import uuid
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, ENUM
from sqlalchemy.orm import relationship
from app.dependencies.database.database import Base


class ApplicationStatus(Enum):
    PENDING = "pending"  # На рассмотрении
    APPROVED = "approved"  # Одобрено
    REJECTED = "rejected"  # Отклонено


class Application(Base):
    __tablename__ = "applications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # Статус проверки финансистом
    financier_status = Column(ENUM(ApplicationStatus), default=ApplicationStatus.PENDING)
    financier_approved_at = Column(DateTime, nullable=True)
    financier_rejected_at = Column(DateTime, nullable=True)
    financier_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    
    # Статус проверки МВД
    mvd_status = Column(ENUM(ApplicationStatus), default=ApplicationStatus.PENDING)
    mvd_approved_at = Column(DateTime, nullable=True)
    mvd_rejected_at = Column(DateTime, nullable=True)
    mvd_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    
    # Unified reason for rejection by either financier or MVD
    reason = Column(String, nullable=True)
    
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    # Связи
    user = relationship("User", foreign_keys=[user_id], back_populates="application")
    financier = relationship("User", foreign_keys=[financier_user_id])
    mvd_user = relationship("User", foreign_keys=[mvd_user_id])

    @property
    def sid(self) -> str:
        """Short ID for API responses derived from UUID."""
        from app.utils.short_id import uuid_to_sid
        return uuid_to_sid(self.id)
