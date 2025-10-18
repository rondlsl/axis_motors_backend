"""
Схемы для работы с договорами
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import uuid

from app.models.contract_model import ContractType


class ContractFileUpload(BaseModel):
    """Схема для загрузки договора (админ)"""
    contract_type: ContractType = Field(..., description="Тип договора")
    file_content: str = Field(..., description="Содержимое файла в base64 или data URL")

class ContractFileResponse(BaseModel):
    """Схема ответа с информацией о договоре"""
    id: str
    contract_type: ContractType
    file_name: str
    is_active: bool
    uploaded_at: datetime
    file_url: Optional[str] = None  # URL для скачивания


class SignContractRequest(BaseModel):
    """Схема для подписания договора"""
    contract_type: ContractType = Field(..., description="Тип договора")
    rental_id: Optional[uuid.UUID] = Field(None, description="ID аренды (для договоров аренды)")
    guarantor_relationship_id: Optional[str] = Field(None, description="ID связи гарант-клиент (для договоров гаранта)")


class SignContractByTypeRequest(BaseModel):
    """Схема для подписания договора по типу"""
    contract_type: ContractType = Field(..., description="Тип договора")
    rental_id: Optional[uuid.UUID] = Field(None, description="ID аренды (для договоров аренды)")
    guarantor_relationship_id: Optional[str] = Field(None, description="ID связи гарант-клиент (для договоров гаранта)")


class UserSignatureResponse(BaseModel):
    """Схема ответа с информацией о подписи"""
    id: str
    user_id: str
    contract_file_id: str
    contract_type: ContractType
    digital_signature: str
    signed_at: datetime
    rental_id: Optional[str] = None
    guarantor_relationship_id: Optional[str] = None
    already_signed: Optional[bool] = None


class UserContractsResponse(BaseModel):
    """Схема для списка подписанных договоров пользователя"""
    registration_contracts: List[UserSignatureResponse] = Field(default_factory=list, description="Договоры при регистрации")
    rental_contracts: List[UserSignatureResponse] = Field(default_factory=list, description="Договоры при аренде")
    guarantor_contracts: List[UserSignatureResponse] = Field(default_factory=list, description="Договоры гаранта")


class ContractRequirements(BaseModel):
    """Схема для проверки требований к подписанию договоров"""
    user_id: str
    
    # Договоры при регистрации
    user_agreement_signed: bool = Field(..., description="Подписано ли пользовательское соглашение")
    main_contract_signed: bool = Field(..., description="Подписан ли договор присоединения")
    
    # Статус регистрации
    can_proceed_to_rental: bool = Field(..., description="Может ли пользователь перейти к аренде")


class RentalContractStatus(BaseModel):
    """Схема для статуса договоров при аренде"""
    rental_id: str
    appendix_7_1_signed: bool = Field(..., description="Подписано ли приложение 7.1")
    appendix_7_2_signed: bool = Field(..., description="Подписано ли приложение 7.2")


class GuarantorContractStatus(BaseModel):
    """Схема для статуса договоров гаранта"""
    guarantor_relationship_id: str
    guarantor_contract_signed: bool = Field(..., description="Подписан ли договор гаранта")
    guarantor_main_contract_signed: bool = Field(..., description="Подписан ли основной договор для гаранта")
    can_guarantee: bool = Field(..., description="Может ли выступать гарантом")

