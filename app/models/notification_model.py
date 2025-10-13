from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.dependencies.database.database import Base
from app.push.enums import NotificationStatus


class Notification(Base):
    __tablename__ = "notifications"

    # Уникальный айди уведомления
    id = Column(Integer, primary_key=True, index=True)
    # Для какого пользователя
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # Заголовок и тело
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    # Когда отправлено
    sent_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Прочитано?
    is_read = Column(Boolean, default=False, nullable=False)
    # Статус уведомления
    status = Column(Enum(NotificationStatus), nullable=True)

    user = relationship("User", back_populates="notifications")
