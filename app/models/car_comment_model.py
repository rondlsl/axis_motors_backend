from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.dependencies.database.database import Base


class CarComment(Base):
    __tablename__ = "car_comments"

    id = Column(Integer, primary_key=True, index=True)
    car_id = Column(Integer, ForeignKey("cars.id"), nullable=False)
    author_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    comment = Column(Text, nullable=False)
    is_internal = Column(Boolean, default=True, nullable=False)  # Комментарии видны только механикам и админам
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    car = relationship("Car", back_populates="comments")
    author = relationship("User", back_populates="car_comments")


