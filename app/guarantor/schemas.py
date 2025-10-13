from pydantic import BaseModel, field_validator, Field
from datetime import datetime
from typing import Optional, List
from enum import Enum
import uuid
from app.schemas.base import SidMixin


class GuarantorRequestStatusSchema(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ErrorResponseSchema(BaseModel):
    """Унифицированный ответ об ошибке для Swagger"""
    detail: str = Field(..., description="Описание ошибки", example="Пользователь не найден")


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
    phone_number: str = Field(..., description="Номер телефона гаранта (только цифры)", example="7777654321", min_length=10, max_length=15)

    @field_validator('phone_number')
    @classmethod
    def validate_phone(cls, v):
        if not v.isdigit():
            raise ValueError('Phone number must contain only digits')
        if len(v) < 10 or len(v) > 15:
            raise ValueError('Phone number must be between 10 and 15 digits')
        return v



class ClientGuarantorRequestItemSchema(SidMixin):
    """Список заявок клиента с детальным статусом"""
    id: int = Field(..., description="ID заявки")
    guarantor_id: Optional[str] = Field(None, description="ID гаранта, если зарегистрирован")
    guarantor_phone: Optional[str] = Field(None, description="Телефон гаранта")
    guarantor_first_name: Optional[str] = Field(None, description="Имя гаранта", example="Петр")
    guarantor_last_name: Optional[str] = Field(None, description="Фамилия гаранта", example="Иванов")
    status: GuarantorRequestStatusSchema = Field(..., description="Статус заявки")
    verification_status: VerificationStatusSchema = Field(..., description="Статус проверки администратором")
    reason: Optional[str] = Field(None, description="Причина запроса")
    admin_notes: Optional[str] = Field(None, description="Заметки администратора")
    created_at: datetime = Field(..., description="Дата создания")
    responded_at: Optional[datetime] = Field(None, description="Дата ответа гаранта")
    verified_at: Optional[datetime] = Field(None, description="Дата проверки админом")


class ClientGuarantorRequestsResponseSchema(BaseModel):
    """Ответ: мои заявки гарантов для клиента"""
    total: int = Field(..., description="Всего заявок")
    items: List[ClientGuarantorRequestItemSchema] = Field(..., description="Список заявок")


class GuarantorRequestCreateSchema(BaseModel):
    """Схема для создания заявки на гаранта"""
    guarantor_info: GuarantorInfoSchema = Field(..., description="Информация о гаранте")
    reason: Optional[str] = Field(None, description="Причина запроса гаранта", example="Нужен гарант для аренды автомобиля", max_length=500)


class GuarantorRequestResponseSchema(BaseModel):
    """Ответ на заявку гаранта"""
    accept: bool = Field(..., description="Принять заявку", example=True)
    rejection_reason: Optional[str] = Field(None, description="Причина отклонения (если accept=false)", example="Не могу быть гарантом", max_length=500)


class GuarantorRequestSchema(SidMixin):
    """Схема заявки на гаранта"""
    id: int
    requestor_id: str
    guarantor_id: str
    status: GuarantorRequestStatusSchema
    reason: Optional[str]
    created_at: datetime
    responded_at: Optional[datetime]
    
    # Информация о запрашивающем
    requestor_first_name: Optional[str]
    requestor_last_name: Optional[str]
    requestor_phone: str
    
    # Информация о гаранте
    guarantor_phone: str
    
    class Config:
        from_attributes = True


class GuarantorSchema(SidMixin):
    """Схема активного гаранта"""
    id: int
    guarantor_id: str
    client_id: str
    contract_signed: bool
    main_contract_signed: bool
    is_active: bool
    created_at: datetime
    
    # Информация о гаранте
    guarantor_phone: str
    
    # Информация о клиенте
    client_first_name: Optional[str]
    client_last_name: Optional[str]
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
    contract_type: str = Field(..., description="Тип договора для подписания", example="guarantor_contract", enum=["guarantor_contract", "guarantor_main_contract"])
    guarantor_relationship_id: int = Field(..., description="ID связи гарант-клиент из списка my_clients", example=8)


class ContractUploadSchema(BaseModel):
    """Схема для загрузки договора (только админ)"""
    contract_type: str = Field(..., description="Тип договора: 'guarantor_contract' или 'guarantor_main_contract'", example="guarantor_contract")
    file_content: str = Field(..., description="Data URL файла (data:application/pdf;base64,...) или base64", example="data:application/pdf;base64,JVBERi0xLjQKJcfsj6IKNSAwIG9iago8PAovVHlwZSAvUGFnZQovUGFyZW50IDMgMCBSCi9SZXNvdXJjZXMgPDwKL0ZvbnQgPDwKL0YxIDIgMCBSCj4+Cj4+Ci9NZWRpYUJveCBbMCAwIDU5NSA4NDJdCi9Db250ZW50cyA0IDAgUgo+PgplbmRvYmoK")


class ContractDownloadSchema(BaseModel):
    """Схема для просмотра договора"""
    id: int = Field(..., description="ID договора", example=1)
    contract_type: str = Field(..., description="Тип договора", example="guarantor_contract")
    file_name: str = Field(..., description="Имя файла", example="guarantor_contract.pdf")
    file_url: str = Field(..., description="Прямая ссылка на файл", example="https://api.azvmotors.kz/contracts/guarantor_a1b2c3d4.pdf")
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
    guarantor_main_contracts: List[ContractFileSchema]


class RejectUserWithGuarantorSchema(SidMixin):
    """Схема для отклонения пользователя с предложением гаранта"""
    user_id: str
    rejection_reason: str
    sms_message: str


class CheckUserEligibilitySchema(BaseModel):
    """Схема проверки платежеспособности пользователя"""
    phone_number: str


class UserEligibilityResultSchema(SidMixin):
    """Результат проверки платежеспособности"""
    user_exists: bool
    user_id: Optional[str]
    is_eligible: bool
    has_car_access: bool
    user_first_name: Optional[str]
    user_last_name: Optional[str]
    reason: Optional[str]  # Причина, если не подходит


class SimpleGuarantorSchema(BaseModel):
    """Упрощенная схема для активного гаранта"""
    id: int = Field(..., description="ID связи гарант-клиент", example=1)
    phone: str = Field(..., description="Номер телефона гаранта", example="7777654321")
    first_name: Optional[str] = Field(None, description="Имя гаранта", example="Петр")
    last_name: Optional[str] = Field(None, description="Фамилия гаранта", example="Иванов")
    contract_signed: bool = Field(..., description="Подписан ли договор гаранта", example=True)
    main_contract_signed: bool = Field(..., description="Подписан ли основной договор гаранта", example=False)
    created_at: datetime = Field(..., description="Дата создания связи", example="2024-01-15T10:30:00Z")


class SimpleClientSchema(BaseModel):
    """Упрощенная схема для клиента"""
    id: int = Field(..., description="ID связи гарант-клиент", example=1)
    first_name: Optional[str] = Field(None, description="Имя клиента", example="Петр")
    last_name: Optional[str] = Field(None, description="Фамилия клиента", example="Иванов")
    phone: str = Field(..., description="Номер телефона клиента", example="7771234567")
    contract_signed: bool = Field(..., description="Подписан ли договор гаранта", example=True)
    main_contract_signed: bool = Field(..., description="Подписан ли основной договор гаранта", example=True)
    created_at: datetime = Field(..., description="Дата создания связи", example="2024-01-15T10:30:00Z")


class IncomingRequestSchema(SidMixin):
    """Схема входящей заявки для 'Я гарант'"""
    id: int = Field(..., description="ID заявки", example=123)
    requestor_id: str = Field(..., description="ID пользователя, который просит быть гарантом", example="VQ6EAOKbQdSnFkRmVUQAAA")
    requestor_first_name: Optional[str] = Field(None, description="Имя пользователя", example="Иван")
    requestor_last_name: Optional[str] = Field(None, description="Фамилия пользователя", example="Петров")
    requestor_phone: str = Field(..., description="Номер телефона пользователя", example="7771234567")
    reason: Optional[str] = Field(None, description="Причина запроса гаранта", example="Нужен гарант для аренды авто")
    created_at: datetime = Field(..., description="Дата создания заявки", example="2024-01-15T10:30:00Z")


class AdminApproveGuarantorSchema(BaseModel):
    """Схема для одобрения заявки гаранта администратором"""
    auto_classes: List[AutoClassSchema] = Field(..., description="Классы авто которые можно присвоить клиенту")
    admin_notes: Optional[str] = Field(None, description="Заметки администратора", example="Одобрено после проверки документов")


class AdminRejectGuarantorSchema(BaseModel):
    """Схема для отклонения заявки гаранта администратором"""
    admin_notes: str = Field(..., description="Причина отклонения", example="Не подходит по возрасту", min_length=10, max_length=500)


class GuarantorRequestAdminSchema(SidMixin):
    """Схема заявки гаранта для администратора"""
    id: int = Field(..., description="ID заявки", example=123)
    requestor_id: str = Field(..., description="ID запрашивающего", example="VQ6EAOKbQdSnFkRmVUQAAA")
    requestor_first_name: Optional[str] = Field(None, description="Имя запрашивающего", example="Петр")
    requestor_last_name: Optional[str] = Field(None, description="Фамилия запрашивающего", example="Иванов")
    requestor_phone: str = Field(..., description="Номер телефона запрашивающего", example="7771234567")
    guarantor_id: Optional[str] = Field(None, description="ID гаранта", example="VQ6EAOKbQdSnFkRmVUQAAA")
    guarantor_phone: Optional[str] = Field(None, description="Номер телефона гаранта", example="7777654321")
    status: GuarantorRequestStatusSchema = Field(..., description="Статус заявки")
    verification_status: VerificationStatusSchema = Field(..., description="Статус верификации")
    reason: Optional[str] = Field(None, description="Причина запроса", example="Нужен гарант для аренды")
    admin_notes: Optional[str] = Field(None, description="Заметки администратора", example="Требует дополнительной проверки")
    created_at: datetime = Field(..., description="Дата создания", example="2024-01-15T10:30:00Z")
    responded_at: Optional[datetime] = Field(None, description="Дата ответа", example="2024-01-15T11:30:00Z")
    verified_at: Optional[datetime] = Field(None, description="Дата верификации", example="2024-01-15T12:00:00Z")

    class Config:
        from_attributes = True


# ===== Detailed response schemas for Swagger =====

class InviteGuarantorResponseSchema(BaseModel):
    message: str = Field(..., description="Сообщение о результате", example="Заявка на гаранта создана успешно")
    user_exists: bool = Field(..., description="Существует ли пользователь в системе", example=True)
    request_id: int = Field(..., description="ID созданной заявки", example=123)
    sms_result: Optional[dict] = Field(None, description="Результат отправки SMS", example={"status": "sent", "message_id": "12345"})


class AcceptGuarantorResponseSchema(BaseModel):
    message: str = Field(..., description="Сообщение о результате", example="Заявка принята. Теперь вам необходимо подписать договор гаранта.")
    guarantor_relationship_id: int = Field(..., description="ID созданной связи гарант-клиент", example=1)


class MessageResponseSchema(BaseModel):
    message: str = Field(..., description="Сообщение о результате операции", example="Операция выполнена успешно")


class LinkPendingRequestsResponseSchema(BaseModel):
    message: str = Field(..., description="Сообщение о результате", example="Связано 2 заявки с вашим номером телефона")
    linked_requests: int = Field(..., description="Количество связанных заявок", example=2)


class GuarantorRelationshipItemSchema(BaseModel):
    id: int = Field(..., description="ID связи гарант-клиент", example=1)
    created_at: datetime = Field(..., description="Дата создания связи", example="2024-01-15T10:30:00Z")
    contract_signed: bool = Field(..., description="Подписан ли договор гаранта", example=True)
    client_id: Optional[str] = Field(None, description="ID клиента", example="VQ6EAOKbQdSnFkRmVUQAAA")
    guarantor_id: Optional[str] = Field(None, description="ID гаранта", example="VQ6EAOKbQdSnFkRmVUQAAA")


class GuarantorRelationshipsSchema(SidMixin):
    user_id: str = Field(..., description="ID текущего пользователя", example="VQ6EAOKbQdSnFkRmVUQAAA")
    user_phone: str = Field(..., description="Номер телефона текущего пользователя", example="7771234567")

    class SummarySchema(BaseModel):
        requests_sent: int = Field(..., description="Количество отправленных заявок", example=2)
        requests_received: int = Field(..., description="Количество полученных заявок", example=1)
        active_clients: int = Field(..., description="Количество активных клиентов", example=1)
        active_guarantors: int = Field(..., description="Количество активных гарантов", example=1)

    class SentRequestItemSchema(BaseModel):
        id: int = Field(..., description="ID заявки", example=123)
        guarantor_phone: Optional[str] = Field(None, description="Номер телефона гаранта", example="7777654321")
        guarantor_id: Optional[str] = Field(None, description="ID гаранта", example="VQ6EAOKbQdSnFkRmVUQAAA")
        status: str = Field(..., description="Статус заявки", example="pending")
        created_at: datetime = Field(..., description="Дата создания заявки", example="2024-01-15T10:30:00Z")

    class ReceivedRequestItemSchema(BaseModel):
        id: int = Field(..., description="ID заявки", example=124)
        requestor_id: str = Field(..., description="ID запрашивающего", example="VQ6EAOKbQdSnFkRmVUQAAA")
        status: str = Field(..., description="Статус заявки", example="accepted")
        created_at: datetime = Field(..., description="Дата создания заявки", example="2024-01-15T10:30:00Z")

    class DetailsSchema(BaseModel):
        sent_requests: List["GuarantorRelationshipsSchema.SentRequestItemSchema"] = Field(..., description="Отправленные заявки")
        received_requests: List["GuarantorRelationshipsSchema.ReceivedRequestItemSchema"] = Field(..., description="Полученные заявки")
        my_clients: List[GuarantorRelationshipItemSchema] = Field(..., description="Мои клиенты")
        my_guarantors: List[GuarantorRelationshipItemSchema] = Field(..., description="Мои гаранты")

    summary: SummarySchema = Field(..., description="Сводная статистика")
    details: DetailsSchema = Field(..., description="Детальная информация")


class GuarantorInfoContentSchema(BaseModel):
    title: str = Field(..., description="Заголовок", example="Что такое Гарант?")
    description: str = Field(..., description="Описание", example="Гарант — лицо, которое в случае ДТП несёт материальную ответственность")
    details: List[str] = Field(..., description="Детальная информация", example=["Гарант - это человек, который берет на себя материальную ответственность за ваши действия"])