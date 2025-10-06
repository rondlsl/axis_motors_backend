from sqlalchemy import Column, Integer, String, DateTime, Boolean
from app.dependencies.database.database import Base


class VerificationCode(Base):
    __tablename__ = "verification_codes"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(50), nullable=True)
    email = Column(String(50), nullable=True)
    code = Column(String(10), nullable=False)
    purpose = Column(String(50), nullable=False)
    is_used = Column(Boolean, nullable=False, default=False, server_default="false")
    expires_at = Column(DateTime, nullable=False)


