"""
ErrorLog model for storing error logs sent to Telegram
"""
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid

from app.dependencies.database.base import Base


class ErrorLog(Base):
    __tablename__ = "error_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    error_type = Column(String(255), nullable=False) 
    message = Column(Text, nullable=True)  
    endpoint = Column(String(500), nullable=True) 
    method = Column(String(10), nullable=True)
    user_id = Column(UUID(as_uuid=True), nullable=True) 
    user_phone = Column(String(50), nullable=True) 
    traceback = Column(Text, nullable=True) 
    context = Column(JSONB, nullable=True)  
    source = Column(String(50), nullable=False, default="BACKEND")  
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
