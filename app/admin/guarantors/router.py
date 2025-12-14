from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
import asyncio

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole, AutoClass
from app.models.guarantor_model import GuarantorRequest
from app.utils.short_id import uuid_to_sid, safe_sid_to_uuid
from app.guarantor.sms_utils import send_user_rejection_with_guarantor_sms, send_guarantor_approval_sms
from app.admin.guarantors.schemas import (
    GuarantorRequestAdminSchema, 
    AdminApproveGuarantorSchema, 
    AdminRejectGuarantorSchema
)
from app.utils.sid_converter import convert_uuid_response_to_sid
from app.utils.telegram_logger import log_error_to_telegram
from app.utils.time_utils import get_local_time
from app.push.utils import send_localized_notification_to_user, user_has_push_tokens
from app.websocket.notifications import notify_user_status_update

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
        guarantor_name = f"{guarantor.first_name or ''} {guarantor.last_name or ''} {guarantor.middle_name or ''}".strip() if guarantor else "Неизвестно"
        guarantor_phone = guarantor.phone_number if guarantor else ""
        
        # Получаем данные заявителя
        requestor = db.query(User).filter(User.id == request.requestor_id).first()
        requestor_name = f"{requestor.first_name or ''} {requestor.last_name or ''} {requestor.middle_name or ''}".strip() if requestor else "Неизвестно"
        requestor_phone = requestor.phone_number if requestor else ""
        
        request_data = {
            "id": uuid_to_sid(request.id),
            "guarantor_id": uuid_to_sid(request.guarantor_id) if request.guarantor_id else None,
            "requestor_id": uuid_to_sid(request.requestor_id),
            "guarantor_name": guarantor_name,
            "guarantor_phone": guarantor_phone,
            "requestor_name": requestor_name,
            "requestor_phone": requestor_phone,
            "verification_status": request.verification_status,
            "created_at": request.created_at.isoformat(),
            "verified_at": request.verified_at.isoformat() if request.verified_at else None,
            "admin_notes": request.admin_notes
        }
        
        converted_data = convert_uuid_response_to_sid(request_data, ["guarantor_id", "requestor_id"])
        result.append(GuarantorRequestAdminSchema(**converted_data))
    
    return result


@guarantors_router.post("/requests/{request_id}/approve")
async def approve_guarantor_request(
    request_id: str,
    approval_data: AdminApproveGuarantorSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Одобрение заявки гаранта администратором"""
    
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    request_uuid = safe_sid_to_uuid(request_id)
    request = db.query(GuarantorRequest).filter(GuarantorRequest.id == request_uuid).first()
    if not request:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    # Обновляем статус заявки
    request.verification_status = "verified"
    request.admin_notes = approval_data.admin_notes
    request.verified_at = get_local_time()
    
    # Присваиваем классы авто клиенту (requestor)
    requestor = db.query(User).filter(User.id == request.requestor_id).first()
    if requestor:
        # Конвертируем схемы в строки
        auto_classes_strings = [cls.value for cls in approval_data.auto_classes]
        requestor.auto_class = auto_classes_strings
    
    # Получаем данные гаранта для отправки SMS
    guarantor = db.query(User).filter(User.id == request.guarantor_id).first()
    
    db.commit()
    
    if requestor:
        asyncio.create_task(notify_user_status_update(str(requestor.id)))
    
    # Отправляем SMS гаранту при одобрении
    if guarantor and requestor:
        try:
            await send_guarantor_approval_sms(
                guarantor_phone=guarantor.phone_number,
                client_first_name=requestor.first_name,
                client_last_name=requestor.last_name,
                client_middle_name=requestor.middle_name
            )
        except Exception as e:
            print(f"Failed to send SMS to guarantor: {e}")
            try:
                await log_error_to_telegram(
                    error=e,
                    request=None,
                    user=current_user,
                    additional_context={
                        "action": "admin_approve_guarantor_sms",
                        "guarantor_request_id": request_id,
                        "guarantor_id": str(request.guarantor_id),
                        "requestor_id": str(request.requestor_id),
                        "admin_id": str(current_user.id)
                    }
                )
            except:
                pass
    
    # Отправляем уведомление клиенту о том, что гарант подключён
    if requestor and user_has_push_tokens(db, requestor.id):
        from app.push.utils import send_localized_notification_to_user_async
        asyncio.create_task(
            send_localized_notification_to_user_async(
                requestor.id,
                "guarantor_connected",
                "guarantor_connected"
            )
        )
    
    return {
        "message": "Заявка одобрена",
        "assigned_classes": [cls.value for cls in approval_data.auto_classes]
    }


@guarantors_router.post("/requests/{request_id}/reject")
async def reject_guarantor_request(
    request_id: str,
    rejection_data: AdminRejectGuarantorSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Отклонение заявки гаранта администратором"""
    
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    request_uuid = safe_sid_to_uuid(request_id)
    request = db.query(GuarantorRequest).filter(GuarantorRequest.id == request_uuid).first()
    if not request:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    # Обновляем статус заявки
    request.verification_status = "rejected"
    request.admin_notes = rejection_data.admin_notes
    request.verified_at = get_local_time()
    
    # Получаем данные заявителя для отправки SMS
    requestor = db.query(User).filter(User.id == request.requestor_id).first()
    
    db.commit()
    
    # Отправляем SMS заявителю с предложением гаранта
    if requestor:
        try:
            await send_user_rejection_with_guarantor_sms(
                user_phone=requestor.phone_number,
                user_name=f"{requestor.first_name or ''} {requestor.last_name or ''} {requestor.middle_name or ''}".strip(),
                rejection_reason=rejection_data.rejection_reason
            )
        except Exception as e:
            print(f"Failed to send SMS to user: {e}")
            try:
                await log_error_to_telegram(
                    error=e,
                    request=None,
                    user=current_user,
                    additional_context={
                        "action": "admin_reject_guarantor_sms",
                        "guarantor_request_id": request_id,
                        "requestor_id": str(request.requestor_id),
                        "admin_id": str(current_user.id),
                        "rejection_reason": rejection_data.rejection_reason
                    }
                )
            except:
                pass

    return {"message": "Заявка отклонена"}
