from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List
import base64
import os
import uuid

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
    GuarantorRequestAdminSchema
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
            guarantor_name = relationship.original_request.guarantor_name if relationship.original_request else None
            result.append(SimpleGuarantorSchema(
                id=relationship.id,
                name=guarantor_name or guarantor_user.full_name or guarantor_user.phone_number,
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
                        "detail": "Тип договора должен быть 'guarantor' или 'sublease'"
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
    if contract_data.contract_type not in ["guarantor", "sublease"]:
        raise HTTPException(
            status_code=400,
            detail="Тип договора должен быть 'guarantor' или 'sublease'"
        )
    
    try:
        # Декодируем base64
        file_content = base64.b64decode(contract_data.file_content_base64)
        
        # Создаем папку для договоров если не существует
        contracts_dir = "contracts"
        os.makedirs(contracts_dir, exist_ok=True)
        
        # Генерируем уникальное имя файла
        file_extension = os.path.splitext(contract_data.file_name)[1]
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
            file_name=contract_data.file_name,
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
                        "contract_type": "guarantor",
                        "file_name": "guarantor_contract.pdf",
                        "file_content_base64": "JVBERi0xLjQKJcfsj6IKNSAwIG9iago8PAovVHlwZSAvUGFnZQovUGFyZW50IDMgMCBSCi9SZXNvdXJjZXMgPDwKL0ZvbnQgPDwKL0YxIDIgMCBSCj4+Cj4+Ci9NZWRpYUJveCBbMCAwIDU5NSA4NDJdCi9Db250ZW50cyA0IDAgUgo+PgplbmRvYmoK",
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
        ContractFile.contract_type == "guarantor",
        ContractFile.is_active == True
    ).first()
    
    if not contract:
        raise HTTPException(
            status_code=404,
            detail="Договор гаранта не найден"
        )
    
    try:
        # Читаем файл и кодируем в base64
        with open(contract.file_path, "rb") as f:
            file_content = f.read()
            file_content_base64 = base64.b64encode(file_content).decode('utf-8')
        
        return ContractDownloadSchema(
            id=contract.id,
            contract_type=contract.contract_type,
            file_name=contract.file_name,
            file_content_base64=file_content_base64,
            uploaded_at=contract.uploaded_at,
            is_active=contract.is_active
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при чтении файла: {str(e)}"
        )


@guarantor_router.get(
    "/contracts/sublease",
    response_model=ContractDownloadSchema,
    responses={
        200: {
            "description": "Договор субаренды успешно получен",
            "content": {
                "application/json": {
                    "example": {
                        "id": 2,
                        "contract_type": "sublease",
                        "file_name": "sublease_contract.pdf",
                        "file_content_base64": "JVBERi0xLjQKJcfsj6IKNSAwIG9iago8PAovVHlwZSAvUGFnZQovUGFyZW50IDMgMCBSCi9SZXNvdXJjZXMgPDwKL0ZvbnQgPDwKL0YxIDIgMCBSCj4+Cj4+Ci9NZWRpYUJveCBbMCAwIDU5NSA4NDJdCi9Db250ZW50cyA0IDAgUgo+PgplbmRvYmoK",
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
            "description": "Договор субаренды не найден",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Договор субаренды не найден"
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
async def get_sublease_contract(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Просмотр договора субаренды"""
    
    contract = db.query(ContractFile).filter(
        ContractFile.contract_type == "sublease",
        ContractFile.is_active == True
    ).first()
    
    if not contract:
        raise HTTPException(
            status_code=404,
            detail="Договор субаренды не найден"
        )
    
    try:
        # Читаем файл и кодируем в base64
        with open(contract.file_path, "rb") as f:
            file_content = f.read()
            file_content_base64 = base64.b64encode(file_content).decode('utf-8')
        
        return ContractDownloadSchema(
            id=contract.id,
            contract_type=contract.contract_type,
            file_name=contract.file_name,
            file_content_base64=file_content_base64,
            uploaded_at=contract.uploaded_at,
            is_active=contract.is_active
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при чтении файла: {str(e)}"
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
                                "detail": "Неверный тип договора. Должен быть 'guarantor' или 'sublease'"
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
    """Подписание договора (только гарант)"""
    
    # Находим связь гарант-клиент
    relationship = db.query(Guarantor).filter(
        Guarantor.id == sign_data.guarantor_relationship_id,
        Guarantor.is_active == True
    ).first()
    
    if not relationship:
        raise HTTPException(
            status_code=404,
            detail="Связь гарант-клиент не найдена"
        )
    
    # Проверяем, что пользователь является гарантом в этой связи
    if current_user.id != relationship.guarantor_id:
        raise HTTPException(
            status_code=403,
            detail="Только гарант может подписать договор"
        )
    
    # Обновляем статус подписания в таблице guarantors
    if sign_data.contract_type == "guarantor":
        if relationship.contract_signed:
            raise HTTPException(
                status_code=400,
                detail="Договор гаранта уже подписан"
            )
        relationship.contract_signed = True
    elif sign_data.contract_type == "sublease":
        if relationship.sublease_contract_signed:
            raise HTTPException(
                status_code=400,
                detail="Договор субаренды уже подписан"
            )
        relationship.sublease_contract_signed = True
    else:
        raise HTTPException(
            status_code=400,
            detail="Неверный тип договора. Должен быть 'guarantor' или 'sublease'"
        )
    
    db.commit()
    
    return {"message": f"Договор {sign_data.contract_type} успешно подписан"}

@guarantor_router.get(
    "/admin/pending_verification",
    response_model=List[GuarantorRequestAdminSchema],
    responses={401: {"model": ErrorResponseSchema}, 403: {"model": ErrorResponseSchema}},
)
async def get_pending_verification_requests(
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
        requestor_name = requestor.full_name if requestor else None
        requestor_phone = requestor.phone_number if requestor else None
        
        # Получаем информацию о гаранте (если есть)
        guarantor = None
        guarantor_name = request.guarantor_name
        guarantor_phone = request.guarantor_phone
        
        if request.guarantor_id:
            guarantor = db.query(User).filter(User.id == request.guarantor_id).first()
            if guarantor:
                guarantor_name = guarantor.full_name
                guarantor_phone = guarantor.phone_number
        
        result.append(GuarantorRequestAdminSchema(
            id=request.id,
            requestor_id=request.requestor_id,
            requestor_name=requestor_name,
            requestor_phone=requestor_phone or "",
            guarantor_id=request.guarantor_id,
            guarantor_name=guarantor_name,
            guarantor_phone=guarantor_phone or "",
            status=request.status,
            verification_status=request.verification_status,
            reason=request.reason,
            admin_notes=request.admin_notes,
            created_at=request.created_at,
            responded_at=request.responded_at,
            verified_at=request.verified_at
        ))
    
    return result


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


