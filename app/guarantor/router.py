from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List
import base64
import os
import uuid
import logging

logger = logging.getLogger(__name__)
from app.utils.short_id import safe_sid_to_uuid, uuid_to_sid
from app.utils.sid_converter import convert_uuid_response_to_sid

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.guarantor_model import Guarantor
from app.models.guarantor_model import (
    GuarantorRequest, 
    GuarantorRequestStatus, 
    Guarantor
)
from app.models.contract_model import ContractFile, ContractType, UserContractSignature
from app.models.application_model import Application, ApplicationStatus
from app.guarantor.schemas import (
    GuarantorRequestCreateSchema,
    ContractListSchema,
    ContractFileSchema,
    ContractUploadSchema,
    ContractDownloadSchema,
    ContractSignSchema,
    SimpleGuarantorSchema,
    SimpleClientSchema,
    IncomingRequestSchema,
    InviteGuarantorResponseSchema,
    AcceptGuarantorResponseSchema,
    MessageResponseSchema,
    GuarantorRelationshipsSchema,
    GuarantorInfoSchema,
    ErrorResponseSchema,
    GuarantorRequestAdminSchema,
    ClientGuarantorRequestsResponseSchema,
    ClientGuarantorRequestItemSchema,
    VerificationStatusSchema
)
from app.guarantor.sms_utils import send_guarantor_invitation_sms
from app.push.utils import send_push_to_user_by_id


async def cancel_guarantor_requests_on_rejection(guarantor_user_id: str, db: Session):
    """
    Отменяет все заявки гаранта при его отклонении финансистом или МВД
    """
    try:
        # Находим все активные заявки где этот пользователь является гарантом
        active_requests = db.query(GuarantorRequest).filter(
            GuarantorRequest.guarantor_id == guarantor_user_id,
            GuarantorRequest.status == GuarantorRequestStatus.PENDING
        ).all()
        
        # Отменяем все заявки
        for request in active_requests:
            request.status = GuarantorRequestStatus.REJECTED
            request.responded_at = datetime.utcnow()
        
        # Деактивируем все активные связи гарант-клиент
        active_relationships = db.query(Guarantor).filter(
            Guarantor.guarantor_id == guarantor_user_id,
            Guarantor.is_active == True
        ).all()
        
        for relationship in active_relationships:
            relationship.is_active = False
        
        db.commit()
        
        logger.info(f"Отменены все заявки и связи для гаранта {guarantor_user_id}")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при отмене заявок гаранта {guarantor_user_id}: {e}")
        db.rollback()
        return False

guarantor_router = APIRouter(prefix="/guarantor", tags=["Guarantor"])


@guarantor_router.post(
    "/invite",
    response_model=InviteGuarantorResponseSchema,
    responses={
        400: {"model": ErrorResponseSchema, "description": "Validation error"},
        401: {"model": ErrorResponseSchema, "description": "Not authenticated"},
        403: {"model": ErrorResponseSchema, "description": "Forbidden"},
        500: {"model": ErrorResponseSchema, "description": "Internal Server Error"},
    },
)
async def invite_guarantor(
    request_data: GuarantorRequestCreateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Создание заявки на гаранта.
    Если пользователя с указанным номером нет - отправляется SMS с приглашением.
    Если пользователь есть - создается заявка.
    """
    guarantor_phone = request_data.guarantor_info.phone_number
    
    # Проверяем, что пользователь не пытается назначить себя гарантом
    if current_user.phone_number == guarantor_phone:
        raise HTTPException(
            status_code=400,
            detail="Вы не можете назначить себя гарантом"
        )
    
    # Проверяем статус одобрения финансистом - только отклоненные по финансовым причинам могут приглашать гарантов
    user_application = db.query(Application).filter(
        Application.user_id == current_user.id
    ).first()
    
    if user_application:
        # Не может приглашать если одобрен или в обработке
        if user_application.financier_status in [ApplicationStatus.APPROVED, ApplicationStatus.PENDING]:
            raise HTTPException(
                status_code=403,
                detail="Услуга гаранта для вас недоступна"
            )
        
        # Может приглашать только если отклонен финансистом И роль REJECTFIRST (финансовые причины)
        if user_application.financier_status == ApplicationStatus.REJECTED:
            if current_user.role != UserRole.REJECTFIRST:
                raise HTTPException(
                    status_code=403,
                    detail="Услуга гаранта для вас недоступна"
                )
    
    # Проверяем, нет ли уже активной заявки к этому номеру телефона
    existing_request = db.query(GuarantorRequest).filter(
        GuarantorRequest.requestor_id == current_user.id,
        GuarantorRequest.guarantor_phone == guarantor_phone,
        GuarantorRequest.status == GuarantorRequestStatus.PENDING
    ).first()
    
    if existing_request:
        raise HTTPException(
            status_code=400,
            detail="У вас уже есть активная заявка к этому номеру телефона"
        )
    
    # Ищем пользователя с указанным номером
    guarantor_user = db.query(User).filter(
        User.phone_number == guarantor_phone,
        User.is_active == True
    ).first()
    
    if not guarantor_user:
        # Пользователя нет - создаем предварительную запись и отправляем SMS
        # Создаем временного пользователя или запись с номером телефона
        pending_request = GuarantorRequest(
            requestor_id=current_user.id,
            guarantor_id=None,  # Пока не знаем ID гаранта
            guarantor_phone=guarantor_phone,  # Сохраняем номер телефона
            reason=request_data.reason,
            status=GuarantorRequestStatus.PENDING
        )
        
        db.add(pending_request)
        db.commit()
        db.refresh(pending_request)
        
        # Формируем имя для SMS
        requestor_first_name = current_user.first_name or "Пользователь"
        requestor_middle_name = current_user.middle_name
        requestor_last_name = current_user.last_name
        
        sms_result = await send_guarantor_invitation_sms(guarantor_phone, requestor_first_name, requestor_last_name, requestor_middle_name)
        return {
            "message": "Пользователь не найден. SMS приглашение отправлено. Заявка создана.",
            "user_exists": False,
            "request_id": pending_request.sid,
            "sms_result": sms_result
        }
    
    # Проверяем роль пользователя - только user может стать гарантом
    if guarantor_user.role != UserRole.USER:
        raise HTTPException(
            status_code=400,
            detail="Данный клиент не может стать гарантом"
        )
    
    # Проверяем, нет ли уже активной заявки между этими пользователями
    existing_request = db.query(GuarantorRequest).filter(
        GuarantorRequest.requestor_id == current_user.id,
        GuarantorRequest.guarantor_id == guarantor_user.id,
        GuarantorRequest.status == GuarantorRequestStatus.PENDING
    ).first()
    
    if existing_request:
        raise HTTPException(
            status_code=400,
            detail="У вас уже есть активная заявка к этому пользователю"
        )
        
    # Проверяем, не является ли текущий пользователь уже гарантом для этого пользователя
    existing_guarantor_relationship = db.query(Guarantor).filter(
        Guarantor.guarantor_id == current_user.id,
        Guarantor.client_id == guarantor_user.id,
        Guarantor.is_active == True
    ).first()
    
    if existing_guarantor_relationship:
        raise HTTPException(
            status_code=400,
            detail="Вы уже являетесь гарантом для этого пользователя. Взаимное гарантство не допускается."
        )
    
    # Проверяем, не является ли этот пользователь уже гарантом для текущего пользователя
    existing_client_relationship = db.query(Guarantor).filter(
        Guarantor.guarantor_id == guarantor_user.id,
        Guarantor.client_id == current_user.id,
        Guarantor.is_active == True
    ).first()
    
    if existing_client_relationship:
        raise HTTPException(
            status_code=400,
            detail="Этот пользователь уже является вашим гарантом. Взаимное гарантство не допускается."
        )
    
    # Создаем новую заявку
    new_request = GuarantorRequest(
        requestor_id=current_user.id,
        guarantor_id=guarantor_user.id,
        reason=request_data.reason,
        status=GuarantorRequestStatus.PENDING
    )
    
    db.add(new_request)
    db.commit()
    db.refresh(new_request)
    
    try:
        requestor_first_name = current_user.first_name or "Пользователь"
        requestor_middle_name = current_user.middle_name
        requestor_last_name = current_user.last_name
        
        # Закомментировано SMS - отправляем только push уведомления
        # sms_result = await send_guarantor_invitation_sms(
        #     guarantor_user.phone_number,
        #     requestor_first_name,
        #     requestor_last_name,
        #     requestor_middle_name,
        # )

        name_parts = [p for p in [requestor_first_name, requestor_last_name, requestor_middle_name] if p]
        requestor_full_name = " ".join(name_parts)
        push_title = "Приглашение стать гарантом"
        push_body = (
            f"Пользователь {requestor_full_name}, {current_user.phone_number} выбрал вас гарантом. "
            f"Откройте приложение, чтобы принять или отклонить заявку."
        )
        await send_push_to_user_by_id(db, guarantor_user.id, push_title, push_body)
        sms_result = {"message": "Push notification sent successfully"}
    except Exception as _e:
        sms_result = {"message": "Push sending failed", "error": str(_e)}
    
    return {
        "message": "Заявка на гаранта создана успешно. Push уведомление отправлено гаранту.",
        "user_exists": True,
        "request_id": new_request.sid,
        "sms_result": sms_result,
    }


@guarantor_router.post(
    "/{id}/accept",
    response_model=AcceptGuarantorResponseSchema,
    responses={
        401: {"model": ErrorResponseSchema},
        403: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
        409: {"model": ErrorResponseSchema},
    },
)
async def accept_guarantor_request(
    id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Принять заявку на роль гаранта"""
    
    # Находим заявку
    request_uuid = safe_sid_to_uuid(id)
    guarantor_request = db.query(GuarantorRequest).filter(
        GuarantorRequest.id == request_uuid,
        GuarantorRequest.guarantor_id == current_user.id,
        GuarantorRequest.status == GuarantorRequestStatus.PENDING
    ).first()
    
    if not guarantor_request:
        raise HTTPException(
            status_code=404,
            detail="Заявка не найдена или вы не имеете права на неё отвечать"
        )
    
    # Проверяем, нет ли уже активной связи между этими пользователями
    existing_relationship = db.query(Guarantor).filter(
        Guarantor.guarantor_id == current_user.id,
        Guarantor.client_id == guarantor_request.requestor_id,
        Guarantor.is_active == True
    ).first()
    
    if existing_relationship:
        raise HTTPException(
            status_code=409,
            detail="У вас уже есть активная связь с этим пользователем"
        )
    
    # Обновляем статус заявки
    guarantor_request.status = GuarantorRequestStatus.ACCEPTED
    guarantor_request.responded_at = datetime.utcnow()
    
    # Создаем активную связь гарант-клиент
    guarantor_relationship = Guarantor(
        guarantor_id=current_user.id,
        client_id=guarantor_request.requestor_id,
        request_id=guarantor_request.id,
        is_active=True
    )
    
    db.add(guarantor_relationship)
    db.commit()
    
    return {
        "message": "Заявка принята. Теперь вам необходимо подписать договор гаранта.",
        "guarantor_relationship_id": guarantor_relationship.sid
    }


@guarantor_router.post(
    "/{id}/reject",
    response_model=MessageResponseSchema,
    responses={
        401: {"model": ErrorResponseSchema},
        403: {"model": ErrorResponseSchema},
        404: {"model": ErrorResponseSchema},
    },
)
async def reject_guarantor_request(
    id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Отклонить заявку на роль гаранта"""
    
    # Находим заявку
    request_uuid = safe_sid_to_uuid(id)
    guarantor_request = db.query(GuarantorRequest).filter(
        GuarantorRequest.id == request_uuid,
        GuarantorRequest.guarantor_id == current_user.id,
        GuarantorRequest.status == GuarantorRequestStatus.PENDING
    ).first()
    
    if not guarantor_request:
        raise HTTPException(
            status_code=404,
            detail="Заявка не найдена или вы не имеете права на неё отвечать"
        )
    
    # Обновляем статус заявки
    guarantor_request.status = GuarantorRequestStatus.REJECTED
    guarantor_request.responded_at = datetime.utcnow()
    
    db.commit()
    
    return {"message": "Заявка отклонена."}


@guarantor_router.get(
    "/my_guarantors",
    response_model=List[SimpleGuarantorSchema],
    responses={401: {"model": ErrorResponseSchema}},
)
async def get_my_guarantors(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Список подтверждённых гарантов текущего пользователя"""
    
    # Мои активные гаранты (люди, которые за меня ручаются)
    guarantor_relationships = db.query(Guarantor).filter(
        Guarantor.client_id == current_user.id,
        Guarantor.is_active == True
    ).all()
    
    result = []
    for relationship in guarantor_relationships:
        guarantor_user = db.query(User).filter(User.id == relationship.guarantor_id).first()
        if guarantor_user:
            # Проверяем подписи из user_contract_signatures (гарант подписывает для клиента)
            contract_signed = db.query(UserContractSignature).join(ContractFile).filter(
                UserContractSignature.user_id == relationship.guarantor_id,  # Гарант подписывает
                UserContractSignature.guarantor_relationship_id == relationship.id,
                ContractFile.contract_type == ContractType.GUARANTOR_CONTRACT
            ).first() is not None
            
            main_contract_signed = db.query(UserContractSignature).join(ContractFile).filter(
                UserContractSignature.user_id == relationship.guarantor_id,  # Гарант подписывает
                UserContractSignature.guarantor_relationship_id == relationship.id,
                ContractFile.contract_type == ContractType.GUARANTOR_MAIN_CONTRACT
            ).first() is not None
            
            result.append(SimpleGuarantorSchema(
                id=relationship.sid,
                phone=guarantor_user.phone_number,
                first_name=guarantor_user.first_name,
                last_name=guarantor_user.last_name,
                middle_name=guarantor_user.middle_name,
                contract_signed=contract_signed,
                main_contract_signed=main_contract_signed,
                created_at=relationship.created_at
            ))
    
    return result


@guarantor_router.get(
    "/my_guarantor_requests",
    response_model=ClientGuarantorRequestsResponseSchema,
    responses={401: {"model": ErrorResponseSchema}},
)
async def get_my_guarantor_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Мои заявки гарантов (от лица клиента) со статусами"""
    requests = db.query(GuarantorRequest).filter(
        GuarantorRequest.requestor_id == current_user.id
    ).order_by(GuarantorRequest.created_at.desc()).all()

    items: list[ClientGuarantorRequestItemSchema] = []
    for req in requests:
        guarantor_phone: str | None = req.guarantor_phone
        guarantor_first_name: str | None = None
        guarantor_last_name: str | None = None

        if req.guarantor_id:
            g_user = db.query(User).filter(User.id == req.guarantor_id).first()
            if g_user:
                guarantor_phone = guarantor_phone or g_user.phone_number
                guarantor_first_name = g_user.first_name
                guarantor_last_name = g_user.last_name

        items.append(ClientGuarantorRequestItemSchema(
            id=req.sid,
            guarantor_id=uuid_to_sid(req.guarantor_id) if req.guarantor_id else None,
            guarantor_phone=guarantor_phone,
            guarantor_first_name=guarantor_first_name,
            guarantor_last_name=guarantor_last_name,
            status=req.status,
            verification_status=VerificationStatusSchema(req.verification_status) if isinstance(req.verification_status, str) else req.verification_status,
            reason=req.reason,
            admin_notes=req.admin_notes,
            created_at=req.created_at,
            responded_at=req.responded_at,
            verified_at=req.verified_at
        ))

    return {
        "total": len(items),
        "items": items
    }


@guarantor_router.get(
    "/incoming",
    response_model=List[IncomingRequestSchema],
    responses={401: {"model": ErrorResponseSchema}},
)
async def get_incoming_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """«Я гарант»: входящие заявки на роль гаранта"""
    
    # Заявки, где меня просят быть гарантом и которые ещё не обработаны
    incoming_requests = db.query(GuarantorRequest).filter(
        GuarantorRequest.guarantor_id == current_user.id,
        GuarantorRequest.status == GuarantorRequestStatus.PENDING
    ).all()
    
    result = []
    for request in incoming_requests:
        requestor = db.query(User).filter(User.id == request.requestor_id).first()
        if requestor:
            # Приоритет: сначала User.first_name/last_name, иначе null
            requestor_first_name = requestor.first_name
            requestor_middle_name = requestor.middle_name
            requestor_last_name = requestor.last_name
            
            request_data = {
                "id": uuid_to_sid(request.id),
                "requestor_id": uuid_to_sid(request.requestor_id),
                "requestor_first_name": requestor_first_name,
                "requestor_middle_name": requestor_middle_name,
                "requestor_last_name": requestor_last_name,
                "requestor_phone": requestor.phone_number,
                "reason": request.reason,
                "created_at": request.created_at
            }
            
            converted_data = convert_uuid_response_to_sid(request_data, ["requestor_id"])
            result.append(IncomingRequestSchema(**converted_data))
    
    return result


@guarantor_router.get(
    "/my_clients",
    response_model=List[SimpleClientSchema],
    responses={401: {"model": ErrorResponseSchema}},
)
async def get_my_clients(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Люди, за которых я уже несу ответственность (включая отклоненных)"""
    
    # Клиенты, за которых я ручаюсь (включая неактивных)
    client_relationships = db.query(Guarantor).filter(
        Guarantor.guarantor_id == current_user.id
    ).order_by(Guarantor.created_at.desc()).all()
    
    result = []
    for relationship in client_relationships:
        client_user = db.query(User).filter(User.id == relationship.client_id).first()
        if client_user:
            # Проверяем подписи из user_contract_signatures (гарант подписывает для своего клиента)
            contract_signed = db.query(UserContractSignature).join(ContractFile).filter(
                UserContractSignature.user_id == current_user.id,
                UserContractSignature.guarantor_relationship_id == relationship.id,
                ContractFile.contract_type == ContractType.GUARANTOR_CONTRACT
            ).first() is not None
            
            main_contract_signed = db.query(UserContractSignature).join(ContractFile).filter(
                UserContractSignature.user_id == current_user.id,
                UserContractSignature.guarantor_relationship_id == relationship.id,
                ContractFile.contract_type == ContractType.GUARANTOR_MAIN_CONTRACT
            ).first() is not None
            
            # Формируем полное имя гаранта
            guarantor_fullname_parts = []
            if current_user.first_name:
                guarantor_fullname_parts.append(current_user.first_name)
            if current_user.middle_name:
                guarantor_fullname_parts.append(current_user.middle_name)
            if current_user.last_name:
                guarantor_fullname_parts.append(current_user.last_name)
            guarantor_fullname = " ".join(guarantor_fullname_parts) if guarantor_fullname_parts else "Не указано"
            
            # Формируем полное имя клиента
            client_fullname_parts = []
            if client_user.first_name:
                client_fullname_parts.append(client_user.first_name)
            if client_user.middle_name:
                client_fullname_parts.append(client_user.middle_name)
            if client_user.last_name:
                client_fullname_parts.append(client_user.last_name)
            client_fullname = " ".join(client_fullname_parts) if client_fullname_parts else "Не указано"
            
            result.append(SimpleClientSchema(
                guarantee_id=relationship.sid,
                guarantor={
                    "guarantor_fullname": guarantor_fullname,
                    "guarantor_iin": current_user.iin or "",
                    "guarantor_phone": current_user.phone_number or "",
                    "guarantor_email": current_user.email or "",
                    "guarantor_id": str(current_user.id),
                    "digital_signature": current_user.digital_signature or ""
                },
                client={
                    "client_fullname": client_fullname,
                    "client_iin": client_user.iin or "",
                    "client_phone": client_user.phone_number or "",
                    "client_email": client_user.email or "",
                    "client_id": str(client_user.id)
                },
                contract={
                    "contract_signed": contract_signed,
                    "main_contract_signed": main_contract_signed,
                    "guarantee_uuid": str(relationship.id),
                    "created_at": relationship.created_at.isoformat()
                },
                status="accepted" if relationship.is_active else "rejected"
            ))
    
    return result


@guarantor_router.get(
    "/contracts",
    response_model=ContractListSchema,
    responses={401: {"model": ErrorResponseSchema}},
)
async def get_contracts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка активных договоров"""
    
    guarantor_contracts = db.query(ContractFile).filter(
        ContractFile.contract_type == ContractType.GUARANTOR_CONTRACT,
        ContractFile.is_active == True
    ).all()
    
    guarantor_main_contracts = db.query(ContractFile).filter(
        ContractFile.contract_type == ContractType.GUARANTOR_MAIN_CONTRACT,
        ContractFile.is_active == True
    ).all()
    
    def format_contract(contract: ContractFile) -> ContractFileSchema:
        return ContractFileSchema(
            id=contract.sid,
            contract_type=contract.contract_type,
            file_name=contract.file_name,
            file_path=contract.file_path,
            uploaded_at=contract.uploaded_at,
            is_active=contract.is_active
        )
    
    return ContractListSchema(
        guarantor_contracts=[format_contract(c) for c in guarantor_contracts],
        guarantor_main_contracts=[format_contract(c) for c in guarantor_main_contracts]
    )


@guarantor_router.post(
    "/contracts/upload",
    response_model=MessageResponseSchema,
    responses={
        200: {
            "description": "Договор успешно загружен",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Договор guarantor успешно загружен"
                    }
                }
            }
        },
        400: {
            "model": ErrorResponseSchema,
            "description": "Ошибка валидации данных",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Тип договора должен быть 'guarantor_contract' или 'guarantor_main_contract'"
                    }
                }
            }
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Не авторизован"
        },
        403: {
            "model": ErrorResponseSchema,
            "description": "Доступ запрещен. Требуются права администратора",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Доступ запрещен. Требуются права администратора"
                    }
                }
            }
        },
        500: {
            "model": ErrorResponseSchema,
            "description": "Ошибка сервера при загрузке файла"
        }
    },
)
async def upload_contract(
    contract_data: ContractUploadSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Загрузка договора (только для админа)"""
    
    # Проверяем, что пользователь админ
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Доступ запрещен. Требуются права администратора"
        )
    
    # Проверяем тип договора
    if contract_data.contract_type not in ["guarantor_contract", "guarantor_main_contract"]:
        raise HTTPException(
            status_code=400,
            detail="Тип договора должен быть 'guarantor_contract' или 'guarantor_main_contract'"
        )
    
    try:
        # Обрабатываем data URL или обычный base64
        file_content_str = contract_data.file_content
        file_extension = ".pdf"  # По умолчанию
        
        if file_content_str.startswith("data:"):
            # Обрабатываем data URL: data:application/pdf;base64,...
            header, base64_data = file_content_str.split(",", 1)
            
            # Извлекаем MIME type для определения расширения
            if "application/pdf" in header:
                file_extension = ".pdf"
            elif "application/msword" in header or "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in header:
                file_extension = ".docx"
            elif "text/plain" in header:
                file_extension = ".txt"
            elif "image/jpeg" in header:
                file_extension = ".jpg"
            elif "image/png" in header:
                file_extension = ".png"
            elif "image/gif" in header:
                file_extension = ".gif"
            else:
                file_extension = ".pdf"  # По умолчанию
            
            file_content = base64.b64decode(base64_data)
        else:
            # Обычный base64
            file_content = base64.b64decode(file_content_str)
        
        # Создаем папку для договоров если не существует
        contracts_dir = "contracts"
        os.makedirs(contracts_dir, exist_ok=True)
        
        # Генерируем случайное имя файла с правильным расширением
        unique_filename = f"{contract_data.contract_type}_{uuid.uuid4()}{file_extension}"
        file_path = os.path.join(contracts_dir, unique_filename)
        
        # Сохраняем файл
        with open(file_path, "wb") as f:
            f.write(file_content)
        
        # Деактивируем старые договоры этого типа
        old_contracts = db.query(ContractFile).filter(
            ContractFile.contract_type == contract_data.contract_type,
            ContractFile.is_active == True
    ).all()
    
        for old_contract in old_contracts:
            old_contract.is_active = False
        
        # Создаем новую запись в БД
        new_contract = ContractFile(
            contract_type=contract_data.contract_type,
            file_name=unique_filename,
            file_path=file_path,
            is_active=True
        )
        
        db.add(new_contract)
        db.commit()
    
        return {"message": f"Договор {contract_data.contract_type} успешно загружен"}
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при загрузке файла: {str(e)}"
        )


@guarantor_router.get(
    "/contracts/guarantor",
    response_model=ContractDownloadSchema,
    responses={
        200: {
            "description": "Договор гаранта успешно получен",
            "content": {
                "application/json": {
                    "example": {
                        "id": 1,
                        "contract_type": "guarantor_contract",
                        "file_name": "guarantor_contract.pdf",
                        "file_url": "https://api.azvmotors.kz/contracts/guarantor_a1b2c3d4.pdf",
                        "uploaded_at": "2024-01-15T10:30:00Z",
                        "is_active": True
                    }
                }
            }
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Не авторизован"
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "Договор гаранта не найден",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Договор гаранта не найден"
                    }
                }
            }
        },
        500: {
            "model": ErrorResponseSchema,
            "description": "Ошибка при чтении файла"
        }
    },
)
async def get_guarantor_contract(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Просмотр договора гаранта"""
    
    contract = db.query(ContractFile).filter(
        ContractFile.contract_type == ContractType.GUARANTOR_CONTRACT,
        ContractFile.is_active == True
    ).first()
    
    if not contract:
        raise HTTPException(
            status_code=404,
            detail="Договор гаранта не найден"
        )
    
    try:
        # Формируем прямую ссылку на файл
        file_url = f"https://api.azvmotors.kz/contracts/{contract.file_name}"
        
        return ContractDownloadSchema(
            id=contract.sid,
            contract_type=contract.contract_type,
            file_name=contract.file_name,
            file_url=file_url,
            uploaded_at=contract.uploaded_at,
            is_active=contract.is_active
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при получении файла: {str(e)}"
        )


@guarantor_router.get(
    "/contracts/guarantor-main-contract",
    response_model=ContractDownloadSchema,
    responses={
        200: {
            "description": "Основной договор гаранта успешно получен",
            "content": {
                "application/json": {
                    "example": {
                        "id": 2,
                        "contract_type": "guarantor_main_contract",
                        "file_name": "guarantor_main_contract.pdf",
                        "file_url": "https://api.azvmotors.kz/contracts/guarantor_main_a1b2c3d4.pdf",
                        "uploaded_at": "2024-01-15T10:30:00Z",
                        "is_active": True
                    }
                }
            }
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Не авторизован"
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "Основной договор гаранта не найден",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Основной договор гаранта не найден"
                    }
                }
            }
        },
        500: {
            "model": ErrorResponseSchema,
            "description": "Ошибка при чтении файла"
        }
    },
)
async def get_guarantor_main_contract(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Просмотр основного договора гаранта"""
    
    contract = db.query(ContractFile).filter(
        ContractFile.contract_type == ContractType.GUARANTOR_MAIN_CONTRACT,
        ContractFile.is_active == True
    ).first()
    
    if not contract:
        raise HTTPException(
            status_code=404,
            detail="Основной договор гаранта не найден"
        )
    
    try:
        # Формируем прямую ссылку на файл
        file_url = f"https://api.azvmotors.kz/contracts/{contract.file_name}"
        
        return ContractDownloadSchema(
            id=contract.sid,
            contract_type=contract.contract_type,
            file_name=contract.file_name,
            file_url=file_url,
            uploaded_at=contract.uploaded_at,
            is_active=contract.is_active
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при получении файла: {str(e)}"
        )


@guarantor_router.post(
    "/contracts/sign",
    response_model=MessageResponseSchema,
    responses={
        200: {
            "description": "Договор успешно подписан",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Договор guarantor успешно подписан"
                    }
                }
            }
        },
        400: {
            "model": ErrorResponseSchema,
            "description": "Ошибка валидации или договор уже подписан",
            "content": {
                "application/json": {
                    "examples": {
                        "already_signed": {
                            "summary": "Договор уже подписан",
                            "value": {
                                "detail": "Договор гаранта уже подписан"
                            }
                        },
                        "invalid_type": {
                            "summary": "Неверный тип договора",
                            "value": {
                                "detail": "Неверный тип договора. Должен быть 'guarantor_contract' или 'guarantor_main_contract'"
                            }
                        }
                    }
                }
            }
        },
        401: {
            "model": ErrorResponseSchema,
            "description": "Не авторизован"
        },
        403: {
            "model": ErrorResponseSchema,
            "description": "Только гарант может подписать договор",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Только гарант может подписать договор"
                    }
                }
            }
        },
        404: {
            "model": ErrorResponseSchema,
            "description": "Связь гарант-клиент не найдена",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Связь гарант-клиент не найдена"
                    }
                }
            }
        }
    },
)
async def sign_contract(
    sign_data: ContractSignSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Подписание договора (только для принятых заявок)"""
    
    try:
        relationship_uuid = safe_sid_to_uuid(sign_data.guarantor_relationship_id)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Неверный формат guarantor_relationship_id: {str(e)}"
        )
    relationship = db.query(Guarantor).filter(
        Guarantor.id == relationship_uuid,
        Guarantor.guarantor_id == current_user.id,
        Guarantor.is_active == True
    ).first()
    
    if not relationship:
        raise HTTPException(
            status_code=404,
            detail="Связь гарант-клиент не найдена или не принадлежит вам"
        )
    
    original_request = db.query(GuarantorRequest).filter(
        GuarantorRequest.id == relationship.request_id,
        GuarantorRequest.status == GuarantorRequestStatus.ACCEPTED
    ).first()
    
    if not original_request:
        raise HTTPException(
            status_code=400,
            detail="Заявка не была принята. Сначала примите заявку на роль гаранта."
        )
    
    if not current_user.digital_signature:
        raise HTTPException(
            status_code=400,
            detail="У пользователя отсутствует цифровая подпись"
        )
    
    contract_file = db.query(ContractFile).filter(
        ContractFile.contract_type == sign_data.contract_type,
        ContractFile.is_active == True
    ).first()
    
    if not contract_file:
        raise HTTPException(
            status_code=404,
            detail=f"Файл договора типа {sign_data.contract_type} не найден"
        )
    
    # Проверяем, не подписан ли уже этот договор
    existing_signature = db.query(UserContractSignature).filter(
        UserContractSignature.user_id == current_user.id,
        UserContractSignature.contract_file_id == contract_file.id,
        UserContractSignature.guarantor_relationship_id == relationship_uuid
    ).first()
    
    if existing_signature:
        raise HTTPException(
            status_code=400,
            detail="Этот договор уже подписан"
        )
    
    signature = UserContractSignature(
        user_id=current_user.id,
        contract_file_id=contract_file.id,
        guarantor_relationship_id=relationship_uuid,
        digital_signature=current_user.digital_signature
    )
    
    db.add(signature)
    db.commit()

    # Отправляем push-уведомления после подписания договора
    try:
        client_user = db.query(User).filter(User.id == relationship.client_id).first()

        guarantor_name_parts = [p for p in [current_user.first_name, current_user.last_name, current_user.middle_name] if p]
        guarantor_full_name = " ".join(guarantor_name_parts) or "Гарант"

        client_name_parts = [p for p in [client_user.first_name if client_user else None, client_user.last_name if client_user else None, client_user.middle_name if client_user else None] if p]
        client_full_name = " ".join(client_name_parts) or "Клиент"

        title_for_guarantor = "Подтверждение роли гаранта"
        body_for_guarantor = (
            f"Вы, {guarantor_full_name}, стали гарантом для пользователя {client_full_name}, {client_user.phone_number if client_user else 'неизвестно'}. "
            f"Спасибо за подтверждение ответственности. Договор успешно подписан."
        )
        await send_push_to_user_by_id(db, current_user.id, title_for_guarantor, body_for_guarantor)

        if client_user:
            title_for_client = "Гарант подтвержден"
            body_for_client = (
                f"Пользователь {guarantor_full_name}, {current_user.phone_number} подтвердил статус гаранта для вас. "
                f"Договор успешно подписан."
            )
            await send_push_to_user_by_id(db, client_user.id, title_for_client, body_for_client)
    except Exception:
        pass

    return {"message": f"Договор {sign_data.contract_type} успешно подписан"}

@guarantor_router.get(
    "/admin/guarantor_requests",
    response_model=List[GuarantorRequestAdminSchema],
    responses={401: {"model": ErrorResponseSchema}, 403: {"model": ErrorResponseSchema}},
)
async def get_guarantor_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Админ: заявки ожидающие проверки (verification_status = not_verified)"""
    
    # Проверяем, что пользователь админ
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Доступ запрещен. Требуются права администратора"
        )
    
    # Заявки ожидающие проверки администратором
    pending_requests = db.query(GuarantorRequest).filter(
        GuarantorRequest.verification_status == "not_verified"
    ).all()
    
    result = []
    for request in pending_requests:
        # Получаем информацию о запрашивающем
        requestor = db.query(User).filter(User.id == request.requestor_id).first()
        requestor_first_name = requestor.first_name if requestor else None
        requestor_last_name = requestor.last_name if requestor else None
        requestor_phone = requestor.phone_number if requestor else None
        
        # Получаем информацию о гаранте (если есть)
        guarantor_phone = request.guarantor_phone
        
        if request.guarantor_id:
            guarantor = db.query(User).filter(User.id == request.guarantor_id).first()
            if guarantor:
                guarantor_phone = guarantor.phone_number
        
        request_data = {
            "id": uuid_to_sid(request.id),
            "requestor_id": uuid_to_sid(request.requestor_id),
            "requestor_first_name": requestor_first_name,
            "requestor_last_name": requestor_last_name,
            "requestor_phone": requestor_phone or "",
            "guarantor_id": uuid_to_sid(request.guarantor_id) if request.guarantor_id else None,
            "guarantor_phone": guarantor_phone or "",
            "status": request.status,
            "verification_status": request.verification_status,
            "reason": request.reason,
            "admin_notes": request.admin_notes,
            "created_at": request.created_at,
            "responded_at": request.responded_at,
            "verified_at": request.verified_at
        }
        
        converted_data = convert_uuid_response_to_sid(request_data, ["requestor_id", "guarantor_id"])
        result.append(GuarantorRequestAdminSchema(**converted_data))
    
    return result


@guarantor_router.get("/dashboard", response_model=GuarantorRelationshipsSchema)
async def get_guarantor_relationships(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получить полную информацию о связях гарант-клиент для текущего пользователя"""
    
    # Заявки где я клиент (ищу гаранта)
    my_requests = db.query(GuarantorRequest).filter(
        GuarantorRequest.requestor_id == current_user.id
    ).all()
    
    # Заявки где я гарант (мне нужно ответить)
    guarantor_requests = db.query(GuarantorRequest).filter(
        GuarantorRequest.guarantor_id == current_user.id
    ).all()
    
    # Активные связи где я гарант
    my_clients = db.query(Guarantor).filter(
        Guarantor.guarantor_id == current_user.id,
        Guarantor.is_active == True
    ).all()
    
    # Активные связи где я клиент
    my_guarantors = db.query(Guarantor).filter(
        Guarantor.client_id == current_user.id,
        Guarantor.is_active == True
    ).all()
    
    response_data = {
        "user_id": uuid_to_sid(current_user.id),
        "user_phone": current_user.phone_number,
        "summary": {
            "requests_sent": len(my_requests),
            "requests_received": len(guarantor_requests), 
            "active_clients": len(my_clients),
            "active_guarantors": len(my_guarantors)
        },
        "details": {
            "sent_requests": [
                {
                    "id": uuid_to_sid(req.id),
                    "guarantor_phone": req.guarantor_phone,
                    "guarantor_id": uuid_to_sid(req.guarantor_id) if req.guarantor_id else None,
                    "status": req.status.value,
                    "created_at": req.created_at
                } for req in my_requests
            ],
            "received_requests": [
                {
                    "id": uuid_to_sid(req.id),
                    "requestor_id": uuid_to_sid(req.requestor_id),
                    "status": req.status.value,
                    "created_at": req.created_at
                } for req in guarantor_requests
            ],
            "my_clients": [
                {
                    "id": uuid_to_sid(rel.id),
                    "client_id": uuid_to_sid(rel.client_id),
                    "created_at": rel.created_at,
                    "contract_signed": rel.contract_signed
                } for rel in my_clients
            ],
            "my_guarantors": [
                {
                    "id": uuid_to_sid(rel.id),
                    "guarantor_id": uuid_to_sid(rel.guarantor_id),
                    "created_at": rel.created_at,
                    "contract_signed": rel.contract_signed
                } for rel in my_guarantors
            ]
        }
    }
    
    converted_data = convert_uuid_response_to_sid(response_data, ["user_id"])
    
    for sent_req in converted_data["details"]["sent_requests"]:
        if sent_req.get("guarantor_id"):
            sent_req["guarantor_id"] = uuid_to_sid(sent_req["guarantor_id"])
    
    for rec_req in converted_data["details"]["received_requests"]:
        if rec_req.get("requestor_id"):
            rec_req["requestor_id"] = uuid_to_sid(rec_req["requestor_id"])
    
    for client in converted_data["details"]["my_clients"]:
        if client.get("client_id"):
            client["client_id"] = uuid_to_sid(client["client_id"])
    
    for guarantor in converted_data["details"]["my_guarantors"]:
        if guarantor.get("guarantor_id"):
            guarantor["guarantor_id"] = uuid_to_sid(guarantor["guarantor_id"])
    
    return converted_data


