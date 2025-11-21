from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum
import uuid
from app.dependencies.database.database import Base
from app.utils.short_id import uuid_to_sid
from app.utils.time_utils import get_local_time


# New model to store user actions on a rental
class ActionType(enum.Enum):
    OPEN_VEHICLE = "open_vehicle"
    CLOSE_VEHICLE = "close_vehicle"
    GIVE_KEY = "give_key"
    TAKE_KEY = "take_key"
    LOCK_ENGINE = "lock_engine"
    UNLOCK_ENGINE = "unlock_engine"


class RentalAction(Base):
    __tablename__ = "rental_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    rental_id = Column(UUID(as_uuid=True), ForeignKey("rental_history.id"), nullable=False)
    rental = relationship("RentalHistory", back_populates="actions")

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    user = relationship("User")

    action_type = Column(Enum(ActionType), nullable=False)
    timestamp = Column(DateTime, default=get_local_time, nullable=False)
    
    @property
    def sid(self) -> str:
        """Короткий ID для использования в API"""
        return uuid_to_sid(self.id)
