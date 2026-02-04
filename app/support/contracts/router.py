"""
Роутер подписания договоров для поддержки (support).
Эндпоинты: POST /support/contracts/sign, POST /support/contracts/sign-mechanic.
"""
import uuid
from datetime import timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.logging_config import get_logger
from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.contract_model import ContractFile, ContractType, UserContractSignature
from app.models.history_model import RentalHistory, RentalStatus
from app.models.guarantor_model import Guarantor
from app.models.car_model import Car, CarStatus
from app.utils.short_id import safe_sid_to_uuid, uuid_to_sid
from app.utils.time_utils import get_local_time
from app.utils.action_logger import log_action
from app.websocket.notifications import notify_user_status_update

from app.support.deps import require_support_role
from app.contracts.schemas import AdminSignContractRequest, UserSignatureResponse

logger = get_logger(__name__)

support_contracts_router = APIRouter(tags=["Support Contracts"])
GMT_PLUS_5 = timezone(timedelta(hours=5))


def to_gmt_plus_5(dt):
    """Возвращает время как есть (время уже хранится в UTC+5 в базе как naive datetime)."""
    return dt


@support_contracts_router.post("/sign", response_model=UserSignatureResponse)
async def support_sign_contract(
    sign_request: AdminSignContractRequest,
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """
    Подписать договор от имени клиента (для поддержки и админа).

    Поддержка передает user_id клиента, договор подписывается от имени этого клиента.
    Логика идентична /contracts/admin/sign.
    """
    try:
        client_uuid = safe_sid_to_uuid(sign_request.user_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неверный формат user_id: {str(e)}",
        )

    client = db.query(User).filter(User.id == client_uuid).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        )

    user_field_mapping = {
        ContractType.USER_AGREEMENT: "is_user_agreement",
        ContractType.CONSENT_TO_DATA_PROCESSING: "is_consent_to_data_processing",
        ContractType.MAIN_CONTRACT: "is_contract_read",
    }

    contract_file = (
        db.query(ContractFile)
        .filter(
            ContractFile.contract_type == sign_request.contract_type,
            ContractFile.is_active == True,
        )
        .first()
    )

    if not contract_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Активный файл договора типа {sign_request.contract_type} не найден",
        )

    if not client.digital_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="У клиента отсутствует цифровая подпись",
        )

    rental_uuid = None
    guarantor_rel_uuid = None

    if sign_request.rental_id:
        try:
            rental_uuid = safe_sid_to_uuid(sign_request.rental_id)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Неверный формат rental_id: {str(e)}",
            )

    if sign_request.guarantor_relationship_id:
        try:
            guarantor_rel_uuid = safe_sid_to_uuid(sign_request.guarantor_relationship_id)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Неверный формат guarantor_relationship_id: {str(e)}",
            )

    existing_signature_filters = [
        UserContractSignature.user_id == client.id,
        UserContractSignature.contract_file_id == contract_file.id,
    ]

    if rental_uuid is not None:
        existing_signature_filters.append(UserContractSignature.rental_id == rental_uuid)
    else:
        existing_signature_filters.append(UserContractSignature.rental_id.is_(None))

    if guarantor_rel_uuid is not None:
        existing_signature_filters.append(
            UserContractSignature.guarantor_relationship_id == guarantor_rel_uuid
        )
    else:
        existing_signature_filters.append(
            UserContractSignature.guarantor_relationship_id.is_(None)
        )

    existing_signature = (
        db.query(UserContractSignature)
        .filter(and_(*existing_signature_filters))
        .first()
    )

    if existing_signature:
        return UserSignatureResponse(
            id=uuid_to_sid(existing_signature.id),
            user_id=uuid_to_sid(existing_signature.user_id),
            contract_file_id=uuid_to_sid(existing_signature.contract_file_id),
            contract_type=sign_request.contract_type,
            digital_signature=existing_signature.digital_signature,
            signed_at=to_gmt_plus_5(existing_signature.signed_at),
            rental_id=str(existing_signature.rental_id) if existing_signature.rental_id else None,
            guarantor_relationship_id=(
                str(existing_signature.guarantor_relationship_id)
                if existing_signature.guarantor_relationship_id
                else None
            ),
            already_signed=True,
        )

    if contract_file.contract_type in [
        ContractType.RENTAL_MAIN_CONTRACT,
        ContractType.APPENDIX_7_1,
        ContractType.APPENDIX_7_2,
    ]:
        if not sign_request.rental_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для договоров аренды необходимо указать rental_id",
            )

        rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
        if not rental:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Аренда не найдена",
            )

        if rental.user_id != client.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Аренда не принадлежит указанному пользователю",
            )

    if sign_request.contract_type in [
        ContractType.GUARANTOR_CONTRACT,
        ContractType.GUARANTOR_MAIN_CONTRACT,
    ]:
        if not sign_request.guarantor_relationship_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для договоров гаранта необходимо указать guarantor_relationship_id",
            )

        guarantor_rel = (
            db.query(Guarantor).filter(Guarantor.id == guarantor_rel_uuid).first()
        )
        if not guarantor_rel or guarantor_rel.guarantor_id != client.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Связь гарант-клиент не найдена или не принадлежит указанному пользователю",
            )

    signature = UserContractSignature(
        user_id=client.id,
        contract_file_id=contract_file.id,
        rental_id=(
            rental_uuid
            if contract_file.contract_type
            in [ContractType.RENTAL_MAIN_CONTRACT, ContractType.APPENDIX_7_1, ContractType.APPENDIX_7_2]
            else None
        ),
        guarantor_relationship_id=(
            guarantor_rel_uuid
            if sign_request.contract_type
            in [ContractType.GUARANTOR_CONTRACT, ContractType.GUARANTOR_MAIN_CONTRACT]
            else None
        ),
        digital_signature=client.digital_signature,
    )

    db.add(signature)

    log_action(
        db,
        actor_id=current_user.id,
        action="support_sign_contract_for_user",
        entity_type="user_contract_signature",
        entity_id=signature.id,
        details={
            "user_id": str(client.id),
            "contract_type": contract_file.contract_type.value,
            "contract_file_id": str(contract_file.id),
        },
    )

    db.commit()
    db.refresh(signature)

    if sign_request.contract_type in user_field_mapping:
        field_name = user_field_mapping[sign_request.contract_type]
        setattr(client, field_name, True)
        db.add(client)
        db.commit()

    db.expire_all()
    db.refresh(client)

    # Если подписан appendix_7_1, начать аренду
    if sign_request.contract_type == ContractType.APPENDIX_7_1 and rental_uuid:
        rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
        if rental and rental.rental_status == RentalStatus.RESERVED:
            rental.rental_status = RentalStatus.IN_USE
            if not rental.start_time:
                rental.start_time = get_local_time()

            db.add(rental)
            db.commit()
            db.refresh(rental)

            logger.info(
                f"✅ Аренда {uuid_to_sid(rental.id)} автоматически начата после подписания appendix_7_1 (support)"
            )

            car = db.query(Car).filter(Car.id == rental.car_id).first()
            if car:
                car.status = CarStatus.IN_USE
                car.current_renter_id = client.id
                db.add(car)
                db.commit()

    try:
        await notify_user_status_update(str(client.id))
    except Exception as e:
        logger.error(f"Error sending WebSocket notification: {e}")

    return UserSignatureResponse(
        id=uuid_to_sid(signature.id),
        user_id=uuid_to_sid(signature.user_id),
        contract_file_id=uuid_to_sid(signature.contract_file_id),
        contract_type=sign_request.contract_type,
        digital_signature=signature.digital_signature,
        signed_at=to_gmt_plus_5(signature.signed_at),
        rental_id=str(signature.rental_id) if signature.rental_id else None,
        guarantor_relationship_id=(
            str(signature.guarantor_relationship_id)
            if signature.guarantor_relationship_id
            else None
        ),
    )


class SupportSignMechanicContractRequest(BaseModel):
    mechanic_id: str = Field(..., description="SID механика")
    rental_id: str = Field(..., description="SID аренды")
    contract_type: ContractType = Field(..., description="Тип договора")


@support_contracts_router.post("/sign-mechanic", response_model=UserSignatureResponse)
async def support_sign_contract_mechanic(
    sign_request: SupportSignMechanicContractRequest,
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """
    Подписать договор от имени механика (support).
    Аналог POST /contracts/admin/sign-mechanic.
    """
    try:
        mechanic_uuid = safe_sid_to_uuid(sign_request.mechanic_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неверный формат mechanic_id: {str(e)}",
        )

    mechanic = db.query(User).filter(User.id == mechanic_uuid).first()
    if not mechanic:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Механик не найден",
        )

    if mechanic.role != UserRole.MECHANIC:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Указанный пользователь не является механиком",
        )

    try:
        rental_uuid = safe_sid_to_uuid(sign_request.rental_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неверный формат rental_id: {str(e)}",
        )

    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Аренда не найдена",
        )

    contract_file = (
        db.query(ContractFile)
        .filter(
            ContractFile.contract_type == sign_request.contract_type,
            ContractFile.is_active == True,
        )
        .first()
    )

    if not contract_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Активный файл договора типа {sign_request.contract_type} не найден",
        )

    if not mechanic.digital_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="У механика отсутствует цифровая подпись",
        )

    existing_signature = (
        db.query(UserContractSignature)
        .filter(
            UserContractSignature.user_id == mechanic.id,
            UserContractSignature.contract_file_id == contract_file.id,
            UserContractSignature.rental_id == rental_uuid,
        )
        .first()
    )

    if existing_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этот договор уже подписан механиком для данной аренды",
        )

    signature = UserContractSignature(
        id=uuid.uuid4(),
        user_id=mechanic.id,
        contract_file_id=contract_file.id,
        digital_signature=mechanic.digital_signature,
        signed_at=get_local_time(),
        rental_id=rental_uuid,
    )

    db.add(signature)
    db.commit()
    db.refresh(signature)

    try:
        await notify_user_status_update(str(mechanic.id))
    except Exception as e:
        logger.error("Error sending WebSocket notification: %s", e)

    return UserSignatureResponse(
        id=uuid_to_sid(signature.id),
        user_id=uuid_to_sid(signature.user_id),
        contract_file_id=uuid_to_sid(signature.contract_file_id),
        contract_type=sign_request.contract_type,
        digital_signature=signature.digital_signature,
        signed_at=to_gmt_plus_5(signature.signed_at),
        rental_id=str(signature.rental_id) if signature.rental_id else None,
        guarantor_relationship_id=None,
    )
