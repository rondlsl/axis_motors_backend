from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
import pyotp
from datetime import datetime, timedelta
import httpx
from pydantic import BaseModel
from typing import Optional

from app.auth.dependencies.get_current_user import get_current_user
from app.auth.dependencies.save_documents import save_file
from app.auth.schemas import SendSmsRequest, VerifySmsRequest, UserMeResponse
from app.auth.security.auth_bearer import JWTBearer
from app.auth.security.tokens import create_refresh_token, create_access_token
from app.core.config import SMS_TOKEN
from app.dependencies.database.database import get_db
from app.models.user_model import UserRole, User

Auth_router = APIRouter(prefix="/auth", tags=["Auth"])


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
    """Отправка смс по номеру телефона. Создает в базе данных юзера с указанным номером, и отправляет ему смс код.
    В случае если пользователь уже зарегистрирован - можно использовать код 6666.

    Номер отправлять без "+", только 11 символов.
    Например для номера +7 (747) 205-15-07 отправляйте 77472051507
    ВАЖНО!! ЭНДПОИНТ ПРИНИМАЕТ ОДИН ЗАПРОС С ОДНОГО АЙПИ РАЗ В 1 МИНУТУ.
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
    user = db.query(User).filter(User.phone_number == phone_number).first()

    if not user:
        user = User(
            phone_number=phone_number,
            role=UserRole.FIRST,  # Новым пользователям даем роль FIRST
            last_sms_code=sms_code,
            sms_code_valid_until=current_time + timedelta(hours=1)
        )
        db.add(user)
    else:
        user.last_sms_code = sms_code
        user.sms_code_valid_until = current_time + timedelta(hours=1)

    db.commit()
    print(sms_code)
    sms_text = f"{sms_code} - Ваш код подтверждения AZV Motors"
    # response = await send_sms_mobizon(phone_number, sms_text, f"{SMS_TOKEN}")
    return {"message": "SMS code sent successfully"}


@Auth_router.post("/verify_sms/")
async def verify_sms(request: VerifySmsRequest, db: Session = Depends(get_db)):
    phone_number = request.phone_number
    sms_code = request.sms_code

    if not phone_number.isdigit():
        raise HTTPException(status_code=400, detail="Phone number must contain only digits.")

    # Проверка тестового кода
    if sms_code == "6666":
        user = db.query(User).filter(User.phone_number == phone_number).first()
    else:
        user = db.query(User).filter(
            User.phone_number == phone_number,
            User.last_sms_code == sms_code,
            User.sms_code_valid_until > datetime.utcnow()
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


@Auth_router.get("/user/me", response_model=UserMeResponse)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return {
        "phone_number": current_user.phone_number,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "wallet_balance": float(current_user.wallet_balance) if current_user.wallet_balance else 0.0
    }


@Auth_router.post("/refresh_token/")
async def refresh_token(db: Session = Depends(get_db), token: str = Depends(JWTBearer(expected_token_type="refresh"))):
    credentials_exception = HTTPException(status_code=401, detail="Could not validate credentials")
    phone_number: str = token.get("sub")
    if phone_number is None:
        raise credentials_exception
    user = db.query(User).filter(User.phone_number == phone_number).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

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
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """
    Загрузка документов пользователя.
    Принимает 4 фото:
    - Фото лицевой стороны удостоверения
    - Фото обратной стороны удостоверения
    - Фото водительских прав
    - Селфи с водительскими правами
    """
    # Проверяем MIME-type файлов
    allowed_types = ["image/jpeg", "image/png"]
    for doc in [id_front, id_back, drivers_license, selfie]:
        if doc.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"File {doc.filename} is not an image. Only JPEG and PNG are allowed."
            )

    try:
        # Сохраняем все файлы
        id_front_path = await save_file(id_front, current_user.id, "uploads/documents")
        id_back_path = await save_file(id_back, current_user.id, "uploads/documents")
        license_path = await save_file(drivers_license, current_user.id, "uploads/documents")
        selfie_path = await save_file(selfie, current_user.id, "uploads/documents")

        # Обновляем пользователя
        current_user.id_card_front_url = id_front_path
        current_user.id_card_back_url = id_back_path
        current_user.drivers_license_url = license_path
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
