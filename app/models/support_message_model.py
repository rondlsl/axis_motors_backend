from datetime import datetime
import uuid
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text, Enum, BigInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.dependencies.database.database import Base


class SupportMessageSenderType:
    CLIENT = "client"
    SUPPORT = "support"
    SYSTEM = "system"


class SupportMessage(Base):
    __tablename__ = "support_messages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    chat_id = Column(UUID(as_uuid=True), ForeignKey("support_chats.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_type = Column(String(20), nullable=False, index=True)  # client, support, system
    sender_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    message_text = Column(Text, nullable=False)
    telegram_message_id = Column(BigInteger, nullable=True)  # ID сообщения в Telegram
    telegram_chat_id = Column(BigInteger, nullable=True)    # ID чата в Telegram
    is_from_bot = Column(Boolean, default=False, nullable=False)  # Отправлено через бота
    is_read = Column(Boolean, default=False, nullable=False)     # Прочитано получателем
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    chat = relationship("SupportChat", back_populates="messages")
    sender_user = relationship("User", back_populates="support_messages")

    @property
    def sid(self) -> str:
        from app.utils.short_id import uuid_to_sid
        return uuid_to_sid(self.id)
    
    @property
    def sender_name(self) -> str:
        if self.sender_type == SupportMessageSenderType.CLIENT:
            return "Клиент"
        elif self.sender_type == SupportMessageSenderType.SUPPORT and self.sender_user:
            return f"Поддержка ({self.sender_user.first_name})"
        elif self.sender_type == SupportMessageSenderType.SYSTEM:
            return "Система"
        return "Неизвестно"
