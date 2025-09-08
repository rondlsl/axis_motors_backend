from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional, List
from enum import Enum


class GuarantorRequestStatusSchema(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class GuarantorInfoSchema(BaseModel):
    """Схема для указания данных гаранта"""
    full_name: str
    phone_number: str

    @field_validator('phone_number')
    @classmethod
    def validate_phone(cls, v):
        if not v.isdigit():
            raise ValueError('Phone number must contain only digits')
        if len(v) < 10 or len(v) > 15:
            raise ValueError('Phone number must be between 10 and 15 digits')
        return v

    @field_validator('full_name')
    @classmethod
    def validate_full_name(cls, v):
        if len(v.strip()) < 2:
            raise ValueError('Full name must be at least 2 characters')
        # Проверяем, что имя состоит из минимум двух слов
        name_parts = v.strip().split()
        if len(name_parts) < 2:
            raise ValueError('Full name must contain at least first name and last name')
        return v.strip()


class GuarantorRequestCreateSchema(BaseModel):
    """Схема для создания заявки на гаранта"""
    guarantor_info: GuarantorInfoSchema
    reason: Optional[str] = None  # Причина отказа в регистрации


class GuarantorRequestResponseSchema(BaseModel):
    """Ответ на заявку гаранта"""
    accept: bool
    rejection_reason: Optional[str] = None


class GuarantorRequestSchema(BaseModel):
    """Схема заявки на гаранта"""
    id: int
    requestor_id: int
    guarantor_id: int
    status: GuarantorRequestStatusSchema
    reason: Optional[str]
    created_at: datetime
    responded_at: Optional[datetime]
    
    # Информация о запрашивающем
    requestor_name: Optional[str]
    requestor_phone: str
    
    # Информация о гаранте
    guarantor_name: Optional[str]
    guarantor_phone: str
    
    class Config:
        from_attributes = True


class GuarantorSchema(BaseModel):
    """Схема активного гаранта"""
    id: int
    guarantor_id: int
    client_id: int
    contract_signed: bool
    sublease_contract_signed: bool
    is_active: bool
    created_at: datetime
    
    # Информация о гаранте
    guarantor_name: Optional[str]
    guarantor_phone: str
    
    # Информация о клиенте
    client_name: Optional[str]
    client_phone: str
    
    class Config:
        from_attributes = True


class UserGuarantorInfoSchema(BaseModel):
    """Схема информации о гарантах пользователя"""
    # Заявки, которые я отправил
    sent_requests: List[GuarantorRequestSchema]
    
    # Заявки, которые я получил
    received_requests: List[GuarantorRequestSchema]
    
    # Люди, за которых я ручаюсь
    my_clients: List[GuarantorSchema]
    
    # Мои гаранты
    my_guarantors: List[GuarantorSchema]


class ContractSignSchema(BaseModel):
    """Схема для подписания договора"""
    contract_type: str  # "guarantor" или "sublease"
    guarantor_relationship_id: int


class ContractFileSchema(BaseModel):
    """Схема файла договора"""
    id: int
    contract_type: str
    file_name: str
    file_path: str
    uploaded_at: datetime
    is_active: bool
    
    class Config:
        from_attributes = True


class ContractListSchema(BaseModel):
    """Схема списка договоров"""
    guarantor_contracts: List[ContractFileSchema]
    sublease_contracts: List[ContractFileSchema]


class RejectUserWithGuarantorSchema(BaseModel):
    """Схема для отклонения пользователя с предложением гаранта"""
    user_id: int
    rejection_reason: str
    sms_message: str


class CheckUserEligibilitySchema(BaseModel):
    """Схема проверки платежеспособности пользователя"""
    phone_number: str


class UserEligibilityResultSchema(BaseModel):
    """Результат проверки платежеспособности"""
    user_exists: bool
    user_id: Optional[int]
    is_eligible: bool
    has_car_access: bool
    user_name: Optional[str]
    reason: Optional[str]  # Причина, если не подходит
