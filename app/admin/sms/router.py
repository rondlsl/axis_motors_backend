from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.admin.sms.schemas import SendSmsRequest, SendSmsResponse
from app.guarantor.sms_utils import send_sms_mobizon
from app.core.config import SMS_TOKEN
from app.utils.telegram_logger import log_error_to_telegram

sms_router = APIRouter(tags=["Admin SMS"])


@sms_router.post("/send", response_model=SendSmsResponse)
async def send_custom_sms(
    request: SendSmsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Отправка произвольного SMS сообщения по номеру телефона.
    
    Доступно только для администраторов.
    
    - **phone_number**: Номер телефона получателя (только цифры, например 77771234567)
    - **message_text**: Текст SMS сообщения (до 500 символов)
    
    Примеры:
    ```json
    {
        "phone_number": "77771234567",
        "message_text": "Здравствуйте! Это сообщение от AZV Motors."
    }
    ```
    """
    # Проверка прав администратора
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав. Только администраторы или саппорт могут отправлять SMS.")
    
    # Валидация номера телефона
    phone_number = request.phone_number.strip()
    if not phone_number.isdigit():
        raise HTTPException(status_code=400, detail="Номер телефона должен содержать только цифры.")
    
    if len(phone_number) < 10 or len(phone_number) > 15:
        raise HTTPException(status_code=400, detail="Номер телефона должен содержать от 10 до 15 цифр.")
    
    # Валидация текста сообщения
    message_text = request.message_text.strip()
    if not message_text:
        raise HTTPException(status_code=400, detail="Текст сообщения не может быть пустым.")
    
    # Тестовый режим
    if SMS_TOKEN == "1010":
        print(f"TEST SMS to {phone_number}: {message_text}")
        return SendSmsResponse(
            success=True,
            message="TEST SMS sent successfully (test mode)",
            result="Test mode - SMS not actually sent"
        )
    
    # Отправка SMS
    try:
        result = await send_sms_mobizon(phone_number, message_text, SMS_TOKEN)
        return SendSmsResponse(
            success=True,
            message="SMS sent successfully",
            result=result
        )
    except Exception as e:
        print(f"SMS sending error: {e}")
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "admin_send_custom_sms",
                    "phone_number": request.phone_number,
                    "admin_id": str(current_user.id)
                }
            )
        except:
            pass
        return SendSmsResponse(
            success=False,
            message="SMS sending failed",
            error=str(e)
        )

