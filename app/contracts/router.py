from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import base64
import os
import uuid
from app.utils.short_id import safe_sid_to_uuid, uuid_to_sid
from datetime import datetime

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.contract_model import ContractFile, ContractType, UserContractSignature
from app.models.history_model import RentalHistory
from app.models.guarantor_model import Guarantor
from app.contracts.schemas import (
    ContractFileUpload,
    ContractUploadByType,
    ContractFileResponse,
    SignContractRequest,
    SignContractByTypeRequest,
    UserSignatureResponse,
    UserContractsResponse,
    ContractRequirements,
    RentalContractStatus,
    GuarantorContractStatus
)

ContractsRouter = APIRouter(prefix="/contracts", tags=["Contracts"])


@ContractsRouter.post("/upload", response_model=ContractFileResponse)
async def upload_contract(
    contract_data: ContractFileUpload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Загрузить договор (только для админа)
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только администратор может загружать договоры"
        )
    
    # Создаем директорию для договоров если её нет
    contracts_dir = "uploads/contracts"
    os.makedirs(contracts_dir, exist_ok=True)
    
    # Обрабатываем base64
    file_content = contract_data.file_content
    if file_content.startswith("data:"):
        # Убираем data URL prefix
        file_content = file_content.split(",")[1]
    
    # Декодируем base64
    try:
        file_bytes = base64.b64decode(file_content)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ошибка декодирования файла: {str(e)}"
        )
    
    # Генерируем имя файла
    file_extension = os.path.splitext(contract_data.file_name)[1]
    unique_filename = f"{contract_data.contract_type.value}_{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(contracts_dir, unique_filename)
    
    # Сохраняем файл
    with open(file_path, "wb") as f:
        f.write(file_bytes)
    
    # Деактивируем предыдущие версии этого типа договора
    db.query(ContractFile).filter(
        ContractFile.contract_type == contract_data.contract_type,
        ContractFile.is_active == True
    ).update({"is_active": False})
    
    # Создаем запись в БД
    contract_file = ContractFile(
        contract_type=contract_data.contract_type,
        file_path=file_path,
        file_name=contract_data.file_name
    )
    db.add(contract_file)
    db.commit()
    db.refresh(contract_file)
    
    return ContractFileResponse(
        id=uuid_to_sid(contract_file.id),
        contract_type=contract_file.contract_type,
        file_name=contract_file.file_name,
        is_active=contract_file.is_active,
        uploaded_at=contract_file.uploaded_at,
        file_url=f"/contracts/download/{uuid_to_sid(contract_file.id)}"
    )


@ContractsRouter.post("/upload-by-type", response_model=dict)
async def upload_contract_by_type(
    contract_data: ContractUploadByType,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Загрузить договор по типу (только для админа)
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только администратор может загружать договоры"
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
        
        # Создаем директорию для договоров если её нет
        contracts_dir = "uploads/contracts"
        os.makedirs(contracts_dir, exist_ok=True)
        
        # Генерируем случайное имя файла с правильным расширением
        unique_filename = f"{contract_data.contract_type.value}_{uuid.uuid4()}{file_extension}"
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
    
        return {"message": f"Договор {contract_data.contract_type.value} успешно загружен"}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при загрузке файла: {str(e)}"
        )


@ContractsRouter.get("/available", response_model=List[ContractFileResponse])
async def get_available_contracts(
    contract_type: ContractType = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получить список доступных договоров
    """
    query = db.query(ContractFile).filter(ContractFile.is_active == True)
    
    if contract_type:
        query = query.filter(ContractFile.contract_type == contract_type)
    
    contracts = query.all()
    
    return [
        ContractFileResponse(
            id=uuid_to_sid(contract.id),
            contract_type=contract.contract_type,
            file_name=contract.file_name,
            is_active=contract.is_active,
            uploaded_at=contract.uploaded_at,
            file_url=f"/contracts/download/{uuid_to_sid(contract.id)}"
        )
        for contract in contracts
    ]


@ContractsRouter.get("/download/{contract_id}")
async def download_contract(
    contract_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Скачать договор
    """
    contract_uuid = safe_sid_to_uuid(contract_id)
    contract = db.query(ContractFile).filter(ContractFile.id == contract_uuid).first()
    
    if not contract:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Договор не найден"
        )
    
    if not os.path.exists(contract.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл договора не найден"
        )
    
    with open(contract.file_path, "rb") as f:
        file_content = f.read()
    
    # Возвращаем base64
    file_base64 = base64.b64encode(file_content).decode()
    
    return {
        "file_name": contract.file_name,
        "contract_type": contract.contract_type,
        "file_content": f"data:application/pdf;base64,{file_base64}"
    }


@ContractsRouter.post("/sign", response_model=UserSignatureResponse)
async def sign_contract(
    sign_request: SignContractRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Подписать договор
    """
    # Проверяем существование договора
    contract_file_uuid = safe_sid_to_uuid(sign_request.contract_file_id)
    contract_file = db.query(ContractFile).filter(
        ContractFile.id == contract_file_uuid,
        ContractFile.is_active == True
    ).first()
    
    if not contract_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Договор не найден"
        )
    
    # Проверяем, что у пользователя есть цифровая подпись
    if not current_user.digital_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="У пользователя отсутствует цифровая подпись"
        )
    
    # Проверяем, не подписан ли уже этот договор
    existing_signature = db.query(UserContractSignature).filter(
        UserContractSignature.user_id == current_user.id,
        UserContractSignature.contract_file_id == contract_file_uuid,
        UserContractSignature.rental_id == sign_request.rental_id,
        UserContractSignature.guarantor_relationship_id == sign_request.guarantor_relationship_id
    ).first()
    
    if existing_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этот договор уже подписан"
        )
    
    # Валидация для договоров аренды
    if contract_file.contract_type in [ContractType.APPENDIX_7_START, ContractType.APPENDIX_7_END]:
        if not sign_request.rental_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для договоров аренды необходимо указать rental_id"
            )
        
        rental = db.query(RentalHistory).filter(RentalHistory.id == sign_request.rental_id).first()
        if not rental or rental.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Аренда не найдена или не принадлежит пользователю"
            )
    
    # Валидация для договоров гаранта
    if contract_file.contract_type in [ContractType.GUARANTOR_CONTRACT, ContractType.GUARANTOR_MAIN_CONTRACT]:
        if not sign_request.guarantor_relationship_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для договоров гаранта необходимо указать guarantor_relationship_id"
            )
        
        guarantor_rel_uuid = safe_sid_to_uuid(sign_request.guarantor_relationship_id)
        guarantor_rel = db.query(Guarantor).filter(Guarantor.id == guarantor_rel_uuid).first()
        if not guarantor_rel or guarantor_rel.guarantor_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Связь гарант-клиент не найдена или не принадлежит пользователю"
            )
    
    # Создаем подпись
    signature = UserContractSignature(
        user_id=current_user.id,
        contract_file_id=contract_file_uuid,
        rental_id=sign_request.rental_id,
        guarantor_relationship_id=guarantor_rel_uuid if contract_file.contract_type in [ContractType.GUARANTOR_CONTRACT, ContractType.GUARANTOR_MAIN_CONTRACT] else None,
        digital_signature=current_user.digital_signature
    )
    
    db.add(signature)
    db.commit()
    db.refresh(signature)
    
    return UserSignatureResponse(
        id=signature.id,
        user_id=signature.user_id,
        contract_file_id=uuid_to_sid(signature.contract_file_id),
        contract_type=contract_file.contract_type,
        digital_signature=signature.digital_signature,
        signed_at=signature.signed_at,
        rental_id=signature.rental_id,
        guarantor_relationship_id=uuid_to_sid(signature.guarantor_relationship_id) if signature.guarantor_relationship_id else None
    )


@ContractsRouter.post("/sign-by-type", response_model=UserSignatureResponse)
async def sign_contract_by_type(
    sign_request: SignContractByTypeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Подписать договор по типу (автоматически найдет активный файл договора)
    """
    # Находим активный файл договора указанного типа
    contract_file = db.query(ContractFile).filter(
        ContractFile.contract_type == sign_request.contract_type,
        ContractFile.is_active == True
    ).first()
    
    if not contract_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Активный договор типа {sign_request.contract_type.value} не найден"
        )
    
    # Проверяем, что у пользователя есть цифровая подпись
    if not current_user.digital_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="У пользователя отсутствует цифровая подпись"
        )
    
    # Проверяем, не подписан ли уже этот договор
    existing_signature = db.query(UserContractSignature).filter(
        UserContractSignature.user_id == current_user.id,
        UserContractSignature.contract_file_id == contract_file.id,
        UserContractSignature.rental_id == sign_request.rental_id,
        UserContractSignature.guarantor_relationship_id == sign_request.guarantor_relationship_id
    ).first()
    
    if existing_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этот договор уже подписан"
        )
    
    # Валидация для договоров аренды
    if contract_file.contract_type in [ContractType.APPENDIX_7_START, ContractType.APPENDIX_7_END]:
        if not sign_request.rental_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для договоров аренды необходимо указать rental_id"
            )
        
        rental = db.query(RentalHistory).filter(RentalHistory.id == sign_request.rental_id).first()
        if not rental or rental.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Аренда не найдена или не принадлежит пользователю"
            )
    
    # Валидация для договоров гаранта
    if contract_file.contract_type in [ContractType.GUARANTOR_CONTRACT, ContractType.GUARANTOR_MAIN_CONTRACT]:
        if not sign_request.guarantor_relationship_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для договоров гаранта необходимо указать guarantor_relationship_id"
            )
        
        guarantor_rel_uuid = safe_sid_to_uuid(sign_request.guarantor_relationship_id)
        guarantor_rel = db.query(Guarantor).filter(Guarantor.id == guarantor_rel_uuid).first()
        if not guarantor_rel or guarantor_rel.guarantor_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Связь гарант-клиент не найдена или не принадлежит пользователю"
            )
    
    # Создаем подпись
    signature = UserContractSignature(
        user_id=current_user.id,
        contract_file_id=contract_file.id,
        rental_id=sign_request.rental_id,
        guarantor_relationship_id=guarantor_rel_uuid if contract_file.contract_type in [ContractType.GUARANTOR_CONTRACT, ContractType.GUARANTOR_MAIN_CONTRACT] else None,
        digital_signature=current_user.digital_signature
    )
    
    db.add(signature)
    db.commit()
    db.refresh(signature)
    
    return UserSignatureResponse(
        id=signature.id,
        user_id=signature.user_id,
        contract_file_id=uuid_to_sid(signature.contract_file_id),
        contract_type=contract_file.contract_type,
        digital_signature=signature.digital_signature,
        signed_at=signature.signed_at,
        rental_id=signature.rental_id,
        guarantor_relationship_id=uuid_to_sid(signature.guarantor_relationship_id) if signature.guarantor_relationship_id else None
    )


@ContractsRouter.get("/my-contracts", response_model=UserContractsResponse)
async def get_my_contracts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получить список подписанных договоров текущего пользователя
    """
    signatures = db.query(UserContractSignature).filter(
        UserContractSignature.user_id == current_user.id
    ).all()
    
    registration_contracts = []
    rental_contracts = []
    guarantor_contracts = []
    
    for sig in signatures:
        contract_file = db.query(ContractFile).filter(ContractFile.id == sig.contract_file_id).first()
        
        response = UserSignatureResponse(
            id=uuid_to_sid(sig.id),
            user_id=uuid_to_sid(sig.user_id),
            contract_file_id=uuid_to_sid(sig.contract_file_id),
            contract_type=contract_file.contract_type if contract_file else None,
            digital_signature=sig.digital_signature,
            signed_at=sig.signed_at,
            rental_id=uuid_to_sid(sig.rental_id) if sig.rental_id else None,
            guarantor_relationship_id=uuid_to_sid(sig.guarantor_relationship_id) if sig.guarantor_relationship_id else None
        )
        
        if contract_file:
            if contract_file.contract_type in [
                ContractType.USER_AGREEMENT,
                ContractType.MAIN_CONTRACT,
                ContractType.APPENDIX_1,
                ContractType.APPENDIX_2,
                ContractType.APPENDIX_3,
                ContractType.APPENDIX_4,
                ContractType.APPENDIX_5,
                ContractType.APPENDIX_6,
                ContractType.APPENDIX_7
            ]:
                registration_contracts.append(response)
            elif contract_file.contract_type in [ContractType.APPENDIX_7_START, ContractType.APPENDIX_7_END]:
                rental_contracts.append(response)
            elif contract_file.contract_type in [ContractType.GUARANTOR_CONTRACT, ContractType.GUARANTOR_MAIN_CONTRACT]:
                guarantor_contracts.append(response)
    
    return UserContractsResponse(
        registration_contracts=registration_contracts,
        rental_contracts=rental_contracts,
        guarantor_contracts=guarantor_contracts
    )


@ContractsRouter.get("/requirements", response_model=ContractRequirements)
async def get_contract_requirements(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Проверить требования к подписанию договоров
    """
    # Получаем все подписи пользователя
    signatures = db.query(UserContractSignature).join(ContractFile).filter(
        UserContractSignature.user_id == current_user.id
    ).all()
    
    signed_types = set()
    for sig in signatures:
        contract_file = db.query(ContractFile).filter(ContractFile.id == sig.contract_file_id).first()
        if contract_file:
            signed_types.add(contract_file.contract_type)
    
    user_agreement_signed = ContractType.USER_AGREEMENT in signed_types
    main_contract_signed = ContractType.MAIN_CONTRACT in signed_types
    
    appendix_1_signed = ContractType.APPENDIX_1 in signed_types
    appendix_2_signed = ContractType.APPENDIX_2 in signed_types
    appendix_3_signed = ContractType.APPENDIX_3 in signed_types
    appendix_4_signed = ContractType.APPENDIX_4 in signed_types
    appendix_5_signed = ContractType.APPENDIX_5 in signed_types
    appendix_6_signed = ContractType.APPENDIX_6 in signed_types
    appendix_7_signed = ContractType.APPENDIX_7 in signed_types
    
    # Для возможности аренды нужны все основные договоры и все приложения
    can_proceed_to_rental = (
        user_agreement_signed and
        main_contract_signed and
        appendix_1_signed and
        appendix_2_signed and
        appendix_3_signed and
        appendix_4_signed and
        appendix_5_signed and
        appendix_6_signed and
        appendix_7_signed
    )
    
    return ContractRequirements(
        user_id=uuid_to_sid(current_user.id),
        user_agreement_signed=user_agreement_signed,
        main_contract_signed=main_contract_signed,
        appendix_1_signed=appendix_1_signed,
        appendix_2_signed=appendix_2_signed,
        appendix_3_signed=appendix_3_signed,
        appendix_4_signed=appendix_4_signed,
        appendix_5_signed=appendix_5_signed,
        appendix_6_signed=appendix_6_signed,
        appendix_7_signed=appendix_7_signed,
        can_proceed_to_rental=can_proceed_to_rental
    )


@ContractsRouter.get("/rental/{rental_id}/status", response_model=RentalContractStatus)
async def get_rental_contract_status(
    rental_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Проверить статус договоров для конкретной аренды
    """
    rental_uuid = safe_sid_to_uuid(rental_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    
    if not rental:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Аренда не найдена"
        )
    
    if rental.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ запрещен"
        )
    
    signatures = db.query(UserContractSignature).join(ContractFile).filter(
        UserContractSignature.user_id == current_user.id,
        UserContractSignature.rental_id == rental_uuid
    ).all()
    
    appendix_7_start_signed = False
    appendix_7_end_signed = False
    
    for sig in signatures:
        contract_file = db.query(ContractFile).filter(ContractFile.id == sig.contract_file_id).first()
        if contract_file:
            if contract_file.contract_type == ContractType.APPENDIX_7_START:
                appendix_7_start_signed = True
            elif contract_file.contract_type == ContractType.APPENDIX_7_END:
                appendix_7_end_signed = True
    
    return RentalContractStatus(
        rental_id=uuid_to_sid(rental_uuid),
        appendix_7_start_signed=appendix_7_start_signed,
        appendix_7_end_signed=appendix_7_end_signed
    )


@ContractsRouter.get("/guarantor/{guarantor_relationship_id}/status", response_model=GuarantorContractStatus)
async def get_guarantor_contract_status(
    guarantor_relationship_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Проверить статус договоров гаранта
    """
    guarantor_rel_uuid = safe_sid_to_uuid(guarantor_relationship_id)
    guarantor_rel = db.query(Guarantor).filter(Guarantor.id == guarantor_rel_uuid).first()
    
    if not guarantor_rel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Связь гарант-клиент не найдена"
        )
    
    if guarantor_rel.guarantor_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ запрещен"
        )
    
    signatures = db.query(UserContractSignature).join(ContractFile).filter(
        UserContractSignature.user_id == current_user.id,
        UserContractSignature.guarantor_relationship_id == guarantor_rel_uuid
    ).all()
    
    guarantor_contract_signed = False
    guarantor_main_contract_signed = False
    
    for sig in signatures:
        contract_file = db.query(ContractFile).filter(ContractFile.id == sig.contract_file_id).first()
        if contract_file:
            if contract_file.contract_type == ContractType.GUARANTOR_CONTRACT:
                guarantor_contract_signed = True
            elif contract_file.contract_type == ContractType.GUARANTOR_MAIN_CONTRACT:
                guarantor_main_contract_signed = True
    
    can_guarantee = guarantor_contract_signed and guarantor_main_contract_signed
    
    return GuarantorContractStatus(
        guarantor_relationship_id=guarantor_relationship_id,
        guarantor_contract_signed=guarantor_contract_signed,
        guarantor_main_contract_signed=guarantor_main_contract_signed,
        can_guarantee=can_guarantee
    )

