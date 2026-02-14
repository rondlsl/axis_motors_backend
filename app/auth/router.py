from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from app.core.logging_config import get_logger
logger = get_logger(__name__)
from sqlalchemy.orm import Session
import pyotp
from datetime import datetime, timedelta
import httpx
from pydantic import BaseModel, Field
from typing import Optional
from email.mime.text import MIMEText
import os
from app.core.smtp import send_email_with_fallback
import random
from app.utils.short_id import uuid_to_sid, safe_sid_to_uuid
from app.models.contract_model import UserContractSignature, ContractFile, ContractType
from app.models.history_model import RentalHistory, RentalStatus
from app.models.car_model import Car
from app.rent.utils.user_utils import get_user_available_auto_classes
from app.models.user_device_model import UserDevice

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
from app.guarantor.sms_utils import send_sms_mobizon
from app.models.car_model import Car
from app.models.history_model import RentalHistory, RentalStatus, RentalReview
from app.models.user_model import UserRole, User
from app.models.verification_code_model import VerificationCode
from app.models.application_model import Application, ApplicationStatus
from app.models.notification_model import Notification
from app.rent.utils.calculate_price import get_open_price
from app.owner.utils import calculate_month_availability_minutes, ALMATY_TZ
from app.models.guarantor_model import Guarantor
from app.admin.cars.utils import sort_car_photos
from app.utils.digital_signature import generate_digital_signature
from app.utils.sid_converter import convert_uuid_response_to_sid
from app.utils.telegram_logger import log_error_to_telegram
from app.utils.time_utils import get_local_time
from app.services.daily_user_stats_service import increment_daily_user_registered
# Временно закомментировано: генерация FCM токенов
# from app.utils.fcm_token import ensure_user_has_unique_fcm_token, ensure_unique_fcm_token
from app.websocket.notifications import notify_user_status_update
from app.auth.rate_limit import SMSRateLimit
import traceback
import asyncio

Auth_router = APIRouter(prefix="/auth", tags=["Auth"])

ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp", "image/jpg"]
CERT_ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp", "image/jpg", "application/pdf"]


def generate_email_verification_code() -> str:
    """Генерирует случайный 6-значный код для подтверждения email"""
    return str(random.randint(100000, 999999))


class VerifyEmailRequest(BaseModel):
    code: str
    email: Optional[str] = Field(None, description="Email для верификации (опционально). Если не указан, используется email из токена.")


@Auth_router.post("/verify_email/")
async def verify_email(request: VerifyEmailRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Проверка кода подтверждения email."""
    email_to_verify = None
    if request.email:
        email_to_verify = request.email.strip().lower()
    elif current_user.email:
        email_to_verify = current_user.email.strip().lower()
    
    if not email_to_verify:
        raise HTTPException(status_code=400, detail="Email не указан. Укажите email в запросе или убедитесь, что он сохранен в профиле.")
    
    # Ищем неиспользованный и неистекший код
    vc = db.query(VerificationCode).filter(
        VerificationCode.email == email_to_verify,
        VerificationCode.code == request.code,
        VerificationCode.purpose == "email_verification",
        VerificationCode.is_used == False,
        VerificationCode.expires_at >= get_local_time(),
    ).order_by(VerificationCode.id.desc()).first()

    if not vc:
        raise HTTPException(status_code=400, detail="Неверный код подтверждения. Попробуйте ещё раз.")

    # Отмечаем код использованным и подтверждаем email
    vc.is_used = True
    # Если email был передан в запросе и отличается от текущего, обновляем email пользователя
    if request.email and email_to_verify != (current_user.email or "").strip().lower():
        current_user.email = email_to_verify
    current_user.is_verified_email = True
    db.commit()
    db.refresh(current_user)
    
    # Отправляем WebSocket уведомление об обновлении статуса пользователя
    try:
        await notify_user_status_update(str(current_user.id))
        logger.info(f"WebSocket user_status notification sent for user {current_user.id} after email verification")
    except Exception as e:
        logger.error(f"Error sending WebSocket notification: {e}")

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

    # Пытаемся отправить письмо (с перебором SMTP-аккаунтов при лимитах)
    try:
        msg = MIMEText(f"Ваш код подтверждения: {code}")
        msg["Subject"] = "AZV Motors"
        msg["To"] = current_user.email
        if not send_email_with_fallback(msg, current_user.email):
            logger.warning(f"SMTP not configured or all accounts failed; verification code for {current_user.email}: {code}")
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
    logger.warning(f"Email verification code for {current_user.email}: {code}")

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


def _send_sms_registration_sync(
    phone_number: str,
    first_name: Optional[str],
    last_name: Optional[str],
    middle_name: Optional[str],
    email: Optional[str],
    sms_code: str,
) -> dict:
    """
    Синхронная работа с БД для шага регистрации/отправки SMS.
    Вызывается через asyncio.to_thread, чтобы не блокировать event loop.
    Возвращает {"ok": True, **data} или {"ok": False, "detail": str, "status_code": int}.
    """
    from app.dependencies.database.database import SessionLocal
    db = None
    try:
        db = SessionLocal()
        current_time = get_local_time()
        blocked_by_phone = db.query(User).filter(
            User.phone_number == phone_number,
            User.role == UserRole.REJECTSECOND
        ).first()
        if blocked_by_phone:
            return {
                "ok": False,
                "detail": (
                    "Вынуждены отказать в регистрации. По результатам проверки ваших данных были выявлены несоответствия требованиям доступа к сервису. "
                    "Обращаем внимание, что на основании п. 4.4 Договора, Арендодатель вправе по своему усмотрению отказаться от заключения Договора с Клиентом. "
                    "С уважением, Команда «AZV Motors»."
                ),
                "status_code": 403,
            }
        user = db.query(User).filter(User.phone_number == phone_number, User.is_active == True).first()
        if not user:
            inactive_user = db.query(User).filter(
                User.phone_number == phone_number,
                User.is_active == False
            ).first()
            if inactive_user:
                if inactive_user.role == UserRole.REJECTSECOND:
                    return {
                        "ok": False,
                        "detail": (
                            "Вынуждены отказать в регистрации. По результатам проверки ваших данных были выявлены несоответствия требованиям доступа к сервису. "
                            "Обращаем внимание, что на основании п. 4.4 Договора, Арендодатель вправе по своему усмотрению отказаться от заключения Договора с Клиентом. "
                            "С уважением, Команда «AZV Motors»."
                        ),
                        "status_code": 403,
                    }
                if inactive_user.is_blocked:
                    return {"ok": False, "detail": "Ваш аккаунт заблокирован. Обратитесь в техподдержку.", "status_code": 403}
                if inactive_user.is_deleted:
                    return {"ok": False, "detail": "Ваш аккаунт удалён. Обратитесь в техподдержку для восстановления.", "status_code": 403}
                if first_name or last_name or middle_name:
                    return {"ok": False, "detail": "Пользователь с таким номером телефона уже существует. Укажите только номер телефона.", "status_code": 400}
                inactive_user.is_active = True
                inactive_user.last_sms_code = sms_code
                inactive_user.sms_code_valid_until = current_time + timedelta(hours=1)
                user = inactive_user
            else:
                if not first_name or not last_name:
                    return {"ok": False, "detail": "Для новых пользователей обязательно указать имя и фамилию", "status_code": 400}
                user = User(
                    phone_number=phone_number,
                    first_name=first_name,
                    last_name=last_name,
                    middle_name=middle_name,
                    role=UserRole.CLIENT,
                    last_sms_code=sms_code,
                    sms_code_valid_until=current_time + timedelta(hours=1),
                    is_active=True,
                )
                db.add(user)
                db.flush()
                user.digital_signature = generate_digital_signature(
                    user_id=str(user.id),
                    phone_number=phone_number,
                    first_name=first_name,
                    last_name=last_name,
                    middle_name=middle_name or "",
                )
                increment_daily_user_registered(db, get_local_time().date())
        else:
            if first_name or last_name or middle_name:
                return {"ok": False, "detail": "Пользователь с таким номером телефона уже существует.", "status_code": 400}
            user.last_sms_code = sms_code
            user.sms_code_valid_until = current_time + timedelta(hours=1)
        db.commit()
        if not user.digital_signature:
            user.digital_signature = generate_digital_signature(
                user_id=str(user.id),
                phone_number=phone_number,
                first_name=user.first_name or "",
                last_name=user.last_name or "",
                middle_name=user.middle_name or "",
            )
            db.commit()
        full_name = f"{user.first_name or ''} {user.last_name or ''} {user.middle_name or ''}".strip() or "Не указано"
        email_code = None
        if email:
            email = email.strip().lower()
            existing = db.query(User).filter(User.email == email, User.id != user.id, User.is_active == True).first()
            if existing:
                return {"ok": False, "detail": "Этот email уже используется другим пользователем", "status_code": 400}
            TEST_EMAIL_CODES = {
                "test1@example.com": "111111", "test2@example.com": "222222", "test3@example.com": "333333",
                "test4@example.com": "444444", "test5@example.com": "555555", "test6@example.com": "666666",
                "test7@example.com": "777777", "test8@example.com": "888888", "test9@example.com": "999999",
                "test10@example.com": "000000",
            }
            email_code = TEST_EMAIL_CODES.get(email, generate_email_verification_code())
            email_verification_record = VerificationCode(
                phone_number=None,
                email=email,
                code=email_code,
                purpose="email_verification",
                is_used=False,
                expires_at=get_local_time() + timedelta(minutes=15),
            )
            db.add(email_verification_record)
            if not user.email or (user.email or "").lower() != email:
                user.email = email
                user.is_verified_email = False
            db.commit()
        return {
            "ok": True,
            "user_id": str(user.id),
            "digital_signature": user.digital_signature,
            "full_name": full_name,
            "fcm_token": user.fcm_token if user.fcm_token else None,
            "skip_sms": phone_number in (
                "70000000000", "71234567890", "71234567898", "71234567899", "79999999999", "71231111111"
            ),
            "email": email,
            "email_code": email_code,
        }
    except Exception as e:
        if db:
            try:
                db.rollback()
            except Exception:
                pass
        return {"ok": False, "detail": str(e), "status_code": 500}
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def _send_email_verification_sync(
    email: str,
    email_code: str,
    phone_number: str,
    user_id: Optional[str],
) -> None:
    """Синхронная отправка кода на email. Вызывается через asyncio.to_thread."""
    msg = MIMEText(f"Ваш код подтверждения: {email_code}")
    msg["Subject"] = "AZV Motors"
    msg["To"] = email
    send_email_with_fallback(msg, email)


def _verify_sms_sync(
    phone_number: str,
    sms_code: str,
    latitude: Optional[float],
    longitude: Optional[float],
) -> dict:
    """
    Синхронная верификация SMS и выдача токенов. Вызывается через asyncio.to_thread.
    Возвращает {"ok": True, **data} для VerifySmsResponse или {"ok": False, "detail": str, "status_code": int}.
    """
    from app.dependencies.database.database import SessionLocal
    db = None
    linked_count = 0
    try:
        db = SessionLocal()
        SYSTEM_PHONE_NUMBERS = (
            "70000000000", "71234567890", "71234567898", "71234567899", "79999999999", "71231111111"
        )
        if sms_code == "1010":
            user = db.query(User).filter(User.phone_number == phone_number, User.is_active == True).first()
        elif phone_number in SYSTEM_PHONE_NUMBERS:
            user = db.query(User).filter(
                User.phone_number == phone_number,
                User.last_sms_code == sms_code,
                User.is_active == True
            ).first()
        else:
            user = db.query(User).filter(
                User.phone_number == phone_number,
                User.last_sms_code == sms_code,
                User.sms_code_valid_until > get_local_time(),
                User.is_active == True
            ).first()
        if not user:
            return {"ok": False, "detail": "Invalid SMS code or code expired", "status_code": 401}
        if user.role == UserRole.REJECTSECOND:
            return {
                "ok": False,
                "detail": (
                    "Вынуждены отказать в регистрации. По результатам проверки ваших данных были выявлены несоответствия требованиям доступа к сервису. "
                    "Обращаем внимание, что на основании п. 4.4 Договора, Арендодатель вправе по своему усмотрению отказаться от заключения Договора с Клиентом. "
                    "С уважением, Команда «AZV Motors»."
                ),
                "status_code": 403,
            }
        if user.is_blocked:
            return {"ok": False, "detail": "Ваш аккаунт заблокирован. Обратитесь в техподдержку.", "status_code": 403}
        if user.is_deleted:
            return {"ok": False, "detail": "Ваш аккаунт удалён. Обратитесь в техподдержку для восстановления.", "status_code": 403}
        user.last_activity_at = get_local_time()
        db.commit()
        access_token = create_access_token(data={"sub": user.phone_number})
        refresh_token = create_refresh_token(data={"sub": user.phone_number})
        now = get_local_time()
        try:
            db.add(TokenRecord(user_id=user.id, token_type="access", token=access_token, expires_at=None, created_at=now, updated_at=now, last_used_at=now))
            db.add(TokenRecord(user_id=user.id, token_type="refresh", token=refresh_token, expires_at=None, created_at=now, updated_at=now))
            db.commit()
        except Exception:
            db.rollback()
        try:
            from app.models.guarantor_model import GuarantorRequest, GuarantorRequestStatus
            pending = db.query(GuarantorRequest).filter(
                GuarantorRequest.guarantor_phone == user.phone_number,
                GuarantorRequest.guarantor_id.is_(None),
                GuarantorRequest.status == GuarantorRequestStatus.PENDING
            ).all()
            for req in pending:
                req.guarantor_id = user.id
                if user.phone_number:
                    req.guarantor_phone = user.phone_number
                linked_count += 1
            if linked_count > 0:
                db.commit()
        except Exception as e:
            logger.error(" при связывании заявок гарантов: %s", e)
        if latitude is not None and longitude is not None:
            try:
                device = db.query(UserDevice).filter(
                    UserDevice.user_id == user.id,
                    UserDevice.is_active == True,
                    UserDevice.revoked_at.is_(None)
                ).order_by(UserDevice.last_active_at.desc()).first()
                if device is None:
                    device = UserDevice(user_id=user.id, is_active=True)
                    db.add(device)
                device.last_lat = latitude
                device.last_lng = longitude
                device.last_active_at = get_local_time()
                device.update_timestamp()
                db.commit()
            except Exception as e:
                logger.error("Ошибка при сохранении координат в user_devices: %s", e)
        full_name = f"{user.first_name or ''} {user.last_name or ''} {user.middle_name or ''}".strip() or "Не указано"
        return {
            "ok": True,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "linked_guarantor_requests": linked_count,
            "digital_signature": user.digital_signature,
            "client_info": {
                "full_name": full_name,
                "phone_number": user.phone_number,
                "user_id": uuid_to_sid(user.id),
                "digital_signature": user.digital_signature,
            },
            "fcm_token": user.fcm_token if user.fcm_token else None,
            "role": user.role.value,
        }
    except Exception as e:
        if db:
            try:
                db.rollback()
            except Exception:
                pass
        return {"ok": False, "detail": str(e), "status_code": 500}
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def _get_client_ip(http_request) -> str:
    """Извлечь реальный IP клиента (с учётом прокси)."""
    # X-Forwarded-For может содержать несколько IP через запятую
    forwarded = http_request.headers.get("X-Forwarded-For")
    if forwarded:
        # Берём первый IP (реальный клиент)
        return forwarded.split(",")[0].strip()
    # X-Real-IP (nginx)
    real_ip = http_request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    # Fallback на прямой IP
    if http_request.client:
        return http_request.client.host
    return ""


@Auth_router.post("/send_sms/", response_model=SendSmsResponse)
async def send_sms(
    request: SendSmsRequest,
    http_request: Request,
    db: Session = Depends(get_db)
):
    """
    Отправка смс по номеру телефона:
    - Если имеется активный аккаунт, для него обновляется sms-код (только phone_number).
    - Если активного аккаунта нет, но есть неактивный (удаленный), он автоматически восстанавливается (только phone_number).
    - Если вообще нет пользователя с таким номером, создаётся новый (обязательно указать first_name и last_name).

    Для существующих или восстановленных пользователей:
    {
        "phone_number": "77771234567",
        "email": "user@example.com"
    }

    Для новых пользователей:
    {
        "phone_number": "77771234567",
        "first_name": "Иван",
        "last_name": "Иванов",
        "middle_name": "Петрович",  // опционально
        "email": "user@example.com"
    }

    Если указан email, код подтверждения будет отправлен на email в дополнение к SMS.

    Rate limiting:
    - По номеру телефона: 60 сек cooldown, макс 5 SMS/час
    - По IP адресу: макс 10 SMS/мин, 50 SMS/час, 200 SMS/сутки
    """
    # Извлекаем IP для rate limiting
    client_ip = _get_client_ip(http_request)

    totp = pyotp.TOTP(
        pyotp.random_base32(),
        digits=4,
        interval=1000
    )

    phone_number = request.phone_number
    if not phone_number.isdigit():
        raise HTTPException(status_code=400, detail="Phone number must contain only digits.")

    # Системные номера телефонов — сразу возвращаем успех без отправки SMS
    SYSTEM_PHONE_NUMBERS = [
        "70000000000",   # админ
        "71234567890",   # механик
        "71234567898",   # МВД
        "71234567899",   # финансист
        "79999999999",   # бухгалтер
        "71231111111",   # владелец автомобилей
        # Тестовые номера
        "70123456789",   # тест1
        "70123456790",   # тест2
        "70123456791",   # тест3
        "70123456792",   # тест4
        "70123456793",   # тест5
        "70123456794",   # тест6
        "70123456795",   # тест7
        "70123456796",   # тест8
        "70123456797",   # тест9
        "70123456798",   # тест10
    ]

    if phone_number in SYSTEM_PHONE_NUMBERS:
        # Для системных пользователей сразу возвращаем успех без проверок
        try:
            system_user = db.query(User).filter(User.phone_number == phone_number, User.is_active == True).first()
            fcm = system_user.fcm_token if system_user and system_user.fcm_token else None
            return SendSmsResponse(message="SMS code sent successfully", fcm_token=fcm)
        except Exception as e:
            # Если что-то пошло не так, просто возвращаем успех
            return SendSmsResponse(message="SMS code sent successfully", fcm_token=None)

    can_send, error_msg = await SMSRateLimit.check(phone_number, client_ip)
    if not can_send:
        raise HTTPException(status_code=429, detail=error_msg)

    # Используем фиксированный код для тестовых номеров, иначе генерируем случайный
    TEST_PHONE_CODES = {
        "70123456789": "1111",  # тест1
        "70123456790": "2222",  # тест2
        "70123456791": "3333",  # тест3
        "70123456792": "4444",  # тест4
        "70123456793": "5555",  # тест5
        "70123456794": "6666",  # тест6
        "70123456795": "7777",  # тест7
        "70123456796": "8888",  # тест8
        "70123456797": "9999",  # тест9
        "70123456798": "0000",  # тест10
    }
    sms_code = TEST_PHONE_CODES.get(phone_number, totp.now())
    result = await asyncio.to_thread(
        _send_sms_registration_sync,
        phone_number,
        request.first_name,
        request.last_name,
        request.middle_name,
        request.email,
        sms_code,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=result.get("status_code", 500),
            detail=result.get("detail", "Internal error"),
        )
    sms_text = f"""{sms_code}-Ваш код
Электронная подпись:{result["digital_signature"]}"""
    if not result.get("skip_sms"):
        try:
            if SMS_TOKEN:
                logger.info("Mobizon: отправка SMS кода на phone=%s (auth)", phone_number)
                await send_sms_mobizon(phone_number, sms_text, f"{SMS_TOKEN}", sender="AZV Motors")
                await SMSRateLimit.update(phone_number, client_ip)
            else:
                logger.warning("SMS_TOKEN is not configured; skipping Mobizon send")
        except Exception as e:
            logger.error("Mobizon send error: phone=%s, error=%s", phone_number, e, exc_info=True)
            try:
                await log_error_to_telegram(
                    error=e,
                    request=None,
                    user=None,
                    additional_context={
                        "action": "send_sms_mobizon",
                        "phone_number": phone_number,
                        "user_id": result.get("user_id"),
                    }
                )
            except Exception:
                pass
    if result.get("email") and result.get("email_code"):
        email = result["email"]
        email_code = result["email_code"]
        try:
            await asyncio.to_thread(
                _send_email_verification_sync,
                email,
                email_code,
                phone_number,
                result.get("user_id"),
            )
        except Exception as e:
            try:
                await log_error_to_telegram(
                    error=e,
                    request=None,
                    user=None,
                    additional_context={
                        "action": "send_email_code_in_send_sms",
                        "email": email,
                        "user_id": result.get("user_id"),
                        "phone_number": phone_number,
                    }
                )
            except Exception:
                pass
        logger.warning("Email verification code for %s: %s", email, email_code)
    return SendSmsResponse(
        message="SMS code sent successfully",
        fcm_token=result.get("fcm_token"),
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
        
        asyncio.create_task(notify_user_status_update(str(current_user.id)))

        return UpdateNameResponse(
            message="Profile updated",
            first_name=current_user.first_name,
            last_name=current_user.last_name
        )
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update profile")


@Auth_router.post("/verify_sms/", response_model=VerifySmsResponse)
async def verify_sms(request: VerifySmsRequest):
    """
    Верификация смс-кода. Учтите, что ищем активного пользователя.
    Если sms_code == "1010", то тестовая проверка, иначе проверяем по коду и времени.
    Для системных пользователей время кода не проверяется.
    Работа с БД выполняется в потоке (asyncio.to_thread), чтобы не блокировать event loop.
    """
    if not request.phone_number.isdigit():
        raise HTTPException(status_code=400, detail="Phone number must contain only digits.")
    result = await asyncio.to_thread(
        _verify_sms_sync,
        request.phone_number,
        request.sms_code,
        request.latitude,
        request.longitude,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=result.get("status_code", 500),
            detail=result.get("detail", "Internal error"),
        )
    return VerifySmsResponse(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        token_type="bearer",
        linked_guarantor_requests=result["linked_guarantor_requests"],
        digital_signature=result["digital_signature"],
        client_info=result["client_info"],
        fcm_token=result.get("fcm_token"),
        role=result["role"],
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
    
    asyncio.create_task(notify_user_status_update(str(current_user.id)))
    
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
    if not selfie.content_type in ["image/jpeg", "image/png", "image/webp", "image/jpg"]:
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
        
        asyncio.create_task(notify_user_status_update(str(current_user.id)))
        
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
- pension_contributions_certificate: Справка о пенсионных отчислениях (изображение/PDF)

**Требуемые данные:**
- first_name: Имя (1-50 символов). Пример: "Иван"
- last_name: Фамилия (1-50 символов). Пример: "Иванов"
- birth_date: Дата рождения в формате YYYY-MM-DD. Пример: "1990-05-15"
- iin: ИИН из 12 цифр без пробелов. Пример: "900515123456" (или)
- passport_number: Номер паспорта (можно указать вместо ИИН)
- id_card_expiry: Дата истечения ID карты в формате YYYY-MM-DD (будущая дата). Пример: "2030-12-31"
- drivers_license_expiry: Дата истечения прав в формате YYYY-MM-DD (будущая дата). Пример: "2029-08-20"
- email: Электронная почта (необязательно)
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
        email: Optional[str] = Form(None),
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
        pension_path = None

        if psych_neurology_certificate is not None:
            psych_neuro_path = await save_file(psych_neurology_certificate, current_user.id, "uploads/documents")
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
        if normalized_email:
            current_user.email = normalized_email
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

        # Логика для email верификации (только если email был передан):
        # Если пользователь повторно загружает документы (был отклонен), но email уже подтвержден - сбрасываем верификацию
        # Если email изменился - тоже сбрасываем верификацию
        # Если email новый и еще не подтвержден - оставляем как есть
        # Если email НЕ передан - не трогаем существующий email и его верификацию

        if normalized_email:
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


        current_user.upload_document_at = get_local_time()

        db.commit()
        
        # Отправляем push-уведомление о загрузке документов (перед WebSocket, чтобы не блокировать)
        try:
            from app.push.utils import send_localized_notification_to_user_async
            asyncio.create_task(
                send_localized_notification_to_user_async(
                    current_user.id,
                    "documents_uploaded",
                    "documents_uploaded"
                )
            )
        except Exception as e:
            # Не блокируем основной флоу из-за ошибок отправки уведомления
            logger.error(f"Error sending documents_uploaded notification: {e}")
        
        # Обновляем все данные из БД для получения свежих данных (после всех операций)
        db.expire_all()
        db.refresh(current_user)
        
        # Отправляем WebSocket уведомление об обновлении статуса пользователя в самом конце
        try:
            await notify_user_status_update(str(current_user.id))
            logger.info(f"WebSocket user_status notification sent for user {current_user.id} after document upload")
        except Exception as e:
            logger.error(f"Error sending WebSocket notification: {e}")

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
    
    # Отправляем письмо с кодом (с перебором SMTP-аккаунтов при лимитах)
    try:
        msg = MIMEText(f"Ваш код для подтверждения изменения email: {code}")
        msg["Subject"] = "AZV Motors - Изменение email"
        msg["To"] = new_email
        if not send_email_with_fallback(msg, new_email):
            logger.warning(f"SMTP not configured or all accounts failed; verification code for {new_email}: {code}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")

    logger.warning(f"Email change verification code for {new_email}: {code}")

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
    
    asyncio.create_task(notify_user_status_update(str(current_user.id)))
    
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
      - Инвалидируем все токены в Redis-кэше.
      - Все связи сохраняются, история не удаляется.
      - После этого все эндпоинты, зависящие от get_current_user, будут недоступны для данного аккаунта.
    """
    from app.auth.dependencies.token_cache import TokenCache

    # Проверяем отрицательный баланс
    if getattr(current_user, "wallet_balance", 0) < 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Нельзя удалить аккаунт: на кошельке отрицательный баланс."
        )

    current_user.is_active = False
    db.commit()

    # Инвалидируем все токены пользователя в Redis
    await TokenCache.invalidate_all_user_tokens(current_user.id)

    asyncio.create_task(notify_user_status_update(str(current_user.id)))

    return {"message": "Аккаунт помечен как неактивный."}

