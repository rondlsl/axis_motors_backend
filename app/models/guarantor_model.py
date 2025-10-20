from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
import uuid

from app.dependencies.database.database import Base


class GuarantorRequestStatus(enum.Enum):
    PENDING = "pending"  # Ожидает ответа гаранта
    ACCEPTED = "accepted"  # Принято гарантом
    REJECTED = "rejected"  # Отклонено гарантом
    EXPIRED = "expired"  # Истекло время ответа


class VerificationStatus(enum.Enum):
    NOT_VERIFIED = "not_verified"  # Не проверено администратором
    VERIFIED = "verified"  # Проверено и одобрено администратором
    REJECTED_BY_ADMIN = "rejected"  # Отклонено администратором


class GuarantorRequest(Base):
    """Заявки на гарантов"""
    __tablename__ = "guarantor_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    requestor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)  # Кто запрашивает гаранта
    guarantor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)  # Кого просят быть гарантом (может быть NULL пока не зарегистрирован)
    guarantor_phone = Column(String, nullable=True)  # Номер телефона гаранта (для незарегистрированных)
    status = Column(ENUM(GuarantorRequestStatus), default=GuarantorRequestStatus.PENDING)
    verification_status = Column(String, default="not_verified")  # Статус проверки администратором: not_verified, verified, rejected
    reason = Column(Text, nullable=True)  # Причина отказа в регистрации (если применимо)
    admin_notes = Column(Text, nullable=True)  # Заметки администратора при проверке
    created_at = Column(DateTime, default=datetime.utcnow)
    responded_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)  # Когда проверено администратором
    
    # Relationships
    requestor = relationship("User", foreign_keys=[requestor_id], back_populates="sent_guarantor_requests")
    guarantor = relationship("User", foreign_keys=[guarantor_id], back_populates="received_guarantor_requests")

    @property
    def sid(self) -> str:
        from app.utils.short_id import uuid_to_sid
        return uuid_to_sid(self.id)


class Guarantor(Base):
    """Активные отношения гарант-клиент"""
    __tablename__ = "guarantors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    guarantor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)  # Кто является гарантом
    client_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)  # За кого отвечает
    request_id = Column(UUID(as_uuid=True), ForeignKey("guarantor_requests.id"), nullable=False)  # Ссылка на заявку
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    deactivated_at = Column(DateTime, nullable=True)
    
    # Relationships
    guarantor_user = relationship("User", foreign_keys=[guarantor_id], back_populates="guaranteeing_for")
    client_user = relationship("User", foreign_keys=[client_id], back_populates="guaranteed_by")
    original_request = relationship("GuarantorRequest")
    contract_signatures = relationship("UserContractSignature", foreign_keys="[UserContractSignature.guarantor_relationship_id]", back_populates="guarantor_relationship")

    @property
    def sid(self) -> str:
        from app.utils.short_id import uuid_to_sid
        return uuid_to_sid(self.id)
