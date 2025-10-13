from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from app.models.user_model import UserRole, AutoClass


class GuarantorRequestAdminSchema(BaseModel):
    """Схема заявки гаранта для админа"""
    id: int
    guarantor_id: uuid.UUID
    requestor_id: uuid.UUID
    guarantor_name: str
    guarantor_phone: str
    requestor_name: str
    requestor_phone: str
    verification_status: str
    created_at: str
    verified_at: Optional[str] = None
    admin_notes: Optional[str] = None


class AdminApproveGuarantorSchema(BaseModel):
    """Схема одобрения заявки гаранта администратором"""
    auto_classes: List[AutoClass] = Field(..., description="Список классов автомобилей для присвоения")
    admin_notes: Optional[str] = Field(None, description="Заметки администратора")


class AdminRejectGuarantorSchema(BaseModel):
    """Схема отклонения заявки гаранта администратором"""
    rejection_reason: str = Field(..., description="Причина отклонения")
    admin_notes: Optional[str] = Field(None, description="Заметки администратора")
