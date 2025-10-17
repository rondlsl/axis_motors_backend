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
    # Основные договоры
    GUARANTOR_CONTRACT = "guarantor_contract"  # Договор гаранта
    GUARANTOR_MAIN_CONTRACT = "guarantor_main_contract"  # Основной договор гаранта
    USER_AGREEMENT = "user_agreement"  # Пользовательское соглашение
    CONSENT_TO_DATA_PROCESSING = "consent_to_data_processing"  # Обработка персональных данных
    MAIN_CONTRACT = "main_contract"  # Договор присоединения
    APPENDIX_7_1 = "appendix_7_1"  # Приложение 7.1
    APPENDIX_7_2 = "appendix_7_2"  # Приложение 7.2


class ContractFile(Base):
    """Файлы договоров (шаблоны)"""
    __tablename__ = "contract_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    contract_type = Column(SQLEnum(ContractType), nullable=False)
    file_path = Column(String, nullable=False)
    file_name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    signatures = relationship("UserContractSignature", back_populates="contract_file")

    @property
    def sid(self) -> str:
        from app.utils.short_id import uuid_to_sid
        return uuid_to_sid(self.id)


class UserContractSignature(Base):
    """Подписи пользователей на договорах"""
    __tablename__ = "user_contract_signatures"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    contract_file_id = Column(UUID(as_uuid=True), ForeignKey("contract_files.id"), nullable=False)
    rental_id = Column(UUID(as_uuid=True), ForeignKey("rental_history.id"), nullable=True)  # Для договоров аренды
    guarantor_relationship_id = Column(UUID(as_uuid=True), ForeignKey("guarantors.id"), nullable=True)  # Для договоров гаранта
    
    digital_signature = Column(String, nullable=False)  # Цифровая подпись пользователя
    signed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="signed_contracts")
    contract_file = relationship("ContractFile", back_populates="signatures")
    rental = relationship("RentalHistory", foreign_keys=[rental_id])
    guarantor_relationship = relationship("Guarantor", foreign_keys=[guarantor_relationship_id])

