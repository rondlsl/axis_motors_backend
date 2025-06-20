from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
import enum
from datetime import datetime
from app.dependencies.database.database import Base


# New model to store user actions on a rental
class ActionType(enum.Enum):
    OPEN_VEHICLE = "open_vehicle"
    CLOSE_VEHICLE = "close_vehicle"
    GIVE_KEY = "give_key"
    TAKE_KEY = "take_key"


class RentalAction(Base):
    __tablename__ = "rental_actions"

    id = Column(Integer, primary_key=True, index=True)
    rental_id = Column(Integer, ForeignKey("rental_history.id"), nullable=False)
    rental = relationship("RentalHistory", back_populates="actions")

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User")

    action_type = Column(Enum(ActionType), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
