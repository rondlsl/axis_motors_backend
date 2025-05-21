from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
import pyotp
from datetime import datetime, timedelta
import httpx
from pydantic import BaseModel
from typing import Optional

from app.auth.dependencies.get_current_user import get_current_user  # обновлённая версия — см. ниже
from app.auth.dependencies.save_documents import save_file
from app.auth.schemas import SendSmsRequest, VerifySmsRequest
from app.auth.security.auth_bearer import JWTBearer
from app.auth.security.tokens import create_refresh_token, create_access_token
from app.core.config import SMS_TOKEN
from app.dependencies.database.database import get_db
from app.gps_api.utils.get_active_rental import get_open_price
from app.models.car_model import Car
from app.models.history_model import RentalHistory, RentalStatus
from app.models.user_model import UserRole, User

Auth_router = APIRouter(prefix="/auth", tags=["Auth"])

ALLOWED_TYPES = ["image/jpeg", "image/png"]

# Определяем константу срока действия документов по умолчанию: 15 июля 2025
DEFAULT_DOC_EXPIRY = datetime(2025, 7, 15)


async def send_sms_mobizon(recipient: str, sms_text: str, api_key: str):
    url = "https://api.mobizon.kz/service/message/sendsmsmessage"
    params = {
        "recipient": recipient,
        "text": sms_text,
        "apiKey": api_key
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
    # Ищем только активного пользователя с заданным номером
    user = db.query(User).filter(User.phone_number == phone_number, User.is_active == True).first()

    if not user:
        # Нет активного — создаём новый аккаунт
        user = User(
            phone_number=phone_number,
            role=UserRole.FIRST,  # Новым пользователям даём роль FIRST
            last_sms_code=sms_code,
            sms_code_valid_until=current_time + timedelta(hours=1),
            is_active=True  # Новый аккаунт активен
        )
        db.add(user)
    else:
        # Обновляем смс-код активного аккаунта
        user.last_sms_code = sms_code
        user.sms_code_valid_until = current_time + timedelta(hours=1)

    db.commit()
    print(sms_code)
    sms_text = f"{sms_code} - Ваш код подтверждения AZV Motors"
    # можно раскомментировать, когда подключите SMS
    # await send_sms_mobizon(phone_number, sms_text, f"{SMS_TOKEN}")
    return {"message": "SMS code sent successfully"}


@Auth_router.post("/verify_sms/")
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

    access_token = create_access_token(data={"sub": user.phone_number})
    refresh_token = create_refresh_token(data={"sub": user.phone_number})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


@Auth_router.get("/user/me")
async def read_users_me(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # Получаем активную аренду и автомобиль
    rental_with_car = (
        db.query(RentalHistory, Car)
        .join(Car, Car.id == RentalHistory.car_id)
        .filter(
            RentalHistory.user_id == current_user.id,
            RentalHistory.rental_status.in_([
                RentalStatus.RESERVED,
                RentalStatus.IN_USE,
                RentalStatus.DELIVERING
            ])
        )
        .first()
    )

    current_rental = None
    if rental_with_car:
        rental, car = rental_with_car

        rental_details = {
            "reservation_time": rental.reservation_time.isoformat() if rental.reservation_time else None,
            "start_time": rental.start_time.isoformat() if rental.start_time else None,
            "rental_type": rental.rental_type.value,
            "duration": rental.duration,
            "already_payed": float(rental.already_payed or 0),
            "status": rental.rental_status.value
        }

        if rental.rental_status == RentalStatus.DELIVERING:
            rental_details.update({
                "delivery_latitude": rental.delivery_latitude,
                "delivery_longitude": rental.delivery_longitude,
                "delivery_in_progress": rental.delivery_mechanic_id is not None
            })
        else:
            rental_details["delivery_in_progress"] = False

        if rental.delivery_mechanic_id:
            mech = db.query(User).get(rental.delivery_mechanic_id)
            current_mechanic = {
                "id": mech.id,
                "full_name": mech.full_name,
                "phone_number": mech.phone_number
            } if mech else None
        else:
            current_mechanic = None

        current_rental = {
            "rental_details": rental_details,
            "car_details": {
                "id": car.id,
                "name": car.name,
                "plate_number": car.plate_number,
                "fuel_level": car.fuel_level,
                "latitude": car.latitude,
                "longitude": car.longitude,
                "course": car.course,
                "engine_volume": car.engine_volume,
                "drive_type": car.drive_type,
                "year": car.year,
                "status": car.status,
                "price_per_minute": car.price_per_minute,
                "price_per_hour": car.price_per_hour,
                "price_per_day": car.price_per_day,
                "open_price": get_open_price(car),
                "owned_car": car.owner_id == current_user.id,
                "description": car.description,
            },
            "current_mechanic": current_mechanic
        }

    # Список машин, принадлежащих пользователю
    owned_cars_raw = db.query(Car).filter(Car.owner_id == current_user.id).all()
    owned_cars = []
    for car in owned_cars_raw:
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
            "year": car.year,
            "photos": car.photos,
            "description": car.description,
            "current_renter_id": car.current_renter_id,
            "status": car.status,
            "price_per_minute": car.price_per_minute,
            "price_per_hour": car.price_per_hour,
            "price_per_day": car.price_per_day,
            "open_price": get_open_price(car)
        })

    return {
        "phone_number": current_user.phone_number,
        "full_name": current_user.full_name,
        "role": current_user.role.value,
        "wallet_balance": float(current_user.wallet_balance or 0.0),
        "current_rental": current_rental,
        "owned_cars": owned_cars,
        "documents": {
            "selfie_with_license_url": current_user.selfie_with_license_url,
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

    new_access_token = create_access_token(data={"sub": user.phone_number})
    new_refresh_token = create_refresh_token(data={"sub": user.phone_number})

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer"
    }


@Auth_router.post("/upload-documents/")
async def upload_documents(
        id_front: UploadFile = File(...),
        id_back: UploadFile = File(...),
        drivers_license: UploadFile = File(...),
        selfie: UploadFile = File(...),
        current_user: User = Depends(get_current_user),  # Гарантированно активный
        db: Session = Depends(get_db)
):
    for doc in [id_front, id_back, drivers_license, selfie]:
        if doc.content_type not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"File {doc.filename} is not an image. Only JPEG and PNG are allowed."
            )

    try:
        id_front_path = await save_file(id_front, current_user.id, "uploads/documents")
        id_back_path = await save_file(id_back, current_user.id, "uploads/documents")
        license_path = await save_file(drivers_license, current_user.id, "uploads/documents")
        selfie_path = await save_file(selfie, current_user.id, "uploads/documents")

        current_user.id_card_front_url = id_front_path
        current_user.id_card_back_url = id_back_path
        # Устанавливаем срок действия ID-карты по умолчанию
        current_user.id_card_expiry = DEFAULT_DOC_EXPIRY

        current_user.drivers_license_url = license_path
        # Устанавливаем срок действия водительского удостоверения по умолчанию
        current_user.drivers_license_expiry = DEFAULT_DOC_EXPIRY

        current_user.selfie_with_license_url = selfie_path
        current_user.role = UserRole.PENDING

        db.commit()

        return {
            "message": "Documents uploaded successfully",
            "status": "pending review"
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="An error occurred while uploading documents"
        )


@Auth_router.post("/upload-id-card/")
async def upload_id_card(
        id_front: UploadFile = File(...),
        id_back: UploadFile = File(...),
        current_user: User = Depends(get_current_user),  # Гарантированно активный пользователь
        db: Session = Depends(get_db)
):
    for file in [id_front, id_back]:
        if file.content_type not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"File {file.filename} is not an image. Only JPEG and PNG are allowed."
            )
    try:
        id_front_path = await save_file(id_front, current_user.id, "uploads/documents")
        id_back_path = await save_file(id_back, current_user.id, "uploads/documents")

        current_user.id_card_front_url = id_front_path
        current_user.id_card_back_url = id_back_path
        # Устанавливаем срок действия ID-карты по умолчанию
        current_user.id_card_expiry = DEFAULT_DOC_EXPIRY
        current_user.role = UserRole.PENDING

        db.commit()

        return {
            "message": "ID card (front and back) uploaded successfully",
            "status": "pending review"
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="An error occurred while uploading the ID card documents"
        )


@Auth_router.post("/upload-drivers-license/")
async def upload_drivers_license(
        drivers_license: UploadFile = File(...),
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    if drivers_license.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File {drivers_license.filename} is not an image. Only JPEG and PNG are allowed."
        )
    try:
        license_path = await save_file(drivers_license, current_user.id, "uploads/documents")

        current_user.drivers_license_url = license_path
        # Устанавливаем срок действия водительского удостоверения по умолчанию
        current_user.drivers_license_expiry = DEFAULT_DOC_EXPIRY
        current_user.role = UserRole.PENDING

        db.commit()

        return {
            "message": "Driver's license uploaded successfully",
            "status": "pending review"
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="An error occurred while uploading the driver's license document"
        )


@Auth_router.post("/upload-selfie/")
async def upload_selfie(
        selfie: UploadFile = File(...),
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    if selfie.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File {selfie.filename} is not an image. Only JPEG and PNG are allowed."
        )
    try:
        selfie_path = await save_file(selfie, current_user.id, "uploads/documents")

        current_user.selfie_with_license_url = selfie_path
        current_user.role = UserRole.PENDING

        db.commit()

        return {
            "message": "Selfie uploaded successfully",
            "status": "pending review"
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="An error occurred while uploading the selfie"
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
    current_user.is_active = False
    db.commit()
    return {"message": "Аккаунт помечен как неактивный."}
