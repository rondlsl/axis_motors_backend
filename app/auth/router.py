from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
import pyotp
from datetime import datetime, timedelta
import httpx
from pydantic import BaseModel
from typing import Optional
import smtplib
from email.mime.text import MIMEText
import os
import random
from app.utils.short_id import uuid_to_sid, safe_sid_to_uuid
from app.models.contract_model import UserContractSignature, ContractFile, ContractType
from app.models.history_model import RentalHistory, RentalStatus
from app.models.car_model import Car
from app.rent.utils.user_utils import get_user_available_auto_classes

from starlette import status
import traceback

from app.auth.dependencies.get_current_user import get_current_user  
from app.auth.dependencies.save_documents import save_file
from app.auth.schemas import SendSmsRequest, VerifySmsRequest, DocumentUploadRequest, LocaleUpdate, SelfieUploadResponse, UserRegistrationInfoResponse, VerifySmsResponse, ChangeEmailRequest, VerifyEmailChangeRequest, ChangeEmailResponse, SendSmsResponse
from app.auth.security.auth_bearer import JWTBearer
from app.auth.security.tokens import create_refresh_token, create_access_token
from app.models.token_model import TokenRecord
from datetime import datetime, timedelta
from app.core.config import ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS
from app.core.config import SMS_TOKEN
from app.dependencies.database.database import get_db
from app.models.car_model import Car
from app.models.history_model import RentalHistory, RentalStatus, RentalReview
from app.models.user_model import UserRole, User
from app.models.verification_code_model import VerificationCode
from app.models.application_model import Application, ApplicationStatus
from app.models.notification_model import Notification
from app.rent.utils.calculate_price import get_open_price
from app.owner.utils import calculate_month_availability_minutes, ALMATY_TZ
from app.core.config import logger
from app.models.guarantor_model import Guarantor
from app.admin.cars.utils import sort_car_photos
from app.utils.digital_signature import generate_digital_signature
from app.utils.sid_converter import convert_uuid_response_to_sid
from app.utils.telegram_logger import log_error_to_telegram
from app.utils.time_utils import get_local_time
# Временно закомментировано: генерация FCM токенов
# from app.utils.fcm_token import ensure_user_has_unique_fcm_token, ensure_unique_fcm_token
from app.websocket.notifications import notify_user_status_update
import traceback
import asyncio

Auth_router = APIRouter(prefix="/auth", tags=["Auth"])

ALLOWED_TYPES = ["image/jpeg", "image/png"]
CERT_ALLOWED_TYPES = ["image/jpeg", "image/png", "application/pdf"]


def generate_email_verification_code() -> str:
    """Генерирует случайный 6-значный код для подтверждения email"""
    return str(random.randint(100000, 999999))


class VerifyEmailRequest(BaseModel):
    code: str


@Auth_router.post("/verify_email/")
async def verify_email(request: VerifyEmailRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Проверка кода подтверждения email."""
    if not current_user.email:
        raise HTTPException(status_code=400, detail="У пользователя не указан email")
    # Ищем неиспользованный и неистекший код
    vc = db.query(VerificationCode).filter(
        VerificationCode.email == current_user.email,
        VerificationCode.code == request.code,
        VerificationCode.purpose == "email_verification",
        VerificationCode.is_used == False,
        VerificationCode.expires_at >= get_local_time(),
    ).order_by(VerificationCode.id.desc()).first()

    if not vc:
        raise HTTPException(status_code=400, detail="Неверный код подтверждения. Попробуйте ещё раз.")

    # Отмечаем код использованным и подтверждаем email
    vc.is_used = True
    current_user.is_verified_email = True
    db.commit()

    return {"message": "Email успешно подтверждён."}


@Auth_router.post("/resend_email_code/")
async def resend_email_code(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Повторная отправка кода подтверждения на email."""
    if not current_user.email:
        raise HTTPException(status_code=400, detail="У пользователя не указан email")
    code = generate_email_verification_code()
    record = VerificationCode(
        phone_number=None,
        email=current_user.email,
        code=code,
        purpose="email_verification",
        is_used=False,
        expires_at=get_local_time() + timedelta(minutes=15),
    )
    db.add(record)

    # Пытаемся отправить письмо
    try:
        smtp_host = os.getenv("SMTP_HOST")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER")
        smtp_pass = os.getenv("SMTP_PASSWORD")
        smtp_from = os.getenv("SMTP_FROM", smtp_user or "no-reply@example.com")
        if smtp_host and smtp_user and smtp_pass:
            msg = MIMEText(f"Ваш код подтверждения: {code}")
            msg["Subject"] = "AZV Motors"
            msg["From"] = smtp_from
            msg["To"] = current_user.email
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            try:
                from app.core.config import logger
                logger.warning(f"SMTP not configured; verification code for {current_user.email}: {code}")
            except Exception:
                pass
    except Exception as e:
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "resend_email_code_smtp",
                    "email": current_user.email,
                    "user_id": str(current_user.id)
                }
            )
        except:
            pass
    try:
        from app.core.config import logger
        logger.warning(f"Email verification code for {current_user.email}: {code}")
    except Exception:
        pass

    db.commit()
    return {"message": "Код подтверждения повторно отправлен."}

# Определяем константу срока действия документов по умолчанию: 15 июля 2025
DEFAULT_DOC_EXPIRY = datetime(2025, 7, 15)


class UpdateNameRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    class Config:
        schema_extra = {
            "example": {
                "first_name": "Иван",
                "last_name": "Иванов"
            }
        }


class UpdateNameResponse(BaseModel):
    message: str
    first_name: Optional[str]
    last_name: Optional[str]

    class Config:
        schema_extra = {
            "example": {
                "message": "Profile updated",
                "first_name": "Иван",
                "last_name": "Иванов"
            }
        }


async def send_sms_mobizon(recipient: str, sms_text: str, api_key: str):
    url = "https://api.mobizon.kz/service/message/sendsmsmessage"
    params = {
        "recipient": recipient,
        "text": sms_text,
        "apiKey": api_key,
        "from": "AZV Motors"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        return response.text


@Auth_router.post("/send_sms/", response_model=SendSmsResponse)
async def send_sms(request: SendSmsRequest, db: Session = Depends(get_db)):
    """
    Отправка смс по номеру телефона:
    - Если имеется активный аккаунт, для него обновляется sms-код (только phone_number).
    - Если активного аккаунта нет, но есть неактивный (удаленный), он автоматически восстанавливается (только phone_number).
    - Если вообще нет пользователя с таким номером, создаётся новый (обязательно указать first_name и last_name).
    
    Для существующих или восстановленных пользователей:
    {
        "phone_number": "77771234567"
    }
    
    Для новых пользователей:
    {
        "phone_number": "77771234567",
        "first_name": "Иван",
        "last_name": "Иванов",
        "middle_name": "Петрович"  // опционально
    }
    """
    totp = pyotp.TOTP(
        pyotp.random_base32(),
        digits=4,
        interval=1000
    )

    phone_number = request.phone_number
    current_time = get_local_time()

    if not phone_number.isdigit():
        raise HTTPException(status_code=400, detail="Phone number must contain only digits.")

    sms_code = totp.now()
    # Проверяем блокировку по номеру телефона (REJECTSECOND - независимо от is_active)
    blocked_by_phone = db.query(User).filter(
        User.phone_number == phone_number,
        User.role == UserRole.REJECTSECOND
    ).first()
    if blocked_by_phone:
        raise HTTPException(status_code=403, detail=(
            "Вынуждены отказать в регистрации. По результатам проверки ваших данных были выявлены несоответствия требованиям доступа к сервису. "
            "Обращаем внимание, что на основании п. 4.4 Договора, Арендодатель вправе по своему усмотрению отказаться от заключения Договора с Клиентом. "
            "С уважением, Команда ≪AZV Motors≫."
        ))

    # Ищем активного пользователя с заданным номером
    user = db.query(User).filter(User.phone_number == phone_number, User.is_active == True).first()

    if not user:
        # Нет активного — проверяем, есть ли неактивный (удаленный) пользователь
        inactive_user = db.query(User).filter(
            User.phone_number == phone_number, 
            User.is_active == False
        ).first()
        
        if inactive_user:
            # Проверяем, не заблокирован ли пользователь (REJECTSECOND)
            if inactive_user.role == UserRole.REJECTSECOND:
                raise HTTPException(status_code=403, detail=(
                    "Вынуждены отказать в регистрации. По результатам проверки ваших данных были выявлены несоответствия требованиям доступа к сервису. "
                    "Обращаем внимание, что на основании п. 4.4 Договора, Арендодатель вправе по своему усмотрению отказаться от заключения Договора с Клиентом. "
                    "С уважением, Команда ≪AZV Motors≫."
                ))
            
            # Восстанавливаем удаленный аккаунт
            # Проверяем, что не переданы лишние поля (имя/фамилия уже есть в профиле)
            if request.first_name or request.last_name or request.middle_name:
                raise HTTPException(
                    status_code=400,
                    detail="Пользователь с таким номером телефона уже существует. Укажите только номер телефона."
                )
            inactive_user.is_active = True
            inactive_user.last_sms_code = sms_code
            inactive_user.sms_code_valid_until = current_time + timedelta(hours=1)
            
            # Временно закомментировано: генерация FCM токенов
            # # Проверяем и генерируем FCM токен, если необходимо
            # try:
            #     ensure_user_has_unique_fcm_token(db, inactive_user)
            # except Exception as e:
            #     print(f"Ошибка при генерации FCM токена при восстановлении: {e}")
            #     # Продолжаем без токена, он будет сгенерирован при логине
            
            user = inactive_user
        else:
            # Вообще нет пользователя — создаём новый аккаунт
            if not request.first_name or not request.last_name:
                raise HTTPException(
                    status_code=400, 
                    detail="Для новых пользователей обязательно указать имя и фамилию"
                )
            
            user = User(
                phone_number=phone_number,
                first_name=request.first_name,
                last_name=request.last_name,
                middle_name=request.middle_name,
                role=UserRole.CLIENT,  # Новым пользователям даём роль CLIENT
                last_sms_code=sms_code,
                sms_code_valid_until=current_time + timedelta(hours=1),
                is_active=True  # Новый аккаунт активен
            )
            db.add(user)
            db.flush()  # Получаем ID пользователя
            
            # Генерируем цифровую подпись для нового пользователя
            digital_signature = generate_digital_signature(
                user_id=str(user.id),
                phone_number=phone_number,
                first_name=request.first_name,
                last_name=request.last_name,
                middle_name=request.middle_name
            )
            user.digital_signature = digital_signature
            
            # Временно закомментировано: генерация FCM токенов
            # # Генерируем уникальный FCM токен для нового пользователя
            # try:
            #     user.fcm_token = ensure_unique_fcm_token(db, user_id=user.id)
            # except Exception as e:
            #     print(f"Ошибка при генерации FCM токена при регистрации: {e}")
            #     # Продолжаем без токена, он будет сгенерирован при логине
    else:
        # Существующий активный пользователь - проверяем, что не переданы лишние поля
        if request.first_name or request.last_name or request.middle_name:
            raise HTTPException(
                status_code=400,
                detail="Пользователь с таким номером телефона уже существует."
            )
        
        # Обновляем смс-код активного аккаунта
        user.last_sms_code = sms_code
        user.sms_code_valid_until = current_time + timedelta(hours=1)

    db.commit()
    print(sms_code)
    
    # Формируем SMS с информацией о клиенте
    if not user.digital_signature:
        # Если у пользователя еще нет цифровой подписи, генерируем её
        user.digital_signature = generate_digital_signature(
            user_id=str(user.id),
            phone_number=phone_number,
            first_name=user.first_name or "",
            last_name=user.last_name or "",
            middle_name=user.middle_name or ""
        )
        db.commit()
    
    # Получаем ФИО пользователя
    full_name = f"{user.first_name or ''} {user.last_name or ''} {user.middle_name or ''}".strip()
    if not full_name:
        full_name = "Не указано"
    
    sms_text = f"""{sms_code} - Ваш код подтверждения AZV Motors

Данные клиента:
ФИО клиента: {full_name}
Логин клиента: {phone_number}
ID клиента: {user.id}
Электронная подпись: {user.digital_signature}"""
    try:
        if SMS_TOKEN:
            await send_sms_mobizon(phone_number, sms_text, f"{SMS_TOKEN}")
        else:
            logger.warning("SMS_TOKEN is not configured; skipping Mobizon send")
    except Exception as e:
        logger.error(f"Mobizon send error: {e}")
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=None,
                additional_context={
                    "action": "send_sms_mobizon",
                    "phone_number": phone_number,
                    "user_id": str(user.id) if user else None
                }
            )
        except:
            pass

    # Возвращаем fcm_token из базы данных
    fcm_token = user.fcm_token if user.fcm_token else None
    return SendSmsResponse(
        message="SMS code sent successfully",
        fcm_token=fcm_token
    )


@Auth_router.get("/user/registration-info", response_model=UserRegistrationInfoResponse)
async def get_user_registration_info(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получение информации о пользователе для отображения при регистрации
    Включает цифровую подпись и другие данные для подписания документов
    """
    # Получаем ФИО пользователя
    full_name = f"{current_user.first_name or ''} {current_user.last_name or ''} {current_user.middle_name or ''}".strip()
    if not full_name:
        full_name = "Не указано"
    
    user_data = {
        "user_id": uuid_to_sid(current_user.id),
        "phone_number": current_user.phone_number,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "middle_name": current_user.middle_name,
        "digital_signature": current_user.digital_signature,
        "upload_document_at": current_user.upload_document_at.isoformat() if current_user.upload_document_at else None,
        "message": f"ФИО клиента: {full_name}\nЛогин клиента: {current_user.phone_number}\nID клиента: {current_user.id}\nЭлектронная подпись: {current_user.digital_signature}"
    }
    
    converted_data = convert_uuid_response_to_sid(user_data, ["user_id"])
    return UserRegistrationInfoResponse(**converted_data)


@Auth_router.patch(
    "/user/name",
    summary="Обновить имя и фамилию пользователя",
    description="Позволяет изменить `first_name` и/или `last_name` текущего пользователя",
    response_model=UpdateNameResponse
)
async def update_user_name(
        payload: UpdateNameRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    # Проверяем, что документы не верифицированы
    if current_user.documents_verified:
        raise HTTPException(
            status_code=403, 
            detail="Cannot update name after documents verification"
        )
    
    # Нормализуем входные данные
    new_first = payload.first_name.strip() if isinstance(payload.first_name, str) else None
    new_last = payload.last_name.strip() if isinstance(payload.last_name, str) else None

    if not new_first and not new_last:
        raise HTTPException(status_code=400, detail="Nothing to update")

    # Валидация длин
    if new_first is not None and (len(new_first) < 1 or len(new_first) > 50):
        raise HTTPException(status_code=422, detail="first_name must be 1..50 chars")
    if new_last is not None and (len(new_last) < 1 or len(new_last) > 50):
        raise HTTPException(status_code=422, detail="last_name must be 1..50 chars")

    try:
        if new_first is not None:
            current_user.first_name = new_first
        if new_last is not None:
            current_user.last_name = new_last

        db.add(current_user)
        db.commit()
        db.refresh(current_user)

        return UpdateNameResponse(
            message="Profile updated",
            first_name=current_user.first_name,
            last_name=current_user.last_name
        )
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update profile")


@Auth_router.post("/verify_sms/", response_model=VerifySmsResponse)
async def verify_sms(request: VerifySmsRequest, db: Session = Depends(get_db)):
    """
    Верификация смс-кода. Учтите, что ищем активного пользователя.
    Если sms_code == "6666", то тестовая проверка, иначе проверяем по коду и времени.
    """
    phone_number = request.phone_number
    sms_code = request.sms_code

    if not phone_number.isdigit():
        raise HTTPException(status_code=400, detail="Phone number must contain only digits.")

    # При проверке пользуемся активными пользователями
    if sms_code == "6666":
        user = db.query(User).filter(User.phone_number == phone_number, User.is_active == True).first()
    else:
        user = db.query(User).filter(
            User.phone_number == phone_number,
            User.last_sms_code == sms_code,
            User.sms_code_valid_until > get_local_time(),
            User.is_active == True
        ).first()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid SMS code or code expired")

    # Блокируем вход для пользователей, отклонённых МВД
    if user.role == UserRole.REJECTSECOND:
        raise HTTPException(status_code=403, detail=(
            "Вынуждены отказать в регистрации. По результатам проверки ваших данных были выявлены несоответствия требованиям доступа к сервису. "
            "Обращаем внимание, что на основании п. 4.4 Договора, Арендодатель вправе по своему усмотрению отказаться от заключения Договора с Клиентом. "
            "С уважением, Команда ≪AZV Motors≫."
        ))

    # Обновляем время последней активности
    user.last_activity_at = get_local_time()
    db.commit()
    
    access_token = create_access_token(data={"sub": user.phone_number})
    refresh_token = create_refresh_token(data={"sub": user.phone_number})

    # Create new tokens (always create new records to support multiple devices)
    try:
        now = get_local_time()
        
        # Create new access token
        access_token_record = TokenRecord(
            user_id=user.id, 
            token_type="access", 
            token=access_token, 
            expires_at=None, 
            created_at=now, 
            updated_at=now, 
            last_used_at=now
        )
        db.add(access_token_record)
        
        # Create new refresh token
        refresh_token_record = TokenRecord(
            user_id=user.id, 
            token_type="refresh", 
            token=refresh_token, 
            expires_at=None, 
            created_at=now, 
            updated_at=now
        )
        db.add(refresh_token_record)
        
        db.commit()
    except Exception:
        db.rollback()

    try:
        from app.models.guarantor_model import GuarantorRequest, GuarantorRequestStatus
        
        # Ищем заявки с этим номером телефона где guarantor_id = NULL
        pending_requests = db.query(GuarantorRequest).filter(
            GuarantorRequest.guarantor_phone == user.phone_number,
            GuarantorRequest.guarantor_id.is_(None),
            GuarantorRequest.status == GuarantorRequestStatus.PENDING
        ).all()
        
        linked_count = 0
        for request in pending_requests:
            # Связываем заявку с пользователем
            request.guarantor_id = user.id
            
            # Обновляем телефон в заявке из профиля пользователя
            if user.phone_number:
                request.guarantor_phone = user.phone_number
            
            linked_count += 1
        
        # Сохраняем изменения
        if linked_count > 0:
            db.commit()
            
    except Exception as e:
        print(f"Ошибка при связывании заявок гарантов: {e}")
        # Продолжаем выполнение без обработки гарантов
        linked_count = 0

    # Временно закомментировано: генерация FCM токенов
    # # Проверяем и генерируем FCM токен, если необходимо
    # try:
    #     token_updated = ensure_user_has_unique_fcm_token(db, user)
    #     if token_updated:
    #         db.commit()
    #         db.refresh(user)
    # except Exception as e:
    #     print(f"Ошибка при генерации FCM токена: {e}")
    #     # Продолжаем выполнение даже если не удалось сгенерировать токен
    #     db.rollback()

    # Получаем ФИО пользователя
    full_name = f"{user.first_name or ''} {user.last_name or ''} {user.middle_name or ''}".strip()
    if not full_name:
        full_name = "Не указано"
    
    # Возвращаем fcm_token из базы данных
    fcm_token = user.fcm_token if user.fcm_token else None
    return VerifySmsResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        linked_guarantor_requests=linked_count,
        digital_signature=user.digital_signature,
        client_info={
            "full_name": full_name,
            "phone_number": user.phone_number,
            "user_id": uuid_to_sid(user.id),
            "digital_signature": user.digital_signature
        },
        fcm_token=fcm_token
    )


@Auth_router.get("/user/me")
async def read_users_me(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    try:
        from app.utils.user_data import get_user_me_data
        return await get_user_me_data(db, current_user)
    except HTTPException as e:
        # Обрабатываем ошибки токенов (просрочен, неверный и т.д.)
        if e.status_code in [401, 403]:
            raise e
        else:
            raise HTTPException(status_code=401, detail="Authentication failed")
    except Exception as e:
        logger.error(f"Error in /auth/user/me: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal Server Error")


@Auth_router.post("/set_locale/", summary="Set locale body", description="Доступные locale - ru/en/kz/zh")
async def set_locale(
        payload: LocaleUpdate,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    if payload.locale not in ["ru", "en", "kz", "zh"]:  
        raise HTTPException(status_code=400, detail="Unsupported locale")

    current_user.locale = payload.locale
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return {"message": "Locale updated", "locale": current_user.locale}


@Auth_router.post(
    "/upload-selfie/",
    summary="Загрузка селфи пользователя",
    description="Позволяет пользователю загрузить новое селфи для обновления профиля",
    response_model=SelfieUploadResponse
)
async def upload_selfie(
        selfie: UploadFile = File(..., description="Селфи пользователя (JPEG/PNG)"),
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """
    Загрузка селфи пользователя.
    
    **Требования:**
    - Файл должен быть изображением (JPEG/PNG)
    - Размер файла не должен превышать разумные пределы
    - Пользователь должен быть авторизован
    
    **Возвращает:**
    - URL загруженного селфи
    - Сообщение об успешной загрузке
    """
    # Валидация файла
    if not selfie.content_type in ["image/jpeg", "image/png"]:
        raise HTTPException(
            status_code=400,
            detail="Файл должен быть изображением в формате JPEG или PNG"
        )
    
    # Проверяем размер файла (максимум 10MB)
    content = await selfie.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB
        raise HTTPException(
            status_code=400,
            detail="Размер файла не должен превышать 10MB"
        )
    
    # Возвращаем указатель файла в начало
    await selfie.seek(0)
    
    try:
        # Сохраняем файл
        from app.auth.dependencies.save_documents import save_file
        selfie_path = await save_file(selfie, current_user.id, "uploads/profile")
        
        # Обновляем URL селфи в профиле пользователя
        current_user.selfie_url = selfie_path
        db.add(current_user)
        db.commit()
        db.refresh(current_user)
        
        response_data = {
            "message": "Селфи успешно загружено",
            "selfie_url": selfie_path,
            "user_id": uuid_to_sid(current_user.id)
        }
        
        converted_data = convert_uuid_response_to_sid(response_data, ["user_id"])
        return SelfieUploadResponse(**converted_data)
        
    except Exception as e:
        db.rollback()
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "upload_selfie",
                    "user_id": str(current_user.id),
                    "content_type": selfie.content_type
                }
            )
        except:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при загрузке селфи: {str(e)}"
        )


@Auth_router.post("/refresh_token/")
async def refresh_token(db: Session = Depends(get_db), token: str = Depends(JWTBearer(expected_token_type="refresh"))):
    credentials_exception = HTTPException(status_code=401, detail="Could not validate credentials")
    phone_number: str = token.get("sub")
    if phone_number is None:
        raise credentials_exception
    # Снова ищем только активного пользователя
    user = db.query(User).filter(User.phone_number == phone_number, User.is_active == True).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found or inactive")

    # Обновляем время последней активности
    user.last_activity_at = get_local_time()
    db.commit()

    new_access_token = create_access_token(data={"sub": user.phone_number})
    new_refresh_token = create_refresh_token(data={"sub": user.phone_number})

    # Create new tokens (always create new records to support multiple devices)
    try:
        now = get_local_time()
        
        # Create new access token
        access_token_record = TokenRecord(
            user_id=user.id, 
            token_type="access", 
            token=new_access_token, 
            expires_at=None, 
            created_at=now, 
            updated_at=now, 
            last_used_at=now
        )
        db.add(access_token_record)
        
        # Create new refresh token
        refresh_token_record = TokenRecord(
            user_id=user.id, 
            token_type="refresh", 
            token=new_refresh_token, 
            expires_at=None, 
            created_at=now, 
            updated_at=now
        )
        db.add(refresh_token_record)
        
        db.commit()
    except Exception:
        db.rollback()

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer"
    }


@Auth_router.post("/upload-documents/",
                  summary="Загрузка документов и личных данных",
                  description="""
Загрузка документов пользователя и заполнение личных данных.

**Требуемые файлы:**
- id_front: Фото лицевой стороны ID карты (JPEG/PNG)
- id_back: Фото обратной стороны ID карты (JPEG/PNG)  
- drivers_license: Фото водительских прав (JPEG/PNG)
- selfie_with_license: Селфи с водительскими правами (JPEG/PNG)
- selfie: Обычное селфи (JPEG/PNG)

**Необязательные файлы (для граждан Казахстана обязательны):**
- psych_neurology_certificate: Справка из психоневрологического диспансера (изображение/PDF)
- narcology_certificate: Справка из наркологического диспансера (изображение/PDF)
- pension_contributions_certificate: Справка о пенсионных отчислениях (изображение/PDF)

**Требуемые данные:**
- first_name: Имя (1-50 символов). Пример: "Иван"
- last_name: Фамилия (1-50 символов). Пример: "Иванов"
- birth_date: Дата рождения в формате YYYY-MM-DD. Пример: "1990-05-15"
- iin: ИИН из 12 цифр без пробелов. Пример: "900515123456" (или)
- passport_number: Номер паспорта (можно указать вместо ИИН)
- id_card_expiry: Дата истечения ID карты в формате YYYY-MM-DD (будущая дата). Пример: "2030-12-31"
- drivers_license_expiry: Дата истечения прав в формате YYYY-MM-DD (будущая дата). Пример: "2029-08-20"
- email: Электронная почта
- is_citizen_kz: Гражданин Республики Казахстан (true/false). Если true, то справки обязательны

После успешной загрузки статус пользователя изменится на PENDING (ожидает проверки).
                  """)
async def upload_documents(
        # Обязательные файлы
        id_front: UploadFile = File(...),
        id_back: UploadFile = File(...),
        drivers_license: UploadFile = File(...),
        selfie_with_license: UploadFile = File(...),
        selfie: UploadFile = File(...),

        # Необязательные файлы справок
        psych_neurology_certificate: Optional[UploadFile] = File(None),
        narcology_certificate: Optional[UploadFile] = File(None),
        pension_contributions_certificate: Optional[UploadFile] = File(None),

        # Данные формы
        first_name: str = Form(..., min_length=1, max_length=50),
        last_name: str = Form(..., min_length=1, max_length=50),
        middle_name: Optional[str] = Form(None, min_length=0, max_length=50),
        birth_date: str = Form(...),
        iin: Optional[str] = Form(None),
        passport_number: Optional[str] = Form(None),
        id_card_expiry: str = Form(...),
        drivers_license_expiry: str = Form(...),
        email: str = Form(...),
        is_citizen_kz: bool = Form(False),

        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    # Инициализируем переменную для email верификации
    email_needs_verification = False

    # Проверяем, что пользователь существует
    if not current_user or not current_user.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or invalid"
        )
    
    # Правильно обрабатываем boolean поля (могут прийти как строки из формы)
    if isinstance(is_citizen_kz, str):
        is_citizen_kz = is_citizen_kz.lower() in ('true', '1', 'yes', 'on')
    
    # Обрабатываем пустые файлы
    if isinstance(psych_neurology_certificate, str) and not psych_neurology_certificate:
        psych_neurology_certificate = None
    if isinstance(narcology_certificate, str) and not narcology_certificate:
        narcology_certificate = None
    if isinstance(pension_contributions_certificate, str) and not pension_contributions_certificate:
        pension_contributions_certificate = None
    
    # Валидация типов обязательных файлов
    image_docs = [
        id_front,
        id_back,
        drivers_license,
        selfie_with_license,
        selfie,
    ]

    # Необязательные файлы справок (фильтруем None)
    cert_docs = [
        psych_neurology_certificate,
        narcology_certificate,
        pension_contributions_certificate,
    ]

    # Валидация обязательных файлов
    for doc in image_docs:
        if doc.content_type not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File {doc.filename} is not an image. Only JPEG and PNG are allowed."
            )

    # Валидация необязательных файлов справок (только если они предоставлены)
    for doc in cert_docs:
        if doc is not None and doc.content_type not in CERT_ALLOWED_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Certificate {doc.filename} must be JPEG, PNG or PDF."
            )

    # Нормализуем ИИН, паспорт и middle_name (пустые строки -> None)
    normalized_iin = iin.strip() if iin and isinstance(iin, str) and iin.strip() else None
    normalized_passport = passport_number.strip() if passport_number and isinstance(passport_number, str) and passport_number.strip() else None
    normalized_middle_name = middle_name.strip() if middle_name and isinstance(middle_name, str) and middle_name.strip() else None
    
    # Валидация данных через Pydantic-схему
    try:
        document_data = DocumentUploadRequest(
            first_name=first_name,
            last_name=last_name,
            birth_date=birth_date,
            iin=normalized_iin,
            passport_number=normalized_passport,
            id_card_expiry=id_card_expiry,
            drivers_license_expiry=drivers_license_expiry,
            is_citizen_kz=is_citizen_kz
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Validation error: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid data: {str(e)}"
        )

    # Валидация для граждан Казахстана: если is_citizen_kz = true, то все 4 сертификата обязательны
    if is_citizen_kz:
        missing_certificates = []
        if psych_neurology_certificate is None:
            missing_certificates.append("психоневрологическая справка")
        if narcology_certificate is None:
            missing_certificates.append("наркологическая справка")
        if pension_contributions_certificate is None:
            missing_certificates.append("справка о пенсионных взносах")
        
        if missing_certificates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Как гражданин Республики Казахстан, вы обязаны предоставить все сертификаты. Отсутствуют: {', '.join(missing_certificates)}"
            )

    normalized_email = (email or "").strip().lower()
    if normalized_email:
        existing_with_email = (
            db.query(User)
            .filter(
                User.email == normalized_email,
                User.id != current_user.id,
                User.is_active == True
            )
            .first()
        )
        if existing_with_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Этот email уже используется другим пользователем. Пожалуйста, используйте другой email."
            )

    try:
        # Сохранение обязательных файлов
        id_front_path = await save_file(id_front, current_user.id, "uploads/documents")
        id_back_path = await save_file(id_back, current_user.id, "uploads/documents")
        license_path = await save_file(drivers_license, current_user.id, "uploads/documents")
        selfie_with_license_path = await save_file(selfie_with_license, current_user.id, "uploads/documents")
        selfie_path = await save_file(selfie, current_user.id, "uploads/documents")

        # Сохранение необязательных файлов справок (только если они предоставлены)
        psych_neuro_path = None
        narcology_path = None
        pension_path = None

        if psych_neurology_certificate is not None:
            psych_neuro_path = await save_file(psych_neurology_certificate, current_user.id, "uploads/documents")
        if narcology_certificate is not None:
            narcology_path = await save_file(narcology_certificate, current_user.id, "uploads/documents")
        if pension_contributions_certificate is not None:
            pension_path = await save_file(pension_contributions_certificate, current_user.id, "uploads/documents")

        # Сохраняем старый email для сравнения ДО обновления (нормализуем для корректного сравнения)
        old_email = (current_user.email or "").strip().lower() if current_user.email else None
        
        # Проверка блокировки по ИИН (REJECTSECOND - независимо от is_active и текущего пользователя)
        if document_data.iin:
            blocked_by_iin = db.query(User).filter(
                User.iin == document_data.iin,
                User.role == UserRole.REJECTSECOND
            ).first()
            if blocked_by_iin:
                raise HTTPException(status_code=403, detail=(
                    "Вынуждены отказать в регистрации. По результатам проверки ваших данных были выявлены несоответствия требованиям доступа к сервису. "
                    "Обращаем внимание, что на основании п. 4.4 Договора, Арендодатель вправе по своему усмотрению отказаться от заключения Договора с Клиентом. "
                    "С уважением, Команда ≪AZV Motors≫."
                ))
            
            # Проверка уникальности ИИН среди активных пользователей (кроме текущего)
            exists_iin = db.query(User).filter(
                User.iin == document_data.iin,
                User.id != current_user.id,
                User.is_active == True
            ).first()
            if exists_iin:
                raise HTTPException(status_code=400, detail="Пользователь с таким ИИН уже существует")

        # Проверка блокировки по номеру паспорта (REJECTSECOND - независимо от is_active и текущего пользователя)
        if document_data.passport_number:
            blocked_by_passport = db.query(User).filter(
                User.passport_number == document_data.passport_number,
                User.role == UserRole.REJECTSECOND
            ).first()
            if blocked_by_passport:
                raise HTTPException(status_code=403, detail=(
                    "Вынуждены отказать в регистрации. По результатам проверки ваших данных были выявлены несоответствия требованиям доступа к сервису. "
                    "Обращаем внимание, что на основании п. 4.4 Договора, Арендодатель вправе по своему усмотрению отказаться от заключения Договора с Клиентом. "
                    "С уважением, Команда ≪AZV Motors≫."
                ))
            
            # Проверка уникальности паспорта среди активных пользователей (кроме текущего)
            exists_passport = db.query(User).filter(
                User.passport_number == document_data.passport_number,
                User.id != current_user.id,
                User.is_active == True
            ).first()
            if exists_passport:
                raise HTTPException(status_code=400, detail="Пользователь с таким номером паспорта уже существует")

        # Обновление данных пользователя
        current_user.first_name = document_data.first_name
        current_user.last_name = document_data.last_name
        current_user.middle_name = normalized_middle_name
        current_user.birth_date = datetime.strptime(document_data.birth_date, '%Y-%m-%d')
        current_user.email = normalized_email or None
        current_user.is_citizen_kz = document_data.is_citizen_kz
        # Сохраняем ИИН или паспорт
        current_user.iin = document_data.iin
        current_user.passport_number = document_data.passport_number

        current_user.id_card_front_url = id_front_path
        current_user.id_card_back_url = id_back_path
        current_user.id_card_expiry = datetime.strptime(document_data.id_card_expiry, '%Y-%m-%d')

        current_user.drivers_license_url = license_path
        current_user.drivers_license_expiry = datetime.strptime(document_data.drivers_license_expiry, '%Y-%m-%d')

        current_user.selfie_with_license_url = selfie_with_license_path
        current_user.selfie_url = selfie_path

        # Привязываем пути к справкам (только если файлы были загружены)
        current_user.psych_neurology_certificate_url = psych_neuro_path
        current_user.narcology_certificate_url = narcology_path
        current_user.pension_contributions_certificate_url = pension_path

        # Создаем/обновляем заявку для проверки документов (idempotent)
        existing_application = db.query(Application).filter(Application.user_id == current_user.id).first()

        # Проверяем статус заявки для определения, нужно ли менять роль
        should_reset_role = True
        should_reset_application = False
        if existing_application:
            # Если заявка уже полностью одобрена (финансистом И МВД), не меняем роль
            if existing_application.financier_status == ApplicationStatus.APPROVED and existing_application.mvd_status == ApplicationStatus.APPROVED:
                should_reset_role = False
            # Если пользователь был отклонен, проверяем причину
            elif existing_application.financier_status == ApplicationStatus.REJECTED:
                # Сбрасываем статус заявки только если отказ был из-за документов
                if current_user.role == UserRole.REJECTFIRSTDOC or current_user.role == UserRole.REJECTFIRSTCERT:
                    should_reset_application = True
            else:
                existing_application.updated_at = get_local_time()
        else:
            application = Application(
                user_id=current_user.id,
                created_at=get_local_time(),
                updated_at=get_local_time()
            )
            db.add(application)
        
        # Сбрасываем статус заявки только если была причина в документах
        if should_reset_application:
            existing_application.financier_status = ApplicationStatus.PENDING
            existing_application.financier_rejected_at = None
            existing_application.financier_user_id = None
            existing_application.reason = None
            existing_application.updated_at = get_local_time()

        # Обновляем роль только если заявка не была полностью одобрена
        if should_reset_role:
            current_user.role = UserRole.PENDINGTOFIRST
        current_user.documents_verified = True

        # Логика для email верификации:
        # Если пользователь повторно загружает документы (был отклонен), но email уже подтвержден - сбрасываем верификацию
        # Если email изменился - тоже сбрасываем верификацию
        # Если email новый и еще не подтвержден - оставляем как есть

        # Приводим normalized_email к None, если это пустая строка для корректного сравнения
        normalized_email_for_comparison = normalized_email if normalized_email else None
        
        if existing_application and existing_application.financier_status == ApplicationStatus.REJECTED:
            # Пользователь повторно загружает документы после отказа
            if current_user.is_verified_email:
                # Email был подтвержден, но нужна повторная верификация
                current_user.is_verified_email = False
                email_needs_verification = True
        elif old_email != normalized_email_for_comparison:
            # Пользователь изменил email - нужна верификация нового email
            current_user.is_verified_email = False
            email_needs_verification = True
        elif not current_user.is_verified_email and normalized_email_for_comparison:
            # Email еще не был подтвержден (только если email указан)
            email_needs_verification = True

        # Обновляем имя в заявках гаранта, где этот пользователь является гарантом
        try:
            from app.models.guarantor_model import GuarantorRequest
            guarantor_requests = db.query(GuarantorRequest).filter(
                GuarantorRequest.guarantor_id == current_user.id
            ).all()

            for request in guarantor_requests:
                request.guarantor_phone = current_user.phone_number
        except Exception as e:
            # Продолжаем выполнение без обработки гарантов
            pass

        # Записываем код подтверждения email и отправляем его на почту
        # ЗАКОММЕНТИРОВАНО: отправка кода будет выполняться отдельным запросом
        # try:
        #     code = generate_email_verification_code()
        #     record = VerificationCode(
        #         phone_number=None,
        #         email=current_user.email,
        #         code=code,
        #         purpose="email_verification",
        #         is_used=False,
        #         expires_at=get_local_time() + timedelta(minutes=15),
        #     )
        #     db.add(record)
        #     # Пытаемся отправить письмо
        #     try:
        #         smtp_host = os.getenv("SMTP_HOST")
        #         smtp_port = int(os.getenv("SMTP_PORT", "587"))
        #         smtp_user = os.getenv("SMTP_USER")
        #         smtp_pass = os.getenv("SMTP_PASSWORD")
        #         smtp_from = os.getenv("SMTP_FROM", smtp_user or "no-reply@example.com")
        #         if smtp_host and smtp_user and smtp_pass:
        #             msg = MIMEText(f"Ваш код подтверждения: {code}")
        #             msg["Subject"] = "AZV Motors"
        #             msg["From"] = smtp_from
        #             msg["To"] = current_user.email
        #             with smtplib.SMTP(smtp_host, smtp_port) as server:
        #                 server.starttls()
        #                 server.login(smtp_user, smtp_pass)
        #                 server.send_message(msg)
        #         else:
        #             try:
        #                 from app.core.config import logger
        #                 logger.warning(f"SMTP not configured; verification code for {current_user.email}: {code}")
        #             except Exception:
        #                 pass
        #     except Exception:
        #         pass
        #     try:
        #         from app.core.config import logger
        #         logger.warning(f"Email verification code for {current_user.email}: {code}")
        #     except Exception:
        #         pass
        # except Exception:
        #     # Не блокируем основной флоу из-за ошибок записи кода
        #     pass

        current_user.upload_document_at = get_local_time()

        db.commit()
        
        asyncio.create_task(notify_user_status_update(str(current_user.id)))

        return {
            "message": "Documents and data uploaded successfully",
            "status": "pending review",
            "data": {
                "first_name": current_user.first_name,
                "last_name": current_user.last_name,
                "birth_date": current_user.birth_date.strftime('%Y-%m-%d'),
                "email": current_user.email,
                "is_verified_email": not email_needs_verification,
                "is_citizen_kz": current_user.is_citizen_kz,
                "iin": current_user.iin,
                "passport_number": current_user.passport_number,
                "id_card_expiry": current_user.id_card_expiry.strftime('%Y-%m-%d'),
                "drivers_license_expiry": current_user.drivers_license_expiry.strftime('%Y-%m-%d'),
                "selfie_with_license_url": current_user.selfie_with_license_url,
                "selfie_url": current_user.selfie_url,
                "psych_neurology_certificate_url": current_user.psych_neurology_certificate_url,
                "narcology_certificate_url": current_user.narcology_certificate_url,
                "pension_contributions_certificate_url": current_user.pension_contributions_certificate_url,
                "is_consent_to_data_processing": current_user.is_consent_to_data_processing,
                "is_contract_read": current_user.is_contract_read,
                "is_user_agreement": current_user.is_user_agreement,
                "upload_document_at": current_user.upload_document_at.isoformat() if current_user.upload_document_at else None,
            }
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        error_message = str(e)
        try:
            logger.error(f"Error in /auth/upload-documents: {e}")
            logger.error(traceback.format_exc())
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "upload_documents",
                    "user_id": str(current_user.id),
                    "email": email
                }
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while uploading documents and data: {error_message}"
        )


@Auth_router.post("/change_email/request", response_model=ChangeEmailResponse)
async def request_change_email(
    request: ChangeEmailRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Запрос на изменение email адреса.
    Отправляет код подтверждения на новый email адрес.
    """
    new_email = request.new_email.strip().lower()
    
    # Проверяем, что новый email отличается от текущего
    if current_user.email and current_user.email.lower() == new_email:
        raise HTTPException(
            status_code=400,
            detail="Новый email совпадает с текущим"
        )
    
    # Проверяем, что email не используется другим пользователем
    existing_user = db.query(User).filter(
        User.email == new_email,
        User.id != current_user.id,
        User.is_active == True
    ).first()
    
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Этот email уже используется другим пользователем"
        )
    
    # Генерируем код подтверждения
    code = generate_email_verification_code()
    
    # Сохраняем код в базу данных с указанием purpose = "email_change"
    record = VerificationCode(
        phone_number=None,
        email=new_email,
        code=code,
        purpose="email_change",
        is_used=False,
        expires_at=get_local_time() + timedelta(minutes=15),
    )
    db.add(record)
    
    # Отправляем письмо с кодом
    try:
        smtp_host = os.getenv("SMTP_HOST")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER")
        smtp_pass = os.getenv("SMTP_PASSWORD")
        smtp_from = os.getenv("SMTP_FROM", smtp_user or "no-reply@example.com")
        
        if smtp_host and smtp_user and smtp_pass:
            msg = MIMEText(f"Ваш код для подтверждения изменения email: {code}")
            msg["Subject"] = "AZV Motors - Изменение email"
            msg["From"] = smtp_from
            msg["To"] = new_email
            
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            try:
                from app.core.config import logger
                logger.warning(f"SMTP not configured; verification code for {new_email}: {code}")
            except Exception:
                pass
    except Exception as e:
        try:
            from app.core.config import logger
            logger.error(f"Failed to send email: {e}")
        except Exception:
            pass
    
    try:
        from app.core.config import logger
        logger.warning(f"Email change verification code for {new_email}: {code}")
    except Exception:
        pass
    
    db.commit()
    
    return ChangeEmailResponse(
        message="Код подтверждения отправлен на новый email адрес",
        email=new_email
    )


@Auth_router.post("/change_email/verify", response_model=ChangeEmailResponse)
async def verify_change_email(
    request: VerifyEmailChangeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Подтверждение изменения email адреса с помощью кода.
    После успешной верификации email будет изменен.
    """
    new_email = request.new_email.strip().lower()
    
    # Ищем неиспользованный и неистекший код
    vc = db.query(VerificationCode).filter(
        VerificationCode.email == new_email,
        VerificationCode.code == request.code,
        VerificationCode.purpose == "email_change",
        VerificationCode.is_used == False,
        VerificationCode.expires_at >= get_local_time(),
    ).order_by(VerificationCode.id.desc()).first()
    
    if not vc:
        raise HTTPException(
            status_code=400,
            detail="Неверный код подтверждения или код истек"
        )
    
    # Проверяем еще раз, что email не занят (могло измениться за время верификации)
    existing_user = db.query(User).filter(
        User.email == new_email,
        User.id != current_user.id,
        User.is_active == True
    ).first()
    
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Этот email уже используется другим пользователем"
        )
    
    # Отмечаем код использованным
    vc.is_used = True
    
    # Обновляем email пользователя
    current_user.email = new_email
    current_user.is_verified_email = True
    
    db.commit()
    
    return ChangeEmailResponse(
        message="Email успешно изменен",
        email=new_email
    )


@Auth_router.delete("/delete_account/")
async def delete_account(
        current_user: User = Depends(get_current_user),  # Гарантированно активный до удаления
        db: Session = Depends(get_db)
):
    """
    Мягкое удаление аккаунта:
      - Устанавливаем current_user.is_active = False.
      - Все связи сохраняются, история не удаляется.
      - После этого все эндпоинты, зависящие от get_current_user, будут недоступны для данного аккаунта.
    """
    # Проверяем отрицательный баланс
    if getattr(current_user, "wallet_balance", 0) < 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Нельзя удалить аккаунт: на кошельке отрицательный баланс."
        )

    current_user.is_active = False
    db.commit()
    return {"message": "Аккаунт помечен как неактивный."}

