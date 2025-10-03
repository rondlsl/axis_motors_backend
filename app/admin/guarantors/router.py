from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole, AutoClass
from app.models.guarantor_model import GuarantorRequest
from app.guarantor.sms_utils import send_user_rejection_with_guarantor_sms, send_guarantor_approval_sms
from app.admin.guarantors.schemas import (
    GuarantorRequestAdminSchema, 
    AdminApproveGuarantorSchema, 
    AdminRejectGuarantorSchema
)

guarantors_router = APIRouter(tags=["Admin Guarantors"])


@guarantors_router.get("/requests", response_model=List[GuarantorRequestAdminSchema])
async def get_guarantor_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение всех заявок гарантов для админ панели"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    requests = db.query(GuarantorRequest).all()
    
    result = []
    for request in requests:
        # Получаем данные гаранта
        guarantor = db.query(User).filter(User.id == request.guarantor_id).first()
        guarantor_name = f"{guarantor.first_name or ''} {guarantor.last_name or ''}".strip() if guarantor else "Неизвестно"
        guarantor_phone = guarantor.phone_number if guarantor else ""
        
        # Получаем данные заявителя
        requestor = db.query(User).filter(User.id == request.requestor_id).first()
        requestor_name = f"{requestor.first_name or ''} {requestor.last_name or ''}".strip() if requestor else "Неизвестно"
        requestor_phone = requestor.phone_number if requestor else ""
        
        result.append(GuarantorRequestAdminSchema(
            id=request.id,
            guarantor_id=request.guarantor_id,
            requestor_id=request.requestor_id,
            guarantor_name=guarantor_name,
            guarantor_phone=guarantor_phone,
            requestor_name=requestor_name,
            requestor_phone=requestor_phone,
            verification_status=request.verification_status,
            created_at=request.created_at.isoformat(),
            verified_at=request.verified_at.isoformat() if request.verified_at else None,
            admin_notes=request.admin_notes
        ))
    
    return result


@guarantors_router.post("/requests/{request_id}/approve")
async def approve_guarantor_request(
    request_id: int,
    approval_data: AdminApproveGuarantorSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Одобрение заявки гаранта администратором"""
    
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    request = db.query(GuarantorRequest).filter(GuarantorRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    # Обновляем статус заявки
    request.verification_status = "verified"
    request.admin_notes = approval_data.admin_notes
    request.verified_at = datetime.utcnow()
    
    # Присваиваем классы авто клиенту (requestor)
    requestor = db.query(User).filter(User.id == request.requestor_id).first()
    if requestor:
        # Конвертируем схемы в строки
        auto_classes_strings = [cls.value for cls in approval_data.auto_classes]
        requestor.auto_class = auto_classes_strings
    
    # Получаем данные гаранта для отправки SMS
    guarantor = db.query(User).filter(User.id == request.guarantor_id).first()
    
    db.commit()
    
    # Отправляем SMS гаранту при одобрении
    if guarantor and requestor:
        try:
            await send_guarantor_approval_sms(
                guarantor_phone=guarantor.phone_number,
                client_first_name=requestor.first_name,
                client_last_name=requestor.last_name
            )
        except Exception as e:
            print(f"Failed to send SMS to guarantor: {e}")
    
    return {
        "message": "Заявка одобрена",
        "assigned_classes": [cls.value for cls in approval_data.auto_classes]
    }


@guarantors_router.post("/requests/{request_id}/reject")
async def reject_guarantor_request(
    request_id: int,
    rejection_data: AdminRejectGuarantorSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Отклонение заявки гаранта администратором"""
    
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    request = db.query(GuarantorRequest).filter(GuarantorRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    # Обновляем статус заявки
    request.verification_status = "rejected"
    request.admin_notes = rejection_data.admin_notes
    request.verified_at = datetime.utcnow()
    
    # Получаем данные заявителя для отправки SMS
    requestor = db.query(User).filter(User.id == request.requestor_id).first()
    
    db.commit()
    
    # Отправляем SMS заявителю с предложением гаранта
    if requestor:
        try:
            await send_user_rejection_with_guarantor_sms(
                user_phone=requestor.phone_number,
                user_name=f"{requestor.first_name or ''} {requestor.last_name or ''}".strip(),
                rejection_reason=rejection_data.rejection_reason
            )
        except Exception as e:
            print(f"Failed to send SMS to user: {e}")

    return {"message": "Заявка отклонена"}

