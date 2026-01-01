from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List
import base64
import os
import uuid
from app.utils.short_id import safe_sid_to_uuid, uuid_to_sid
from datetime import datetime, timezone, timedelta

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.contract_model import ContractFile, ContractType, UserContractSignature
from app.models.history_model import RentalHistory
from app.models.guarantor_model import Guarantor
from app.models.car_model import Car
from app.gps_api.utils.auth_api import get_auth_token
from app.core.config import GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD
from app.utils.telegram_logger import log_error_to_telegram, telegram_error_logger
from app.websocket.notifications import notify_user_status_update
import asyncio
import logging
from sqlalchemy import and_


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Очищаем существующие handlers, чтобы избежать дублирования
if not logger.handlers:
    # Добавляем handler для записи в файл (в корне проекта /app внутри контейнера)
    # Файл будет доступен на хосте через volume mount
    contract_log_file = "/app/contracts_debug.log"
    try:
        file_handler = logging.FileHandler(contract_log_file, mode='a', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        # Также добавляем handler для консоли (чтобы видеть логи сразу)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        logger.info(f"📝 Contract signing logger initialized. Log file: {contract_log_file}")
    except Exception as e:
        print(f"⚠️ Failed to initialize contract logger: {e}")

from app.contracts.schemas import (
    ContractFileResponse,
    SignContractRequest,
    AdminSignContractRequest,
    UserSignatureResponse,
    UserContractsResponse,
    ContractRequirements,
    RentalContractStatus,
    GuarantorContractStatus
)
# decode_file_content_and_extension больше не используется

ContractsRouter = APIRouter(prefix="/contracts", tags=["Contracts"])
GMT_PLUS_5 = timezone(timedelta(hours=5))


def to_gmt_plus_5(dt: datetime | None) -> datetime | None:
    """Возвращает время как есть (время уже хранится в UTC+5 в базе как naive datetime)."""
    return dt


@ContractsRouter.post("/upload", response_model=ContractFileResponse)
async def upload_contract(
    file: UploadFile = File(..., description="Файл договора"),
    contract_type: ContractType = Form(..., description="Тип договора"),
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
    
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Файл не выбран"
        )
    
    file_extension = os.path.splitext(file.filename)[1].lower()
    if file_extension not in ['.pdf', '.doc', '.docx']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Поддерживаются только файлы PDF, DOC, DOCX"
        )
    
    contracts_dir = "uploads/contracts"
    os.makedirs(contracts_dir, exist_ok=True)
    
    file_content = await file.read()
    unique_filename = f"{contract_type.value}_{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(contracts_dir, unique_filename)
    
    with open(file_path, "wb") as f:
        f.write(file_content)
    
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка сохранения файла"
        )
    
    db.query(ContractFile).filter(
        ContractFile.contract_type == contract_type,
        ContractFile.is_active == True
    ).update({"is_active": False})
    
    contract_file = ContractFile(
        contract_type=contract_type,
        file_path=file_path,
        file_name=unique_filename
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
        file_url=f"/uploads/contracts/{contract_file.file_name}"
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
            file_url=f"/uploads/contracts/{contract.file_name}"
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
    
    Все договоры подписываются через файлы (ContractFile) и сохраняются в user_contract_signatures.
    При подписании определенных типов также обновляются поля в таблице users.
    """
    
    user_field_mapping = {
        ContractType.USER_AGREEMENT: "is_user_agreement",
        ContractType.CONSENT_TO_DATA_PROCESSING: "is_consent_to_data_processing", 
        ContractType.MAIN_CONTRACT: "is_contract_read"
    }
    
    contract_file = db.query(ContractFile).filter(
        ContractFile.contract_type == sign_request.contract_type,
        ContractFile.is_active == True
    ).first()
    
    if not contract_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Активный файл договора типа {sign_request.contract_type} не найден"
        )
    
    if not current_user.digital_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="У пользователя отсутствует цифровая подпись"
        )
    
    rental_uuid = None
    guarantor_rel_uuid = None
    
    logger.info("=" * 80)
    logger.info("🔍 [CONTRACT SIGN] Starting contract signing process")
    logger.info(f"🔍 User ID: {current_user.id}")
    logger.info(f"🔍 User phone: {current_user.phone_number}")
    logger.info(f"🔍 User role: {current_user.role}")
    logger.info(f"🔍 Contract type: {sign_request.contract_type}")
    logger.info(f"🔍 Contract file ID: {contract_file.id}")
    logger.info(f"🔍 Contract file is_active: {contract_file.is_active}")
    logger.info(f"🔍 Rental ID (from request): {sign_request.rental_id}")
    
    # Отправляем в Telegram о начале процесса
    try:
        await telegram_error_logger.send_info(
            f"📝 <b>Начало подписания договора</b>\n\n"
            f"👤 <b>Пользователь:</b>\n"
            f"  • ID: <code>{current_user.id}</code>\n"
            f"  • ID (short): <code>{uuid_to_sid(current_user.id)}</code>\n"
            f"  • Телефон: <code>{current_user.phone_number}</code>\n"
            f"  • Роль: <code>{current_user.role}</code>\n\n"
            f"📄 <b>Договор:</b>\n"
            f"  • Тип: <code>{sign_request.contract_type}</code>\n"
            f"  • Contract File ID: <code>{contract_file.id}</code>\n"
            f"  • Contract File ID (short): <code>{uuid_to_sid(contract_file.id)}</code>\n"
            f"  • Активен: <code>{contract_file.is_active}</code>\n"
            f"  • Rental ID: <code>{sign_request.rental_id or 'None'}</code>\n"
            f"  • Guarantor Relationship ID: <code>{sign_request.guarantor_relationship_id or 'None'}</code>",
            context={"endpoint": "/contracts/sign"}
        )
    except Exception as e:
        logger.error(f"Error sending Telegram notification: {e}")
    
    if sign_request.rental_id:
        try:
            rental_uuid = uuid.UUID(sign_request.rental_id)
            logger.info(f"🔍 Rental UUID (converted): {rental_uuid}")
        except ValueError as e:
            logger.error(f"❌ Invalid rental_id format: {str(e)}")
            # Отправляем ошибку в Telegram
            try:
                await telegram_error_logger.send_warning(
                    f"⚠️ <b>Ошибка формата rental_id</b>\n\n"
                    f"👤 <b>Пользователь:</b>\n"
                    f"  • ID: <code>{current_user.id}</code>\n"
                    f"  • Телефон: <code>{current_user.phone_number}</code>\n\n"
                    f"❌ <b>Ошибка:</b> <code>{str(e)}</code>\n"
                    f"📝 <b>Rental ID (неверный формат):</b> <code>{sign_request.rental_id}</code>",
                    context={"endpoint": "/contracts/sign", "error_type": "Invalid rental_id format"}
                )
            except Exception as tg_error:
                logger.error(f"Error sending Telegram notification: {tg_error}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Неверный формат rental_id: {str(e)}"
            )
    else:
        logger.info("🔍 Rental ID is None")
    
    if sign_request.guarantor_relationship_id:
        try:
            guarantor_rel_uuid = uuid.UUID(sign_request.guarantor_relationship_id)
            logger.info(f"🔍 Guarantor UUID (converted): {guarantor_rel_uuid}")
        except ValueError as e:
            logger.error(f"❌ Invalid guarantor_relationship_id format: {str(e)}")
            # Отправляем ошибку в Telegram
            try:
                await telegram_error_logger.send_warning(
                    f"⚠️ <b>Ошибка формата guarantor_relationship_id</b>\n\n"
                    f"👤 <b>Пользователь:</b>\n"
                    f"  • ID: <code>{current_user.id}</code>\n"
                    f"  • Телефон: <code>{current_user.phone_number}</code>\n\n"
                    f"❌ <b>Ошибка:</b> <code>{str(e)}</code>\n"
                    f"📝 <b>Guarantor Relationship ID (неверный формат):</b> <code>{sign_request.guarantor_relationship_id}</code>",
                    context={"endpoint": "/contracts/sign", "error_type": "Invalid guarantor_relationship_id format"}
                )
            except Exception as tg_error:
                logger.error(f"Error sending Telegram notification: {tg_error}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Неверный формат guarantor_relationship_id: {str(e)}"
            )
    else:
        logger.info("🔍 Guarantor relationship ID is None")
    
    # Проверяем существующую подпись с правильной обработкой NULL значений
    from sqlalchemy import or_, and_
    
    logger.info("🔍 Building filters for existing signature check...")
    
    existing_signature_filters = [
        UserContractSignature.user_id == current_user.id,
        UserContractSignature.contract_file_id == contract_file.id
    ]
    
    logger.info(f"🔍 Filter 1: user_id == {current_user.id}")
    logger.info(f"🔍 Filter 2: contract_file_id == {contract_file.id}")
    
    # Для rental_id: если передан, проверяем точное совпадение, если None - проверяем что rental_id IS NULL
    if rental_uuid is not None:
        existing_signature_filters.append(UserContractSignature.rental_id == rental_uuid)
        logger.info(f"🔍 Filter 3: rental_id == {rental_uuid}")
    else:
        existing_signature_filters.append(UserContractSignature.rental_id.is_(None))
        logger.info("🔍 Filter 3: rental_id IS NULL")
    
    # Для guarantor_relationship_id: если передан, проверяем точное совпадение, если None - проверяем что guarantor_relationship_id IS NULL
    if guarantor_rel_uuid is not None:
        existing_signature_filters.append(UserContractSignature.guarantor_relationship_id == guarantor_rel_uuid)
        logger.info(f"🔍 Filter 4: guarantor_relationship_id == {guarantor_rel_uuid}")
    else:
        existing_signature_filters.append(UserContractSignature.guarantor_relationship_id.is_(None))
        logger.info("🔍 Filter 4: guarantor_relationship_id IS NULL")
    
    logger.info("🔍 Executing query to check for existing signature...")
    existing_signature = db.query(UserContractSignature).filter(
        and_(*existing_signature_filters)
    ).first()
    
    if existing_signature:
        logger.error("❌ FOUND EXISTING SIGNATURE!")
        logger.error(f"❌ Existing signature ID: {existing_signature.id}")
        logger.error(f"❌ Existing signature user_id: {existing_signature.user_id}")
        logger.error(f"❌ Existing signature contract_file_id: {existing_signature.contract_file_id}")
        logger.error(f"❌ Existing signature rental_id: {existing_signature.rental_id}")
        logger.error(f"❌ Existing signature guarantor_relationship_id: {existing_signature.guarantor_relationship_id}")
        logger.error(f"❌ Existing signature signed_at: {existing_signature.signed_at}")
        
        # Получаем информацию о существующей подписи для отладки
        existing_contract_file = db.query(ContractFile).filter(
            ContractFile.id == existing_signature.contract_file_id
        ).first()
        
        if existing_contract_file:
            logger.error(f"❌ Existing contract file type: {existing_contract_file.contract_type}")
            logger.error(f"❌ Existing contract file is_active: {existing_contract_file.is_active}")
        
        detail_msg = f"Этот договор уже подписан. Подпись ID: {uuid_to_sid(existing_signature.id)}, "
        detail_msg += f"Contract File ID: {uuid_to_sid(existing_signature.contract_file_id)}, "
        detail_msg += f"Активен: {existing_contract_file.is_active if existing_contract_file else 'Unknown'}, "
        detail_msg += f"Дата подписания: {existing_signature.signed_at}"
        
        # Отправляем предупреждение в Telegram
        try:
            # Проверяем, совпадают ли contract_file_id
            is_same_file = existing_signature.contract_file_id == contract_file.id
            
            await telegram_error_logger.send_warning(
                f"⚠️ <b>Попытка повторного подписания договора</b>\n\n"
                f"👤 <b>Пользователь:</b>\n"
                f"  • ID: <code>{current_user.id}</code>\n"
                f"  • ID (short): <code>{uuid_to_sid(current_user.id)}</code>\n"
                f"  • Телефон: <code>{current_user.phone_number}</code>\n"
                f"  • Роль: <code>{current_user.role}</code>\n\n"
                f"📄 <b>Запрос на подписание:</b>\n"
                f"  • Тип: <code>{sign_request.contract_type}</code>\n"
                f"  • Contract File ID: <code>{contract_file.id}</code>\n"
                f"  • Contract File ID (short): <code>{uuid_to_sid(contract_file.id)}</code>\n"
                f"  • Rental ID: <code>{sign_request.rental_id or 'None'}</code>\n\n"
                f"🔍 <b>Найдена существующая подпись:</b>\n"
                f"  • Signature ID: <code>{existing_signature.id}</code>\n"
                f"  • Signature ID (short): <code>{uuid_to_sid(existing_signature.id)}</code>\n"
                f"  • Contract File ID: <code>{existing_signature.contract_file_id}</code>\n"
                f"  • Contract File ID (short): <code>{uuid_to_sid(existing_signature.contract_file_id)}</code>\n"
                f"  • <b>{'✅ Тот же файл' if is_same_file else '❌ РАЗНЫЕ ФАЙЛЫ!'}</b>\n"
                f"  • Активен: <code>{existing_contract_file.is_active if existing_contract_file else 'Unknown'}</code>\n"
                f"  • Дата подписания: <code>{existing_signature.signed_at}</code>\n"
                f"  • Rental ID: <code>{existing_signature.rental_id or 'None'}</code>\n"
                f"  • Guarantor Relationship ID: <code>{existing_signature.guarantor_relationship_id or 'None'}</code>",
                context={
                    "endpoint": "/contracts/sign",
                    "existing_signature_id": str(existing_signature.id),
                    "request_contract_file_id": str(contract_file.id),
                    "is_same_file": is_same_file
                }
            )
        except Exception as e:
            logger.error(f"Error sending Telegram warning: {e}")
        
        logger.info("=" * 80)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail_msg
        )
    else:
        logger.info("✅ No existing signature found, proceeding with signing...")

    # Проверяем, есть ли уже подпись этого типа договора для этой аренды/гаранта
    # Но только если это НЕ договор аренды (для договоров аренды разрешаем подписание нового contract_file_id)
    if contract_file.contract_type not in [ContractType.RENTAL_MAIN_CONTRACT, ContractType.APPENDIX_7_1, ContractType.APPENDIX_7_2]:
        same_type_filters = [
            UserContractSignature.user_id == current_user.id,
            ContractFile.contract_type == sign_request.contract_type,
            ContractFile.is_active == True
        ]
        
        # Для rental_id: если передан, проверяем точное совпадение, если None - проверяем что rental_id IS NULL
        if rental_uuid is not None:
            same_type_filters.append(UserContractSignature.rental_id == rental_uuid)
        else:
            same_type_filters.append(UserContractSignature.rental_id.is_(None))
        
        # Для guarantor_relationship_id: если передан, проверяем точное совпадение, если None - проверяем что guarantor_relationship_id IS NULL
        if guarantor_rel_uuid is not None:
            same_type_filters.append(UserContractSignature.guarantor_relationship_id == guarantor_rel_uuid)
        else:
            same_type_filters.append(UserContractSignature.guarantor_relationship_id.is_(None))
        
        same_type_active = db.query(UserContractSignature).join(ContractFile).filter(
            and_(*same_type_filters)
        ).first()
        
        if same_type_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Этот тип договора уже подписан"
            )
    
    if contract_file.contract_type in [ContractType.RENTAL_MAIN_CONTRACT, ContractType.APPENDIX_7_1, ContractType.APPENDIX_7_2]:
        logger.info("🔍 Checking rental contract requirements...")
        if not sign_request.rental_id:
            logger.error("❌ rental_id is required for rental contracts")
            try:
                await telegram_error_logger.send_warning(
                    f"⚠️ <b>Отсутствует rental_id для договора аренды</b>\n\n"
                    f"👤 <b>Пользователь:</b>\n"
                    f"  • ID: <code>{current_user.id}</code>\n"
                    f"  • Телефон: <code>{current_user.phone_number}</code>\n\n"
                    f"📄 <b>Договор:</b>\n"
                    f"  • Тип: <code>{sign_request.contract_type}</code>\n"
                    f"  • Contract File ID: <code>{contract_file.id}</code>",
                    context={"endpoint": "/contracts/sign", "error_type": "Missing rental_id"}
                )
            except Exception as tg_error:
                logger.error(f"Error sending Telegram notification: {tg_error}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для договоров аренды необходимо указать rental_id"
            )
        
        rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
        if not rental:
            logger.error(f"❌ Rental not found: {rental_uuid}")
            try:
                await telegram_error_logger.send_warning(
                    f"⚠️ <b>Аренда не найдена</b>\n\n"
                    f"👤 <b>Пользователь:</b>\n"
                    f"  • ID: <code>{current_user.id}</code>\n"
                    f"  • Телефон: <code>{current_user.phone_number}</code>\n\n"
                    f"📄 <b>Договор:</b>\n"
                    f"  • Тип: <code>{sign_request.contract_type}</code>\n"
                    f"  • Rental ID: <code>{rental_uuid}</code>",
                    context={"endpoint": "/contracts/sign", "error_type": "Rental not found", "rental_id": str(rental_uuid)}
                )
            except Exception as tg_error:
                logger.error(f"Error sending Telegram notification: {tg_error}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Аренда не найдена"
            )
        
        logger.info(f"🔍 Rental found: {rental.id}")
        logger.info(f"🔍 Rental status: {rental.rental_status}")
        logger.info(f"🔍 Rental user_id: {rental.user_id}")
        logger.info(f"🔍 Rental mechanic_inspector_id: {rental.mechanic_inspector_id}")
        logger.info(f"🔍 Rental delivery_mechanic_id: {rental.delivery_mechanic_id}")
        
        # Для механиков разрешаем подписание договоров для аренд, где они являются инспекторами или доставщиками
        if current_user.role == UserRole.MECHANIC:
            # Механик может подписывать договоры для аренд, где он является инспектором или доставщиком
            is_inspector = rental.mechanic_inspector_id == current_user.id
            is_delivery_mechanic = rental.delivery_mechanic_id == current_user.id
            
            logger.info(f"🔍 Is inspector: {is_inspector}")
            logger.info(f"🔍 Is delivery mechanic: {is_delivery_mechanic}")
            
            if not (is_inspector or is_delivery_mechanic):
                logger.error("❌ Mechanic is not assigned to this rental")
                try:
                    await telegram_error_logger.send_warning(
                        f"⚠️ <b>Механик не авторизован для подписания договора</b>\n\n"
                        f"👤 <b>Механик:</b>\n"
                        f"  • ID: <code>{current_user.id}</code>\n"
                        f"  • Телефон: <code>{current_user.phone_number}</code>\n\n"
                        f"📄 <b>Договор:</b>\n"
                        f"  • Тип: <code>{sign_request.contract_type}</code>\n"
                        f"  • Rental ID: <code>{rental_uuid}</code>\n\n"
                        f"🔍 <b>Проверка:</b>\n"
                        f"  • Is Inspector: <code>{is_inspector}</code>\n"
                        f"  • Is Delivery Mechanic: <code>{is_delivery_mechanic}</code>\n"
                        f"  • Rental Inspector ID: <code>{rental.mechanic_inspector_id or 'None'}</code>\n"
                        f"  • Rental Delivery ID: <code>{rental.delivery_mechanic_id or 'None'}</code>",
                        context={
                            "endpoint": "/contracts/sign",
                            "error_type": "Mechanic not authorized",
                            "rental_id": str(rental_uuid)
                        }
                    )
                except Exception as tg_error:
                    logger.error(f"Error sending Telegram notification: {tg_error}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Механик не назначен инспектором или доставщиком для данной аренды"
                )
            logger.info("✅ Mechanic is authorized to sign this contract")
        else:
            # Для обычных пользователей проверяем, что аренда принадлежит им
            if rental.user_id != current_user.id:
                logger.error(f"❌ Rental does not belong to user. Rental user_id: {rental.user_id}, Current user: {current_user.id}")
                try:
                    await telegram_error_logger.send_warning(
                        f"⚠️ <b>Аренда не принадлежит пользователю</b>\n\n"
                        f"👤 <b>Пользователь:</b>\n"
                        f"  • ID: <code>{current_user.id}</code>\n"
                        f"  • Телефон: <code>{current_user.phone_number}</code>\n\n"
                        f"📄 <b>Договор:</b>\n"
                        f"  • Тип: <code>{sign_request.contract_type}</code>\n"
                        f"  • Rental ID: <code>{rental_uuid}</code>\n\n"
                        f"🔍 <b>Проверка:</b>\n"
                        f"  • Rental User ID: <code>{rental.user_id}</code>\n"
                        f"  • Current User ID: <code>{current_user.id}</code>",
                        context={
                            "endpoint": "/contracts/sign",
                            "error_type": "Rental does not belong to user",
                            "rental_id": str(rental_uuid)
                        }
                    )
                except Exception as tg_error:
                    logger.error(f"Error sending Telegram notification: {tg_error}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Аренда не принадлежит пользователю"
                )
            logger.info("✅ User is authorized to sign this contract")
            logger.info("✅ User is authorized to sign this contract")
    
    if sign_request.contract_type in [ContractType.GUARANTOR_CONTRACT, ContractType.GUARANTOR_MAIN_CONTRACT]:
        if not sign_request.guarantor_relationship_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для договоров гаранта необходимо указать guarantor_relationship_id"
            )
        
        guarantor_rel = db.query(Guarantor).filter(Guarantor.id == guarantor_rel_uuid).first()
        if not guarantor_rel or guarantor_rel.guarantor_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Связь гарант-клиент не найдена или не принадлежит пользователю"
            )
    
    logger.info("🔍 Creating new signature...")
    signature = UserContractSignature(
        user_id=current_user.id,
        contract_file_id=contract_file.id,
        rental_id=rental_uuid if contract_file.contract_type in [ContractType.RENTAL_MAIN_CONTRACT, ContractType.APPENDIX_7_1, ContractType.APPENDIX_7_2] else None,
        guarantor_relationship_id=guarantor_rel_uuid if sign_request.contract_type in [ContractType.GUARANTOR_CONTRACT, ContractType.GUARANTOR_MAIN_CONTRACT] else None,
        digital_signature=current_user.digital_signature
    )
    
    logger.info(f"🔍 New signature user_id: {signature.user_id}")
    logger.info(f"🔍 New signature contract_file_id: {signature.contract_file_id}")
    logger.info(f"🔍 New signature rental_id: {signature.rental_id}")
    logger.info(f"🔍 New signature guarantor_relationship_id: {signature.guarantor_relationship_id}")
    
    db.add(signature)
    db.commit()
    db.refresh(signature)
    
    logger.info(f"✅ Signature created successfully! Signature ID: {signature.id}")
    logger.info("=" * 80)
    
    if sign_request.contract_type in user_field_mapping:
        field_name = user_field_mapping[sign_request.contract_type]
        setattr(current_user, field_name, True)
        db.add(current_user)
        db.commit()
    
    db.expire_all()
    db.refresh(current_user)
    
    # Отправляем успешное подписание в Telegram
    try:
        await telegram_error_logger.send_info(
            f"✅ <b>Договор успешно подписан</b>\n\n"
            f"👤 <b>Пользователь:</b>\n"
            f"  • ID: <code>{current_user.id}</code>\n"
            f"  • Телефон: <code>{current_user.phone_number}</code>\n"
            f"  • Роль: <code>{current_user.role}</code>\n\n"
            f"📄 <b>Договор:</b>\n"
            f"  • Тип: <code>{sign_request.contract_type}</code>\n"
            f"  • Contract File ID: <code>{contract_file.id}</code>\n"
            f"  • Signature ID: <code>{uuid_to_sid(signature.id)}</code>\n"
            f"  • Rental ID: <code>{signature.rental_id or 'None'}</code>\n"
            f"  • Guarantor Relationship ID: <code>{signature.guarantor_relationship_id or 'None'}</code>\n"
            f"  • Дата подписания: <code>{signature.signed_at}</code>",
            context={
                "endpoint": "/contracts/sign",
                "signature_id": str(signature.id),
                "contract_type": str(sign_request.contract_type)
            }
        )
    except Exception as e:
        logger.error(f"Error sending Telegram notification: {e}")
    
    try:
        await notify_user_status_update(str(current_user.id))
        logger.info(f"WebSocket user_status notification sent for user {current_user.id} after contract signing")
    except Exception as e:
        logger.error(f"Error sending WebSocket notification: {e}")
    
    # Если это договор гаранта, также обновляем клиента
    if sign_request.contract_type in [ContractType.GUARANTOR_CONTRACT, ContractType.GUARANTOR_MAIN_CONTRACT] and guarantor_rel_uuid:
        guarantor_rel = db.query(Guarantor).filter(Guarantor.id == guarantor_rel_uuid).first()
        if guarantor_rel:
            try:
                await notify_user_status_update(str(guarantor_rel.client_id))
                logger.info(f"WebSocket user_status notification sent for client {guarantor_rel.client_id} after guarantor contract signing")
            except Exception as e:
                logger.error(f"Error sending WebSocket notification to client: {e}")
    
    return UserSignatureResponse(
        id=uuid_to_sid(signature.id),
        user_id=uuid_to_sid(signature.user_id),
        contract_file_id=uuid_to_sid(signature.contract_file_id),
        contract_type=sign_request.contract_type,
        digital_signature=signature.digital_signature,
        signed_at=to_gmt_plus_5(signature.signed_at),
        rental_id=str(signature.rental_id) if signature.rental_id else None,
        guarantor_relationship_id=str(signature.guarantor_relationship_id) if signature.guarantor_relationship_id else None
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
            signed_at=to_gmt_plus_5(sig.signed_at),
            rental_id=uuid_to_sid(sig.rental_id) if sig.rental_id else None,
            guarantor_relationship_id=uuid_to_sid(sig.guarantor_relationship_id) if sig.guarantor_relationship_id else None
        )
        
        if contract_file:
            if contract_file.contract_type in [
                ContractType.USER_AGREEMENT,
                ContractType.MAIN_CONTRACT,
                ContractType.CONSENT_TO_DATA_PROCESSING
            ]:
                registration_contracts.append(response)
            elif contract_file.contract_type in [ContractType.RENTAL_MAIN_CONTRACT, ContractType.APPENDIX_7_1, ContractType.APPENDIX_7_2]:
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
    consent_to_data_processing_signed = ContractType.CONSENT_TO_DATA_PROCESSING in signed_types
    
    # Для возможности аренды нужны основные договоры
    can_proceed_to_rental = (
        user_agreement_signed and
        main_contract_signed and
        consent_to_data_processing_signed
    )
    
    return ContractRequirements(
        user_id=uuid_to_sid(current_user.id),
        user_agreement_signed=user_agreement_signed,
        main_contract_signed=main_contract_signed,
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
    try:
        rental_uuid = safe_sid_to_uuid(rental_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неверный формат rental_id: {str(e)}"
        )
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    
    if not rental:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Аренда не найдена"
        )
    
    # Для механиков разрешаем доступ к арендам, где они являются инспекторами или доставщиками
    if current_user.role == UserRole.MECHANIC:
        is_inspector = rental.mechanic_inspector_id == current_user.id
        is_delivery_mechanic = rental.delivery_mechanic_id == current_user.id
        
        if not (is_inspector or is_delivery_mechanic):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Механик не назначен инспектором или доставщиком для данной аренды"
            )
    else:
        # Для обычных пользователей проверяем, что аренда принадлежит им
        if rental.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Доступ запрещен"
            )
    
    signatures = db.query(UserContractSignature).join(ContractFile).filter(
        UserContractSignature.user_id == current_user.id,
        UserContractSignature.rental_id == rental_uuid
    ).all()
    
    rental_main_contract_signed = False
    appendix_7_1_signed = False
    appendix_7_2_signed = False
    
    for sig in signatures:
        contract_file = db.query(ContractFile).filter(ContractFile.id == sig.contract_file_id).first()
        if contract_file:
            if contract_file.contract_type == ContractType.RENTAL_MAIN_CONTRACT:
                rental_main_contract_signed = True
            elif contract_file.contract_type == ContractType.APPENDIX_7_1:
                appendix_7_1_signed = True
            elif contract_file.contract_type == ContractType.APPENDIX_7_2:
                appendix_7_2_signed = True
    
    return RentalContractStatus(
        rental_id=uuid_to_sid(rental_uuid),
        rental_main_contract_signed=rental_main_contract_signed,
        appendix_7_1_signed=appendix_7_1_signed,
        appendix_7_2_signed=appendix_7_2_signed
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
    try:
        guarantor_rel_uuid = safe_sid_to_uuid(guarantor_relationship_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неверный формат guarantor_relationship_id: {str(e)}"
        )
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


@ContractsRouter.post("/admin/sign", response_model=UserSignatureResponse)
async def admin_sign_contract(
    sign_request: AdminSignContractRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Подписать договор от имени клиента (только для админа).
    
    Админ передает user_id клиента, и договор подписывается от имени этого клиента.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только администратор может подписывать договоры от имени клиентов"
        )
    
    try:
        client_uuid = safe_sid_to_uuid(sign_request.user_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неверный формат user_id: {str(e)}"
        )
    
    client = db.query(User).filter(User.id == client_uuid).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    user_field_mapping = {
        ContractType.USER_AGREEMENT: "is_user_agreement",
        ContractType.CONSENT_TO_DATA_PROCESSING: "is_consent_to_data_processing", 
        ContractType.MAIN_CONTRACT: "is_contract_read"
    }
    
    contract_file = db.query(ContractFile).filter(
        ContractFile.contract_type == sign_request.contract_type,
        ContractFile.is_active == True
    ).first()
    
    if not contract_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Активный файл договора типа {sign_request.contract_type} не найден"
        )
    
    if not client.digital_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="У клиента отсутствует цифровая подпись"
        )
    
    rental_uuid = None
    guarantor_rel_uuid = None

    if sign_request.rental_id:
        try:
            rental_uuid = uuid.UUID(sign_request.rental_id)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Неверный формат rental_id: {str(e)}"
            )
    
    if sign_request.guarantor_relationship_id:
        try:
            guarantor_rel_uuid = uuid.UUID(sign_request.guarantor_relationship_id)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Неверный формат guarantor_relationship_id: {str(e)}"
            )
        
    existing_signature_filters = [
        UserContractSignature.user_id == client.id,
        UserContractSignature.contract_file_id == contract_file.id
    ]
    
    if rental_uuid is not None:
        existing_signature_filters.append(UserContractSignature.rental_id == rental_uuid)
    else:
        existing_signature_filters.append(UserContractSignature.rental_id.is_(None))
    
    if guarantor_rel_uuid is not None:
        existing_signature_filters.append(UserContractSignature.guarantor_relationship_id == guarantor_rel_uuid)
    else:
        existing_signature_filters.append(UserContractSignature.guarantor_relationship_id.is_(None))
    
    existing_signature = db.query(UserContractSignature).filter(
        and_(*existing_signature_filters)
    ).first()
    
    if existing_signature:
        return UserSignatureResponse(
            id=uuid_to_sid(existing_signature.id),
            user_id=uuid_to_sid(existing_signature.user_id),
            contract_file_id=uuid_to_sid(existing_signature.contract_file_id),
            contract_type=sign_request.contract_type,
            digital_signature=existing_signature.digital_signature,
            signed_at=to_gmt_plus_5(existing_signature.signed_at),
            rental_id=str(existing_signature.rental_id) if existing_signature.rental_id else None,
            guarantor_relationship_id=str(existing_signature.guarantor_relationship_id) if existing_signature.guarantor_relationship_id else None,
            already_signed=True
        )
    
    if contract_file.contract_type in [ContractType.RENTAL_MAIN_CONTRACT, ContractType.APPENDIX_7_1, ContractType.APPENDIX_7_2]:
        if not sign_request.rental_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для договоров аренды необходимо указать rental_id"
            )
        
        rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
        if not rental:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Аренда не найдена"
            )
        
        if rental.user_id != client.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Аренда не принадлежит указанному пользователю"
            )
    
    if sign_request.contract_type in [ContractType.GUARANTOR_CONTRACT, ContractType.GUARANTOR_MAIN_CONTRACT]:
        if not sign_request.guarantor_relationship_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для договоров гаранта необходимо указать guarantor_relationship_id"
            )
        
        guarantor_rel = db.query(Guarantor).filter(Guarantor.id == guarantor_rel_uuid).first()
        if not guarantor_rel or guarantor_rel.guarantor_id != client.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Связь гарант-клиент не найдена или не принадлежит указанному пользователю"
            )
    
    signature = UserContractSignature(
        user_id=client.id,
        contract_file_id=contract_file.id,
        rental_id=rental_uuid if contract_file.contract_type in [ContractType.RENTAL_MAIN_CONTRACT, ContractType.APPENDIX_7_1, ContractType.APPENDIX_7_2] else None,
        guarantor_relationship_id=guarantor_rel_uuid if sign_request.contract_type in [ContractType.GUARANTOR_CONTRACT, ContractType.GUARANTOR_MAIN_CONTRACT] else None,
        digital_signature=client.digital_signature
    )
    
    db.add(signature)
    db.commit()
    db.refresh(signature)
    
    if sign_request.contract_type in user_field_mapping:
        field_name = user_field_mapping[sign_request.contract_type]
        setattr(client, field_name, True)
        db.add(client)
        db.commit()
    
    db.expire_all()
    db.refresh(client)
    
    try:
        await notify_user_status_update(str(client.id))
    except Exception as e:
        logger.error(f"Error sending WebSocket notification: {e}")
    
    logger.info("=" * 80)
    
    return UserSignatureResponse(
        id=uuid_to_sid(signature.id),
        user_id=uuid_to_sid(signature.user_id),
        contract_file_id=uuid_to_sid(signature.contract_file_id),
        contract_type=sign_request.contract_type,
        digital_signature=signature.digital_signature,
        signed_at=to_gmt_plus_5(signature.signed_at),
        rental_id=str(signature.rental_id) if signature.rental_id else None,
        guarantor_relationship_id=str(signature.guarantor_relationship_id) if signature.guarantor_relationship_id else None
    )
