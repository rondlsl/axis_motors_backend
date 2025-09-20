from enum import Enum
from sqlalchemy import Column, Integer, String, DateTime, Enum as SAEnum, ForeignKey
from sqlalchemy.orm import relationship
from app.dependencies.database.database import Base


class ApplicationStatus(Enum):
    PENDING = "pending"  # На рассмотрении
    APPROVED = "approved"  # Одобрено
    REJECTED = "rejected"  # Отклонено


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Статус проверки финансистом
    financier_status = Column(SAEnum(ApplicationStatus), default=ApplicationStatus.PENDING)
    financier_approved_at = Column(DateTime, nullable=True)
    financier_rejected_at = Column(DateTime, nullable=True)
    financier_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Статус проверки МВД
    mvd_status = Column(SAEnum(ApplicationStatus), default=ApplicationStatus.PENDING)
    mvd_approved_at = Column(DateTime, nullable=True)
    mvd_rejected_at = Column(DateTime, nullable=True)
    mvd_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    # Связи
    user = relationship("User", foreign_keys=[user_id], back_populates="application")
    financier = relationship("User", foreign_keys=[financier_user_id])
    mvd_user = relationship("User", foreign_keys=[mvd_user_id])
