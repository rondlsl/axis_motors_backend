from pydantic import BaseModel, field_validator, Field
from datetime import datetime
from typing import Optional, List
from enum import Enum


class GuarantorRequestStatusSchema(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ErrorResponseSchema(BaseModel):
    """Унифицированный ответ об ошибке для Swagger"""
    detail: str


class VerificationStatusSchema(str, Enum):
    NOT_VERIFIED = "not_verified"
    VERIFIED = "verified"
    REJECTED_BY_ADMIN = "rejected_by_admin"


class AutoClassSchema(str, Enum):
    A = "A"  # До 25 млн
    B = "B"  # До 40 млн  
    C = "C"  # 40+ млн


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
    contract_type: str = Field(..., description="Тип договора для подписания", example="guarantor", enum=["guarantor", "sublease"])
    guarantor_relationship_id: int = Field(..., description="ID связи гарант-клиент", example=1)


class ContractUploadSchema(BaseModel):
    """Схема для загрузки договора (только админ)"""
    contract_type: str = Field(..., description="Тип договора: 'guarantor' или 'sublease'", example="guarantor")
    file_content: str = Field(..., description="Содержимое файла в формате base64", example="JVBERi0xLjQKJcfsj6IKNSAwIG9iago8PAovVHlwZSAvUGFnZQovUGFyZW50IDMgMCBSCi9SZXNvdXJjZXMgPDwKL0ZvbnQgPDwKL0YxIDIgMCBSCj4+Cj4+Ci9NZWRpYUJveCBbMCAwIDU5NSA4NDJdCi9Db250ZW50cyA0IDAgUgo+PgplbmRvYmoK")


class ContractDownloadSchema(BaseModel):
    """Схема для просмотра договора"""
    id: int = Field(..., description="ID договора", example=1)
    contract_type: str = Field(..., description="Тип договора", example="guarantor")
    file_name: str = Field(..., description="Имя файла", example="guarantor_contract.pdf")
    file_content: str = Field(..., description="Содержимое файла в base64", example="JVBERi0xLjQKJcfsj6IKNSAwIG9iago8PAovVHlwZSAvUGFnZQovUGFyZW50IDMgMCBSCi9SZXNvdXJjZXMgPDwKL0ZvbnQgPDwKL0YxIDIgMCBSCj4+Cj4+Ci9NZWRpYUJveCBbMCAwIDU5NSA4NDJdCi9Db250ZW50cyA0IDAgUgo+PgplbmRvYmoK")
    uploaded_at: datetime = Field(..., description="Дата загрузки", example="2024-01-15T10:30:00Z")
    is_active: bool = Field(..., description="Активен ли договор", example=True)


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


class SimpleGuarantorSchema(BaseModel):
    """Упрощенная схема для активного гаранта"""
    id: int
    name: str
    phone: str
    contract_signed: bool
    sublease_contract_signed: bool
    created_at: datetime


class SimpleClientSchema(BaseModel):
    """Упрощенная схема для клиента"""
    id: int
    name: str
    phone: str
    contract_signed: bool
    sublease_contract_signed: bool
    created_at: datetime


class IncomingRequestSchema(BaseModel):
    """Схема входящей заявки для 'Я гарант'"""
    id: int
    requestor_name: str
    requestor_phone: str
    reason: Optional[str]
    created_at: datetime


class AdminApproveGuarantorSchema(BaseModel):
    """Схема для одобрения заявки гаранта администратором"""
    auto_classes: List[AutoClassSchema]  # Классы авто которые можно присвоить клиенту
    admin_notes: Optional[str] = None


class AdminRejectGuarantorSchema(BaseModel):
    """Схема для отклонения заявки гаранта администратором"""
    admin_notes: str  # Причина отклонения


class GuarantorRequestAdminSchema(BaseModel):
    """Схема заявки гаранта для администратора"""
    id: int
    requestor_id: int
    requestor_name: Optional[str]
    requestor_phone: str
    guarantor_id: Optional[int]
    guarantor_name: Optional[str]
    guarantor_phone: Optional[str]
    status: GuarantorRequestStatusSchema
    verification_status: VerificationStatusSchema
    reason: Optional[str]
    admin_notes: Optional[str]
    created_at: datetime
    responded_at: Optional[datetime]
    verified_at: Optional[datetime]

    class Config:
        from_attributes = True


# ===== Detailed response schemas for Swagger =====

class InviteGuarantorResponseSchema(BaseModel):
    message: str
    user_exists: bool
    request_id: int
    sms_result: Optional[dict] = None
    guarantor_name: Optional[str] = None


class AcceptGuarantorResponseSchema(BaseModel):
    message: str
    guarantor_relationship_id: int


class MessageResponseSchema(BaseModel):
    message: str


class LinkPendingRequestsResponseSchema(BaseModel):
    message: str
    linked_requests: int


class GuarantorRelationshipItemSchema(BaseModel):
    id: int
    created_at: datetime
    contract_signed: bool
    client_id: Optional[int] = None
    guarantor_id: Optional[int] = None


class GuarantorRelationshipsSchema(BaseModel):
    user_id: int
    user_phone: str

    class SummarySchema(BaseModel):
        requests_sent: int
        requests_received: int
        active_clients: int
        active_guarantors: int

    class SentRequestItemSchema(BaseModel):
        id: int
        guarantor_phone: Optional[str] = None
        guarantor_name: Optional[str] = None
        guarantor_id: Optional[int] = None
        status: str
        created_at: datetime

    class ReceivedRequestItemSchema(BaseModel):
        id: int
        requestor_id: int
        status: str
        created_at: datetime

    class DetailsSchema(BaseModel):
        sent_requests: List["GuarantorRelationshipsSchema.SentRequestItemSchema"]
        received_requests: List["GuarantorRelationshipsSchema.ReceivedRequestItemSchema"]
        my_clients: List[GuarantorRelationshipItemSchema]
        my_guarantors: List[GuarantorRelationshipItemSchema]

    summary: SummarySchema
    details: DetailsSchema


class GuarantorInfoSchema(BaseModel):
    title: str
    description: str
    details: List[str]