from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from datetime import datetime, timedelta
from typing import List, Optional
import os

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
    GuarantorRequestResponseSchema,
    GuarantorRequestSchema,
    GuarantorSchema,
    UserGuarantorInfoSchema,
    ContractSignSchema,
    ContractListSchema,
    ContractFileSchema,
    RejectUserWithGuarantorSchema,
    CheckUserEligibilitySchema,
    UserEligibilityResultSchema,
    GuarantorInfoSchema
)
from app.guarantor.sms_utils import send_guarantor_invitation_sms, send_user_rejection_with_guarantor_sms
from app.models.car_model import Car
from app.models.history_model import RentalHistory, RentalStatus

guarantor_router = APIRouter(prefix="/guarantor", tags=["Guarantor"])

ALLOWED_CONTRACT_TYPES = ["application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]


async def save_contract_file(file: UploadFile, contract_type: str) -> str:
    """Сохранение файла договора"""
    # Создаем директорию если не существует
    upload_dir = f"uploads/contracts/{contract_type}"
    os.makedirs(upload_dir, exist_ok=True)
    
    # Генерируем уникальное имя файла
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_extension = file.filename.split('.')[-1] if '.' in file.filename else 'pdf'
    file_name = f"{contract_type}_{timestamp}.{file_extension}"
    file_path = os.path.join(upload_dir, file_name)
    
    # Сохраняем файл
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    
    return file_path


@guarantor_router.post("/request", response_model=dict)
async def create_guarantor_request(
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
        # Пользователя нет - отправляем SMS приглашение
        sms_result = await send_guarantor_invitation_sms(guarantor_phone, current_user.full_name or current_user.phone_number)
        return {
            "message": "Пользователь не найден. SMS приглашение отправлено.",
            "user_exists": False,
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


@guarantor_router.post("/respond/{request_id}")
async def respond_to_guarantor_request(
    request_id: int,
    response_data: GuarantorRequestResponseSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ответ на заявку гаранта (принять/отклонить)"""
    
    # Находим заявку
    guarantor_request = db.query(GuarantorRequest).filter(
        GuarantorRequest.id == request_id,
        GuarantorRequest.guarantor_id == current_user.id,
        GuarantorRequest.status == GuarantorRequestStatus.PENDING
    ).first()
    
    if not guarantor_request:
        raise HTTPException(
            status_code=404,
            detail="Заявка не найдена или вы не имеете права на неё отвечать"
        )
    
    # Обновляем статус заявки
    if response_data.accept:
        guarantor_request.status = GuarantorRequestStatus.ACCEPTED
        
        # Создаем активную связь гарант-клиент
        guarantor_relationship = Guarantor(
            guarantor_id=current_user.id,
            client_id=guarantor_request.requestor_id,
            request_id=guarantor_request.id,
            is_active=True
        )
        
        db.add(guarantor_relationship)
        
        message = "Заявка принята. Теперь вам необходимо подписать договор гаранта."
    else:
        guarantor_request.status = GuarantorRequestStatus.REJECTED
        message = "Заявка отклонена."
    
    guarantor_request.responded_at = datetime.utcnow()
    
    db.commit()
    
    return {"message": message}


@guarantor_router.get("/my-info", response_model=UserGuarantorInfoSchema)
async def get_my_guarantor_info(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение информации о гарантах пользователя"""
    
    # Заявки, которые я отправил
    sent_requests = db.query(GuarantorRequest).filter(
        GuarantorRequest.requestor_id == current_user.id
    ).all()
    
    # Заявки, которые я получил
    received_requests = db.query(GuarantorRequest).filter(
        GuarantorRequest.guarantor_id == current_user.id
    ).all()
    
    # Люди, за которых я ручаюсь
    my_clients = db.query(Guarantor).filter(
        Guarantor.guarantor_id == current_user.id,
        Guarantor.is_active == True
    ).all()
    
    # Мои гаранты
    my_guarantors = db.query(Guarantor).filter(
        Guarantor.client_id == current_user.id,
        Guarantor.is_active == True
    ).all()
    
    def format_request(req: GuarantorRequest) -> GuarantorRequestSchema:
        try:
            requestor = db.query(User).filter(User.id == req.requestor_id).first()
            guarantor = db.query(User).filter(User.id == req.guarantor_id).first()
            
            return GuarantorRequestSchema(
                id=req.id,
                requestor_id=req.requestor_id,
                guarantor_id=req.guarantor_id,
                status=req.status,
                reason=req.reason,
                created_at=req.created_at,
                responded_at=req.responded_at,
                requestor_name=requestor.full_name if requestor else None,
                requestor_phone=requestor.phone_number if requestor else "",
                guarantor_name=guarantor.full_name if guarantor else None,
                guarantor_phone=guarantor.phone_number if guarantor else ""
            )
        except Exception as e:
            print(f"Error formatting request {req.id}: {e}")
            return None
    
    def format_guarantor(g: Guarantor) -> GuarantorSchema:
        try:
            guarantor_user = db.query(User).filter(User.id == g.guarantor_id).first()
            client_user = db.query(User).filter(User.id == g.client_id).first()
            
            return GuarantorSchema(
                id=g.id,
                guarantor_id=g.guarantor_id,
                client_id=g.client_id,
                contract_signed=g.contract_signed,
                sublease_contract_signed=g.sublease_contract_signed,
                is_active=g.is_active,
                created_at=g.created_at,
                guarantor_name=guarantor_user.full_name if guarantor_user else None,
                guarantor_phone=guarantor_user.phone_number if guarantor_user else "",
                client_name=client_user.full_name if client_user else None,
                client_phone=client_user.phone_number if client_user else ""
            )
        except Exception as e:
            print(f"Error formatting guarantor {g.id}: {e}")
            return None
    
    return UserGuarantorInfoSchema(
        sent_requests=[req for req in [format_request(req) for req in sent_requests] if req is not None],
        received_requests=[req for req in [format_request(req) for req in received_requests] if req is not None],
        my_clients=[g for g in [format_guarantor(g) for g in my_clients] if g is not None],
        my_guarantors=[g for g in [format_guarantor(g) for g in my_guarantors] if g is not None]
    )


@guarantor_router.post("/sign-contract")
async def sign_contract(
    contract_data: ContractSignSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Подписание договора гаранта или субаренды"""
    
    # Находим отношение гарант-клиент
    guarantor_relationship = db.query(Guarantor).filter(
        Guarantor.id == contract_data.guarantor_relationship_id,
        or_(
            Guarantor.guarantor_id == current_user.id,
            Guarantor.client_id == current_user.id
        ),
        Guarantor.is_active == True
    ).first()
    
    if not guarantor_relationship:
        raise HTTPException(
            status_code=404,
            detail="Отношение гарант-клиент не найдено"
        )
    
    # Проверяем тип договора и обновляем соответствующее поле
    if contract_data.contract_type == "guarantor":
        guarantor_relationship.contract_signed = True
        message = "Договор гаранта подписан"
    elif contract_data.contract_type == "sublease":
        if not guarantor_relationship.contract_signed:
            raise HTTPException(
                status_code=400,
                detail="Сначала необходимо подписать договор гаранта"
            )
        guarantor_relationship.sublease_contract_signed = True
        message = "Договор субаренды подписан"
    else:
        raise HTTPException(
            status_code=400,
            detail="Неверный тип договора. Используйте 'guarantor' или 'sublease'"
        )
    
    db.commit()
    
    return {"message": message}


@guarantor_router.post("/upload-contract/{contract_type}")
async def upload_contract(
    contract_type: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Загрузка файла договора (только для администраторов).
    contract_type: 'guarantor' или 'sublease'
    """
    
    # Проверяем права доступа (только админы)
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для загрузки договоров"
        )
    
    if contract_type not in ["guarantor", "sublease"]:
        raise HTTPException(
            status_code=400,
            detail="Неверный тип договора. Используйте 'guarantor' или 'sublease'"
        )
    
    # Проверяем тип файла
    if file.content_type not in ALLOWED_CONTRACT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Неподдерживаемый тип файла. Разрешены только PDF и DOC/DOCX"
        )
    
    try:
        # Деактивируем старые файлы этого типа
        db.query(ContractFile).filter(
            ContractFile.contract_type == contract_type,
            ContractFile.is_active == True
        ).update({"is_active": False})
        
        # Сохраняем новый файл
        file_path = await save_contract_file(file, contract_type)
        
        # Создаем запись в БД
        contract_file = ContractFile(
            contract_type=contract_type,
            file_path=file_path,
            file_name=file.filename,
            is_active=True
        )
        
        db.add(contract_file)
        db.commit()
        db.refresh(contract_file)
        
        return {
            "message": f"Договор типа '{contract_type}' успешно загружен",
            "file_id": contract_file.id,
            "file_path": file_path
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при загрузке файла: {str(e)}"
        )


@guarantor_router.get("/contracts", response_model=ContractListSchema)
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


@guarantor_router.post("/admin/reject-user-with-guarantor")
async def reject_user_with_guarantor_offer(
    rejection_data: RejectUserWithGuarantorSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Отклонение пользователя с предложением использовать гаранта
    (только для администраторов)
    """
    
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для выполнения этой операции"
        )
    
    # Находим пользователя
    user = db.query(User).filter(User.id == rejection_data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Обновляем статус пользователя
    user.role = UserRole.REJECTED
    db.commit()
    
    # Отправляем SMS с предложением гаранта
    sms_result = await send_user_rejection_with_guarantor_sms(
        user.phone_number,
        user.full_name or user.phone_number,
        rejection_data.rejection_reason
    )
    
    return {
        "message": "Пользователь отклонен, SMS с предложением гаранта отправлено",
        "sms_result": sms_result
    }


@guarantor_router.post("/check-user-eligibility", response_model=UserEligibilityResultSchema)
async def check_user_eligibility(
    check_data: CheckUserEligibilitySchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Проверка платежеспособности пользователя по номеру телефона"""
    
    user = db.query(User).filter(
        User.phone_number == check_data.phone_number,
        User.is_active == True
    ).first()
    
    if not user:
        return UserEligibilityResultSchema(
            user_exists=False,
            user_id=None,
            is_eligible=False,
            has_car_access=False,
            user_name=None,
            reason="Пользователь не найден в системе"
        )
    
    # Проверяем, есть ли у пользователя доступ к автомобилю
    has_car_access = False
    
    # Проверяем собственные автомобили
    owned_cars = db.query(Car).filter(Car.owner_id == user.id).first()
    if owned_cars:
        has_car_access = True
    
    # Проверяем активные аренды
    if not has_car_access:
        active_rental = db.query(RentalHistory).filter(
            RentalHistory.user_id == user.id,
            RentalHistory.rental_status.in_([
                RentalStatus.RESERVED,
                RentalStatus.IN_USE,
                RentalStatus.DELIVERING
            ])
        ).first()
        if active_rental:
            has_car_access = True
    
    # Определяем платежеспособность
    is_eligible = True
    reason = None
    
    # Проверяем баланс кошелька
    if user.wallet_balance < 0:
        is_eligible = False
        reason = "Отрицательный баланс кошелька"
    
    # Проверяем роль пользователя
    if user.role in [UserRole.REJECTED, UserRole.PENDING]:
        is_eligible = False
        reason = f"Неподходящий статус пользователя: {user.role.value}"
    
    return UserEligibilityResultSchema(
        user_exists=True,
        user_id=user.id,
        is_eligible=is_eligible,
        has_car_access=has_car_access,
        user_name=user.full_name,
        reason=reason if not is_eligible else None
    )


@guarantor_router.get("/info")
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
