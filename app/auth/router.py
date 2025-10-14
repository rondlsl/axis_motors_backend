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
from app.utils.short_id import uuid_to_sid

from starlette import status

from app.auth.dependencies.get_current_user import get_current_user  # обновлённая версия — см. ниже
from app.auth.dependencies.save_documents import save_file
from app.auth.schemas import SendSmsRequest, VerifySmsRequest, DocumentUploadRequest, LocaleUpdate, SelfieUploadResponse, UserRegistrationInfoResponse, VerifySmsResponse
from app.auth.security.auth_bearer import JWTBearer
from app.auth.security.tokens import create_refresh_token, create_access_token
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
from app.utils.digital_signature import generate_digital_signature
from app.utils.sid_converter import convert_uuid_response_to_sid
import traceback

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
        VerificationCode.expires_at >= datetime.utcnow(),
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
        expires_at=datetime.utcnow() + timedelta(minutes=15),
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
    except Exception:
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


@Auth_router.post("/send_sms/")
async def send_sms(request: SendSmsRequest, db: Session = Depends(get_db)):
    """
    Отправка смс по номеру телефона:
    - Если активного аккаунта по номеру не существует, создаётся новый.
    - Если имеется активный аккаунт, для него обновляется sms-код.
    """
    totp = pyotp.TOTP(
        pyotp.random_base32(),
        digits=4,
        interval=1000
    )

    phone_number = request.phone_number
    current_time = datetime.utcnow()

    if not phone_number.isdigit():
        raise HTTPException(status_code=400, detail="Phone number must contain only digits.")

    sms_code = totp.now()
    # Сначала проверяем, есть ли заблокированный пользователь с таким номером (независимо от is_active)
    blocked = db.query(User).filter(
        User.phone_number == phone_number,
        User.role == UserRole.REJECTSECOND
    ).first()
    if blocked:
        raise HTTPException(status_code=403, detail=(
            "Вынуждены отказать в регистрации. По результатам проверки ваших данных были выявлены несоответствия требованиям доступа к сервису. "
            "Обращаем внимание, что на основании п. 4.4 Договора, Арендодатель вправе по своему усмотрению отказаться от заключения Договора с Клиентом. "
            "С уважением, Команда ≪AZV Motors≫."
        ))

    # Ищем активного пользователя с заданным номером
    user = db.query(User).filter(User.phone_number == phone_number, User.is_active == True).first()

    if not user:
        # Нет активного — создаём новый аккаунт
        if not request.first_name or not request.last_name:
            raise HTTPException(
                status_code=400, 
                detail="Для новых пользователей обязательно указать имя и фамилию"
            )
        
        user = User(
            phone_number=phone_number,
            first_name=request.first_name,
            last_name=request.last_name,
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
            last_name=request.last_name
        )
        user.digital_signature = digital_signature
    else:
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
            last_name=user.last_name or ""
        )
        db.commit()
    
    # Получаем ФИО пользователя
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
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

    return {"message": "SMS code sent successfully"}


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
    full_name = f"{current_user.first_name or ''} {current_user.last_name or ''}".strip()
    if not full_name:
        full_name = "Не указано"
    
    user_data = {
        "user_id": current_user.id,
        "phone_number": current_user.phone_number,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "digital_signature": current_user.digital_signature,
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
            User.sms_code_valid_until > datetime.utcnow(),
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
    user.last_activity_at = datetime.utcnow()
    db.commit()
    
    access_token = create_access_token(data={"sub": user.phone_number})
    refresh_token = create_refresh_token(data={"sub": user.phone_number})

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

    # Получаем ФИО пользователя
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    if not full_name:
        full_name = "Не указано"
    
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
        }
    )


@Auth_router.get("/user/me")
async def read_users_me(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # Получаем активную аренду и автомобиль
    # Для механиков ищем по mechanic_inspector_id, для обычных пользователей - по user_id
    if current_user.role == UserRole.MECHANIC:
        # Сначала ищем активный осмотр
        rental_with_car = (
            db.query(RentalHistory, Car)
            .join(Car, Car.id == RentalHistory.car_id)
            .filter(
                RentalHistory.mechanic_inspector_id == current_user.id,
                RentalHistory.mechanic_inspection_status.in_([
                    "PENDING",
                    "IN_USE",
                    "SERVICE"
                ])
            )
            .first()
        )
        
        # Если нет активного осмотра, ищем активную доставку
        if not rental_with_car:
            rental_with_car = (
                db.query(RentalHistory, Car)
                .join(Car, Car.id == RentalHistory.car_id)
                .filter(
                    RentalHistory.delivery_mechanic_id == current_user.id,
                    RentalHistory.rental_status.in_([
                        RentalStatus.DELIVERY_RESERVED,
                        RentalStatus.DELIVERING,
                        RentalStatus.DELIVERING_IN_PROGRESS
                    ])
                )
                .first()
            )
    else:
        rental_with_car = (
            db.query(RentalHistory, Car)
            .join(Car, Car.id == RentalHistory.car_id)
            .filter(
                RentalHistory.user_id == current_user.id,
                RentalHistory.rental_status.in_([
                    RentalStatus.RESERVED,
                    RentalStatus.IN_USE,
                    RentalStatus.DELIVERING,
                    RentalStatus.DELIVERY_RESERVED,
                    RentalStatus.DELIVERING_IN_PROGRESS
                ])
            )
            .first()
        )

    current_rental = None
    if rental_with_car:
        rental, car = rental_with_car

        # Для механиков используем mechanic_inspection_status, для обычных пользователей - rental_status
        if current_user.role == UserRole.MECHANIC:
            # Проверяем, это осмотр или доставка
            if rental.mechanic_inspector_id == current_user.id:
                # Это осмотр
                rental_details = {
                    "reservation_time": rental.mechanic_inspection_start_time.isoformat() if rental.mechanic_inspection_start_time else None,
                    "start_time": rental.mechanic_inspection_start_time.isoformat() if rental.mechanic_inspection_start_time else None,
                    "rental_type": rental.rental_type.value if rental.rental_type else "minutes",
                    "duration": rental.duration,
                    "already_payed": 0,  # Для механиков всегда 0
                    "status": rental.mechanic_inspection_status
                }
            else:
                # Это доставка
                rental_details = {
                    "reservation_time": rental.delivery_start_time.isoformat() if rental.delivery_start_time else None,
                    "start_time": rental.delivery_start_time.isoformat() if rental.delivery_start_time else None,
                    "rental_type": rental.rental_type.value if rental.rental_type else "minutes",
                    "duration": rental.duration,
                    "already_payed": 0,  # Для механиков всегда 0
                    "status": rental.rental_status.value
                }
        else:
            rental_details = {
                "reservation_time": rental.reservation_time.isoformat() if rental.reservation_time else None,
                "start_time": rental.start_time.isoformat() if rental.start_time else None,
                "rental_type": rental.rental_type.value,
                "duration": rental.duration,
                "already_payed": float(rental.already_payed or 0),
                "status": rental.rental_status.value
            }

        # Для механиков проверяем mechanic_inspection_status, для обычных пользователей - rental_status
        if current_user.role == UserRole.MECHANIC:
            # Для механиков логика доставки не применима
            current_mechanic = None
        elif rental.rental_status == RentalStatus.DELIVERING or rental.rental_status == RentalStatus.DELIVERING_IN_PROGRESS or rental.rental_status == RentalStatus.DELIVERY_RESERVED:
            # Рассчитываем время доставки если она началась
            delivery_duration_minutes = None
            if rental.delivery_start_time:
                delivery_duration_minutes = int((datetime.utcnow() - rental.delivery_start_time).total_seconds() / 60)
            
            rental_details.update({
                "delivery_latitude": rental.delivery_latitude,
                "delivery_longitude": rental.delivery_longitude,
                "delivery_in_progress": rental.delivery_mechanic_id is not None,
                "delivery_start_time": rental.delivery_start_time.isoformat() if rental.delivery_start_time else None,
                "delivery_duration_minutes": delivery_duration_minutes,
                "delivery_penalty_fee": rental.delivery_penalty_fee or 0
            })
        else:
            rental_details["delivery_in_progress"] = False

        if rental.delivery_mechanic_id:
            mech = db.get(User, rental.delivery_mechanic_id)
            current_mechanic = {
                "id": mech.id,
                "first_name": mech.first_name,
                "last_name": mech.last_name,
                "phone_number": mech.phone_number
            } if mech else None
        else:
            current_mechanic = None

        # Для механиков добавляем current_renter_details
        car_details = {
            "id": car.id,
            "name": car.name,
            "plate_number": car.plate_number,
            "fuel_level": car.fuel_level,
            "latitude": car.latitude,
            "longitude": car.longitude,
            "course": car.course,
            "engine_volume": car.engine_volume,
            "drive_type": car.drive_type,
            "transmission_type": car.transmission_type,
            "body_type": car.body_type,
            "auto_class": car.auto_class,
            "year": car.year,
            "photos": car.photos,
            "status": car.status,
            "price_per_minute": car.price_per_minute,
            "price_per_hour": car.price_per_hour,
            "price_per_day": car.price_per_day,
            "open_price": get_open_price(car),
            "owned_car": car.owner_id == current_user.id,
            "description": car.description,
            "current_renter_id": car.current_renter_id,
        }
        
        # Для механиков добавляем поля статуса загрузки фотографий
        if current_user.role == UserRole.MECHANIC:
            # Проверяем, это осмотр или доставка
            if rental.mechanic_inspector_id == current_user.id:
                # Это осмотр - используем mechanic_photos_before/after
                car_details["photo_before_selfie_uploaded"] = bool(rental.mechanic_photos_before and len(rental.mechanic_photos_before) > 0)
                car_details["photo_before_car_uploaded"] = bool(rental.mechanic_photos_before and len(rental.mechanic_photos_before) > 1)
                car_details["photo_before_interior_uploaded"] = bool(rental.mechanic_photos_before and len(rental.mechanic_photos_before) > 2)
                
                car_details["photo_after_selfie_uploaded"] = bool(rental.mechanic_photos_after and len(rental.mechanic_photos_after) > 0)
                car_details["photo_after_car_uploaded"] = bool(rental.mechanic_photos_after and len(rental.mechanic_photos_after) > 1)
                car_details["photo_after_interior_uploaded"] = bool(rental.mechanic_photos_after and len(rental.mechanic_photos_after) > 2)
            else:
                # Это доставка - используем delivery_photos_before/after
                # Проверяем флаги загрузки фото ПЕРЕД доставкой по содержимому путей
                photo_before_selfie_uploaded = False
                photo_before_car_uploaded = False
                photo_before_interior_uploaded = False
                
                if rental.delivery_photos_before:
                    photos_before = rental.delivery_photos_before
                    photo_before_selfie_uploaded = any(
                        ("/before/selfie/" in photo) or ("\\before\\selfie\\" in photo) 
                        for photo in photos_before
                    )
                    photo_before_car_uploaded = any(
                        ("/before/car/" in photo) or ("\\before\\car\\" in photo) 
                        for photo in photos_before
                    )
                    photo_before_interior_uploaded = any(
                        ("/before/interior/" in photo) or ("\\before\\interior\\" in photo) 
                        for photo in photos_before
                    )
                
                car_details["photo_before_selfie_uploaded"] = photo_before_selfie_uploaded
                car_details["photo_before_car_uploaded"] = photo_before_car_uploaded
                car_details["photo_before_interior_uploaded"] = photo_before_interior_uploaded
                
                # Проверяем флаги загрузки фото ПОСЛЕ доставки по содержимому путей
                photo_after_selfie_uploaded = False
                photo_after_car_uploaded = False
                photo_after_interior_uploaded = False
                
                if rental.delivery_photos_after:
                    photos_after = rental.delivery_photos_after
                    photo_after_selfie_uploaded = any(
                        ("/after/selfie/" in photo) or ("\\after\\selfie\\" in photo) 
                        for photo in photos_after
                    )
                    photo_after_car_uploaded = any(
                        ("/after/car/" in photo) or ("\\after\\car\\" in photo) 
                        for photo in photos_after
                    )
                    photo_after_interior_uploaded = any(
                        ("/after/interior/" in photo) or ("\\after\\interior\\" in photo) 
                        for photo in photos_after
                    )
                
                car_details["photo_after_selfie_uploaded"] = photo_after_selfie_uploaded
                car_details["photo_after_car_uploaded"] = photo_after_car_uploaded
                car_details["photo_after_interior_uploaded"] = photo_after_interior_uploaded
                
                # Добавляем delivery_coordinates для доставки
                car_details["delivery_coordinates"] = {
                    "latitude": rental.delivery_latitude,
                    "longitude": rental.delivery_longitude,
                }
            
            # Добавляем rental_id для механиков
            car_details["rental_id"] = rental.id
            
            # Добавляем last_client_review для механиков
            # Ищем последнюю завершенную аренду от обычного клиента (не механика)
            last_completed_rental = (
                db.query(RentalHistory)
                .join(User, RentalHistory.user_id == User.id)
                .filter(
                    RentalHistory.car_id == car.id,
                    RentalHistory.rental_status == RentalStatus.COMPLETED,
                    User.role != UserRole.MECHANIC  # Исключаем аренды от механиков
                )
                .order_by(RentalHistory.end_time.desc())
                .first()
            )
            
            if last_completed_rental:
                # Получаем отзыв клиента
                client_review = (
                    db.query(RentalReview)
                    .filter(RentalReview.rental_id == last_completed_rental.id)
                    .first()
                )
                
                if client_review:
                    # Получаем фото после аренды (салон и кузов)
                    after_photos = last_completed_rental.photos_after or []
                    interior_photos = [p for p in after_photos if ("/after/interior/" in p) or ("\\after\\interior\\" in p)]
                    exterior_photos = [p for p in after_photos if ("/after/car/" in p) or ("\\after\\car\\" in p)]
                    
                    car_details["last_client_review"] = {
                        "rating": client_review.rating,
                        "comment": client_review.comment,
                        "photos_after": {
                            "interior": interior_photos,
                            "exterior": exterior_photos
                        }
                    }
                else:
                    car_details["last_client_review"] = None
            else:
                car_details["last_client_review"] = None
        
        # Для механиков добавляем current_renter_details
        if current_user.role == UserRole.MECHANIC and car.current_renter_id:
            car_details["current_renter_details"] = {
                "id": car.current_renter_id,
                "phone_number": current_user.phone_number,
                "first_name": current_user.first_name,
                "last_name": current_user.last_name
            }
        
        current_rental = {
            "rental_details": rental_details,
            "car_details": car_details,
            "current_mechanic": current_mechanic
        }

    # Список машин, принадлежащих пользователю
    owned_cars_raw = db.query(Car).filter(Car.owner_id == current_user.id).all()
    owned_cars = []
    
    # Получаем текущий месяц и год
    now = datetime.now(ALMATY_TZ)
    current_month = now.month
    current_year = now.year
    
    for car in owned_cars_raw:
        # Рассчитываем доступные минуты для текущего месяца
        available_minutes = calculate_month_availability_minutes(
            car_id=car.id,
            year=current_year,
            month=current_month,
            owner_id=current_user.id,
            db=db
        )
        
        owned_cars.append({
            "id": car.id,
            "name": car.name,
            "plate_number": car.plate_number,
            "fuel_level": car.fuel_level,
            "latitude": car.latitude,
            "longitude": car.longitude,
            "course": car.course,
            "engine_volume": car.engine_volume,
            "drive_type": car.drive_type,
            "transmission_type": car.transmission_type,
            "body_type": car.body_type,
            "auto_class": car.auto_class,
            "year": car.year,
            "photos": car.photos,
            "description": car.description,
            "current_renter_id": car.current_renter_id,
            "status": car.status,
            "price_per_minute": car.price_per_minute,
            "price_per_hour": car.price_per_hour,
            "price_per_day": car.price_per_day,
            "open_price": get_open_price(car),
            "available_minutes": available_minutes
        })

    # Подсчитываем количество непрочитанных уведомлений
    unread_messages = (
        db.query(Notification)
        .filter(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False)
        )
        .count()
    )

    try:
        user_application = db.query(Application).filter(Application.user_id == current_user.id).first()
        guarantors_query = (
            db.query(Guarantor, User)
            .join(User, User.id == Guarantor.guarantor_id)
            .filter(
                Guarantor.client_id == current_user.id,
                Guarantor.is_active == True
            )
            .all()
        )
        
        guarantors = []
        for guarantor_relation, guarantor_user in guarantors_query:
            guarantors.append({
                "id": guarantor_user.id,
                "first_name": guarantor_user.first_name,
                "last_name": guarantor_user.last_name,
                "phone_number": guarantor_user.phone_number
            })
        
        guarantors_count = len(guarantors)

        first_name = current_user.first_name if isinstance(current_user.first_name, str) else None
        last_name = current_user.last_name if isinstance(current_user.last_name, str) else None
        role = getattr(current_user.role, "value", current_user.role) if current_user.role is not None else None

        return {
            "id": current_user.id,
            "user_id": uuid_to_sid(current_user.id),
            "phone_number": current_user.phone_number,
            "email": current_user.email,
            "first_name": first_name,
            "last_name": last_name,
            "iin": current_user.iin,
            "passport_number": current_user.passport_number,
            "birth_date": current_user.birth_date.isoformat() if current_user.birth_date else None,
            "role": role,
            "is_verified_email": getattr(current_user, "is_verified_email", False),
            "is_citizen_kz": getattr(current_user, "is_citizen_kz", False),
            "wallet_balance": float(current_user.wallet_balance or 0.0),
            "current_rental": current_rental,
            "owned_cars": owned_cars,
            "locale": current_user.locale,
            "unread_message": unread_messages,
            "guarantors_count": guarantors_count,
            "guarantors": guarantors,
            "auto_class": current_user.auto_class or [],
            "digital_signature": current_user.digital_signature,
            "application": {
                "reason": getattr(user_application, "reason", None) if user_application else None,
            },
            "documents": {
                "documents_verified": current_user.documents_verified,
                "selfie_with_license_url": current_user.selfie_with_license_url,
                "selfie_url": current_user.selfie_url,
                "psych_neurology_certificate_url": getattr(current_user, "psych_neurology_certificate_url", None),
                "narcology_certificate_url": getattr(current_user, "narcology_certificate_url", None),
                "pension_contributions_certificate_url": getattr(current_user, "pension_contributions_certificate_url", None),
                "drivers_license": {
                    "url": current_user.drivers_license_url,
                    "expiry": current_user.drivers_license_expiry.isoformat()
                    if current_user.drivers_license_expiry else None,
                },
                "id_card": {
                    "front_url": current_user.id_card_front_url,
                    "back_url": current_user.id_card_back_url,
                    "expiry": current_user.id_card_expiry.isoformat()
                    if current_user.id_card_expiry else None,
                }
            }
        }
    except Exception as e:
        from app.core.config import logger
        import traceback
        logger.error(f"Error in /auth/user/me: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal Server Error")


@Auth_router.post("/set_locale/", summary="Set locale body", description="Доступные locale - ru/en/kz")
async def set_locale(
        payload: LocaleUpdate,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    if payload.locale not in ["ru", "en", "kz"]:  # при необходимости список расширяем
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
            "user_id": current_user.id
        }
        
        converted_data = convert_uuid_response_to_sid(response_data, ["user_id"])
        return SelfieUploadResponse(**converted_data)
        
    except Exception as e:
        db.rollback()
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
    user.last_activity_at = datetime.utcnow()
    db.commit()

    new_access_token = create_access_token(data={"sub": user.phone_number})
    new_refresh_token = create_refresh_token(data={"sub": user.phone_number})

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
    
    # Правильно обрабатываем is_citizen_kz (может прийти как строка из формы)
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

    # Валидация данных через Pydantic-схему
    try:
        document_data = DocumentUploadRequest(
            first_name=first_name,
            last_name=last_name,
            birth_date=birth_date,
            iin=iin,
            passport_number=passport_number,
            id_card_expiry=id_card_expiry,
            drivers_license_expiry=drivers_license_expiry,
            is_citizen_kz=is_citizen_kz
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Validation error: {e}"
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

        # Сохраняем старый email для сравнения ДО обновления
        old_email = current_user.email
        
        # Обновление данных пользователя
        current_user.first_name = document_data.first_name
        current_user.last_name = document_data.last_name
        current_user.birth_date = datetime.strptime(document_data.birth_date, '%Y-%m-%d')
        current_user.email = email
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

        # Стартовый этап после загрузки документов — ожидание финансиста
        current_user.role = UserRole.PENDINGTOFIRST
        current_user.documents_verified = True
    
        # Создаем/обновляем заявку для проверки документов (idempotent)
        existing_application = db.query(Application).filter(Application.user_id == current_user.id).first()

        # Логика для email верификации:
        # Если пользователь повторно загружает документы (был отклонен), но email уже подтвержден - сбрасываем верификацию
        # Если email изменился - тоже сбрасываем верификацию
        # Если email новый и еще не подтвержден - оставляем как есть

        if existing_application and existing_application.financier_status == ApplicationStatus.REJECTED:
            # Пользователь повторно загружает документы после отказа
            if current_user.is_verified_email:
                # Email был подтвержден, но нужна повторная верификация
                current_user.is_verified_email = False
                email_needs_verification = True
        elif old_email != email:
            # Пользователь изменил email - нужна верификация нового email
            current_user.is_verified_email = False
            email_needs_verification = True
        elif not current_user.is_verified_email:
            # Email еще не был подтвержден
            email_needs_verification = True
        if existing_application:
            # Если пользователь был отклонен финансистом из-за документов, сбрасываем статус заявки
            if existing_application.financier_status == ApplicationStatus.REJECTED:
                existing_application.financier_status = ApplicationStatus.PENDING
                existing_application.financier_rejected_at = None
                existing_application.financier_user_id = None
                existing_application.reason = None
                existing_application.updated_at = datetime.utcnow()
            else:
                existing_application.updated_at = datetime.utcnow()
        else:
            application = Application(
                user_id=current_user.id,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(application)

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
        try:
            code = generate_email_verification_code()
            record = VerificationCode(
                phone_number=None,
                email=current_user.email,
                code=code,
                purpose="email_verification",
                is_used=False,
                expires_at=datetime.utcnow() + timedelta(minutes=15),
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
            except Exception:
                pass
            try:
                from app.core.config import logger
                logger.warning(f"Email verification code for {current_user.email}: {code}")
            except Exception:
                pass
        except Exception:
            # Не блокируем основной флоу из-за ошибок записи кода
            pass

        db.commit()

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
            }
        }

    except Exception as e:
        db.rollback()
        try:
            logger.error(f"Error in /auth/upload-documents: {e}")
            logger.error(traceback.format_exc())
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while uploading documents and data"
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