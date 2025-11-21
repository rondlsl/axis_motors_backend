import uuid
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text, Enum, BigInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.dependencies.database.database import Base
from app.utils.time_utils import get_local_time


class SupportChatStatus:
    NEW = "new"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class SupportChat(Base):
    __tablename__ = "support_chats"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_telegram_id = Column(BigInteger, nullable=False, index=True)
    user_telegram_username = Column(String(255), nullable=True)
    user_name = Column(String(255), nullable=False)  
    user_phone = Column(String(20), nullable=False, index=True)  
    azv_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), default=SupportChatStatus.NEW, nullable=False, index=True)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=get_local_time, nullable=False)
    updated_at = Column(DateTime, default=get_local_time, onupdate=get_local_time, nullable=False)
    closed_at = Column(DateTime, nullable=True)
    azv_user = relationship("User", foreign_keys=[azv_user_id], back_populates="support_chats_as_client")
    assigned_support = relationship("User", foreign_keys=[assigned_to], back_populates="support_chats_as_support")
    messages = relationship("SupportMessage", back_populates="chat", cascade="all, delete-orphan")

    @property
    def sid(self) -> str:
        from app.utils.short_id import uuid_to_sid
        return uuid_to_sid(self.id)
    
    @property
    def is_active(self) -> bool:
        return self.status in [SupportChatStatus.NEW, SupportChatStatus.IN_PROGRESS, SupportChatStatus.RESOLVED]
    
    @property
    def message_count(self) -> int:
        return len(self.messages) if self.messages else 0
