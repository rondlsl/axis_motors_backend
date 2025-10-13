"""
Модели для работы с договорами и их подписанием
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
import uuid

from app.dependencies.database.base import Base


class ContractType(str, enum.Enum):
    """Типы договоров"""
    # Основные договоры при регистрации
    USER_AGREEMENT = "user_agreement"  # Пользовательское соглашение
    MAIN_CONTRACT = "main_contract"  # Договор присоединения
    
    # Приложения (1-7)
    APPENDIX_1 = "appendix_1"
    APPENDIX_2 = "appendix_2"
    APPENDIX_3 = "appendix_3"
    APPENDIX_4 = "appendix_4"
    APPENDIX_5 = "appendix_5"
    APPENDIX_6 = "appendix_6"
    APPENDIX_7 = "appendix_7"
    
    # Договоры при аренде
    APPENDIX_7_START = "appendix_7_start"  # Приложение №7 (1) - при начале аренды
    APPENDIX_7_END = "appendix_7_end"  # Приложение №7 (2) - при завершении аренды
    
    # Договоры гаранта
    GUARANTOR_CONTRACT = "guarantor_contract"  # Договор гаранта
    GUARANTOR_MAIN_CONTRACT = "guarantor_main_contract"  # Основной договор для гаранта


class ContractFile(Base):
    """Файлы договоров (шаблоны)"""
    __tablename__ = "contract_files"

    id = Column(Integer, primary_key=True, index=True)
    contract_type = Column(SQLEnum(ContractType), nullable=False)
    file_path = Column(String, nullable=False)
    file_name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    signatures = relationship("UserContractSignature", back_populates="contract_file")


class UserContractSignature(Base):
    """Подписи пользователей на договорах"""
    __tablename__ = "user_contract_signatures"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    contract_file_id = Column(Integer, ForeignKey("contract_files.id"), nullable=False)
    rental_id = Column(UUID(as_uuid=True), ForeignKey("rental_history.id"), nullable=True)  # Для договоров аренды
    guarantor_relationship_id = Column(Integer, ForeignKey("guarantors.id"), nullable=True)  # Для договоров гаранта
    
    digital_signature = Column(String, nullable=False)  # Цифровая подпись пользователя
    signed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Дополнительная информация
    contract_data = Column(String, nullable=True)  # JSON с данными, которые были в договоре на момент подписания
    
    # Relationships
    user = relationship("User", back_populates="signed_contracts")
    contract_file = relationship("ContractFile", back_populates="signatures")
    rental = relationship("RentalHistory", foreign_keys=[rental_id])
    guarantor_relationship = relationship("Guarantor", foreign_keys=[guarantor_relationship_id])

