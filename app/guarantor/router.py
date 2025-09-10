from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.guarantor_model import (
    GuarantorRequest, 
    GuarantorRequestStatus, 
    Guarantor, 
    ContractFile
)
from app.guarantor.schemas import (
    GuarantorRequestCreateSchema,
    ContractListSchema,
    ContractFileSchema,
    SimpleGuarantorSchema,
    SimpleClientSchema,
    IncomingRequestSchema,
    InviteGuarantorResponseSchema,
    AcceptGuarantorResponseSchema,
    MessageResponseSchema,
    LinkPendingRequestsResponseSchema,
    GuarantorRelationshipsSchema,
    GuarantorInfoSchema,
    ErrorResponseSchema
)
from app.guarantor.sms_utils import send_guarantor_invitation_sms

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
    guarantor_name = request_data.guarantor_info.full_name
    
    # Проверяем, что пользователь не пытается назначить себя гарантом
    if current_user.phone_number == guarantor_phone:
        raise HTTPException(
            status_code=400,
            detail="Вы не можете назначить себя гарантом"
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
            guarantor_name=guarantor_name,    # Сохраняем имя
            reason=request_data.reason,
            status=GuarantorRequestStatus.PENDING
        )
        
        db.add(pending_request)
        db.commit()
        db.refresh(pending_request)
        
        sms_result = await send_guarantor_invitation_sms(guarantor_phone, current_user.full_name or current_user.phone_number)
        return {
            "message": "Пользователь не найден. SMS приглашение отправлено. Заявка создана.",
            "user_exists": False,
            "request_id": pending_request.id,
            "sms_result": sms_result
        }
    
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
    
    return {
        "message": "Заявка на гаранта создана успешно",
        "user_exists": True,
        "request_id": new_request.id,
        "guarantor_name": guarantor_user.full_name
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
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Принять заявку на роль гаранта"""
    
    # Находим заявку
    guarantor_request = db.query(GuarantorRequest).filter(
        GuarantorRequest.id == id,
        GuarantorRequest.guarantor_id == current_user.id,
        GuarantorRequest.status == GuarantorRequestStatus.PENDING
    ).first()
    
    if not guarantor_request:
        raise HTTPException(
            status_code=404,
            detail="Заявка не найдена или вы не имеете права на неё отвечать"
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
        "guarantor_relationship_id": guarantor_relationship.id
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
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Отклонить заявку на роль гаранта"""
    
    # Находим заявку
    guarantor_request = db.query(GuarantorRequest).filter(
        GuarantorRequest.id == id,
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
            result.append(SimpleGuarantorSchema(
                id=relationship.id,
                name=guarantor_user.full_name or guarantor_user.phone_number,
                phone=guarantor_user.phone_number,
                contract_signed=relationship.contract_signed,
                sublease_contract_signed=relationship.sublease_contract_signed,
                created_at=relationship.created_at
            ))
    
    return result


@guarantor_router.get(
    "/incoming",
    response_model=List[IncomingRequestSchema],
    responses={401: {"model": ErrorResponseSchema}},
)
async def get_incoming_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """«Я гарант»: входящие заявки"""
    
    # Заявки, где меня просят быть гарантом и которые ещё не обработаны
    incoming_requests = db.query(GuarantorRequest).filter(
        GuarantorRequest.guarantor_id == current_user.id,
        GuarantorRequest.status == GuarantorRequestStatus.PENDING
    ).all()
    
    result = []
    for request in incoming_requests:
        requestor = db.query(User).filter(User.id == request.requestor_id).first()
        if requestor:
            result.append(IncomingRequestSchema(
                id=request.id,
                requestor_name=requestor.full_name or requestor.phone_number,
                requestor_phone=requestor.phone_number,
                reason=request.reason,
                created_at=request.created_at
            ))
    
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
    """Люди, за которых я уже несу ответственность"""
    
    # Клиенты, за которых я ручаюсь
    client_relationships = db.query(Guarantor).filter(
        Guarantor.guarantor_id == current_user.id,
        Guarantor.is_active == True
    ).all()
    
    result = []
    for relationship in client_relationships:
        client_user = db.query(User).filter(User.id == relationship.client_id).first()
        if client_user:
            result.append(SimpleClientSchema(
                id=relationship.id,
                name=client_user.full_name or client_user.phone_number,
                phone=client_user.phone_number,
                contract_signed=relationship.contract_signed,
                sublease_contract_signed=relationship.sublease_contract_signed,
                created_at=relationship.created_at
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
        ContractFile.contract_type == "guarantor",
        ContractFile.is_active == True
    ).all()
    
    sublease_contracts = db.query(ContractFile).filter(
        ContractFile.contract_type == "sublease",
        ContractFile.is_active == True
    ).all()
    
    def format_contract(contract: ContractFile) -> ContractFileSchema:
        return ContractFileSchema(
            id=contract.id,
            contract_type=contract.contract_type,
            file_name=contract.file_name,
            file_path=contract.file_path,
            uploaded_at=contract.uploaded_at,
            is_active=contract.is_active
        )
    
    return ContractListSchema(
        guarantor_contracts=[format_contract(c) for c in guarantor_contracts],
        sublease_contracts=[format_contract(c) for c in sublease_contracts]
    )


@guarantor_router.post("/link-pending-requests", response_model=LinkPendingRequestsResponseSchema)
async def link_pending_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Связывание ожидающих заявок с новозарегистрированным пользователем.
    Вызывается автоматически при регистрации или входе пользователя.
    """
    
    # Ищем заявки с номером телефона этого пользователя
    pending_requests = db.query(GuarantorRequest).filter(
        GuarantorRequest.guarantor_phone == current_user.phone_number,
        GuarantorRequest.guarantor_id.is_(None),
        GuarantorRequest.status == GuarantorRequestStatus.PENDING
    ).all()
    
    linked_count = 0
    for request in pending_requests:
        request.guarantor_id = current_user.id
        linked_count += 1
    
    if linked_count > 0:
        db.commit()
    
    return {
        "message": f"Связано {linked_count} заявок с вашим аккаунтом",
        "linked_requests": linked_count
    }


@guarantor_router.get("/relationships", response_model=GuarantorRelationshipsSchema)
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
    
    return {
        "user_id": current_user.id,
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
                    "id": req.id,
                    "guarantor_phone": req.guarantor_phone,
                    "guarantor_name": req.guarantor_name,
                    "guarantor_id": req.guarantor_id,
                    "status": req.status.value,
                    "created_at": req.created_at
                } for req in my_requests
            ],
            "received_requests": [
                {
                    "id": req.id,
                    "requestor_id": req.requestor_id,
                    "status": req.status.value,
                    "created_at": req.created_at
                } for req in guarantor_requests
            ],
            "my_clients": [
                {
                    "id": rel.id,
                    "client_id": rel.client_id,
                    "created_at": rel.created_at,
                    "contract_signed": rel.contract_signed
                } for rel in my_clients
            ],
            "my_guarantors": [
                {
                    "id": rel.id,
                    "guarantor_id": rel.guarantor_id,
                    "created_at": rel.created_at,
                    "contract_signed": rel.contract_signed
                } for rel in my_guarantors
            ]
        }
    }


@guarantor_router.get("/info", response_model=GuarantorInfoSchema)
async def get_guarantor_info():
    """Информация о функции гаранта (для кнопки '?')"""
    return {
        "title": "Что такое Гарант?",
        "description": "Гарант — лицо, которое в случае ДТП несёт материальную ответственность",
        "details": [
            "Гарант - это человек, который берет на себя материальную ответственность за ваши действия",
            "В случае ДТП или других обязательств, гарант будет нести финансовую ответственность",
            "Для оформления услуги гарант должен подписать специальный договор",
            "После подписания договора гаранта, также подписывается договор субаренды автомобиля"
        ]
    }
