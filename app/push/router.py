from typing import List

from fastapi import APIRouter, Depends, status, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.translations.notifications import get_notification_text
from app.models.notification_model import Notification
from app.models.user_model import User
from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.utils.short_id import uuid_to_sid, safe_sid_to_uuid
from app.push.schemas import PushPayload, NotificationListResponse
from app.push.utils import send_push_notification_async
from app.push.enums import NotificationStatus

router = APIRouter(prefix="/notifications", tags=["notifications"])


class TokenRequest(BaseModel):
    fcm_token: str


@router.post("/save_token", status_code=status.HTTP_200_OK)
async def save_fcm_token(payload: TokenRequest,
                         db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    """
    Save FCM token for push notifications.
    """
    print(f"📱 [SAVE_TOKEN] User {current_user.phone_number} - Token: {payload.fcm_token[:50]}...")
    
    current_user.fcm_token = payload.fcm_token
    db.add(current_user)
    db.flush()
    db.commit()
    db.refresh(current_user)
    
    print(f"✅ [SAVE_TOKEN] Token saved successfully")
    
    return {
        "detail": "FCM token saved",
        "user_id": str(current_user.id),
        "phone": current_user.phone_number
    }


@router.post("/send_push")
async def send_push(payload: PushPayload):
    success = await send_push_notification_async(payload.token, payload.title, payload.body)
    return {"success": success}


class TestPushRequest(BaseModel):
    phone: str  # Номер телефона пользователя
    title: str = "Тестовое уведомление"
    body: str = "Это тестовое push-уведомление для проверки работы системы"


@router.post("/test_push_by_phone", status_code=status.HTTP_200_OK)
async def test_push_by_phone(
    payload: TestPushRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Тестовый endpoint для отправки push-уведомления по номеру телефона.
    Доступен только администраторам и механикам для тестирования.
    
    Args:
        phone: Номер телефона пользователя (например: 77777777772)
        title: Заголовок уведомления (по умолчанию: "Тестовое уведомление")
        body: Текст уведомления
    
    Returns:
        Информацию об успешности отправки и детали
    """
    from app.models.user_model import UserRole
    
    # Отладочный вывод для проверки роли
    print(f"🔍 Current user: phone={current_user.phone_number}, role={current_user.role}, role_value={current_user.role.value if current_user.role else None}")
    print(f"🔍 UserRole.ADMIN={UserRole.ADMIN}, UserRole.MECHANIC={UserRole.MECHANIC}")
    print(f"🔍 Comparison: role == ADMIN: {current_user.role == UserRole.ADMIN}, role == MECHANIC: {current_user.role == UserRole.MECHANIC}")
    
    # Проверяем права доступа (только админ и механик могут тестировать)
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC]:
        raise HTTPException(
            status_code=403, 
            detail=f"Only admins and mechanics can use test endpoints. Your role: {current_user.role.value if current_user.role else None}"
        )
    
    # Находим пользователя по номеру телефона
    target_user = db.query(User).filter(User.phone_number == payload.phone).first()
    
    if not target_user:
        raise HTTPException(
            status_code=404, 
            detail=f"User with phone {payload.phone} not found"
        )
    
    # Проверяем наличие FCM токена
    if not target_user.fcm_token:
        raise HTTPException(
            status_code=400, 
            detail=f"User {target_user.phone_number} doesn't have FCM token. User needs to login to the app first."
        )
    
    # Отправляем push-уведомление
    success = await send_push_notification_async(
        token=target_user.fcm_token,
        title=payload.title,
        body=payload.body
    )
    
    # Формируем полное имя
    full_name = f"{target_user.first_name or ''} {target_user.last_name or ''} {target_user.middle_name or ''}".strip() or "Не указано"
    
    return {
        "success": success,
        "user": {
            "id": str(target_user.id),
            "phone": target_user.phone_number,
            "name": full_name,
            "role": target_user.role.value if target_user.role else None,
            "fcm_token": target_user.fcm_token[:30] + "..." if len(target_user.fcm_token) > 30 else target_user.fcm_token
        },
        "message": "Push notification sent successfully" if success else "Failed to send push notification"
    }


@router.get("/test_users_with_tokens", status_code=status.HTTP_200_OK)
async def get_users_with_tokens(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Тестовый endpoint для получения списка пользователей с FCM токенами.
    Доступен только администраторам для тестирования.
    """
    from app.models.user_model import UserRole
    
    # Проверяем права доступа
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC]:
        raise HTTPException(
            status_code=403,
            detail="Only admins and mechanics can access this endpoint"
        )
    
    # Получаем всех пользователей с токенами
    users = db.query(User).filter(User.fcm_token.isnot(None)).all()
    
    return {
        "total_users_with_tokens": len(users),
        "users": [
            {
                "id": str(user.id),
                "phone": user.phone_number,
                "name": f"{user.first_name or ''} {user.last_name or ''} {user.middle_name or ''}".strip() or "Не указано",
                "role": user.role.value if user.role else None,
                "fcm_token_preview": user.fcm_token[:30] + "..." if len(user.fcm_token) > 30 else user.fcm_token,
                "fcm_token": user.fcm_token  # Полный токен для копирования
            }
            for user in users
        ]
    }


@router.get("/", response_model=NotificationListResponse)
async def list_notifications(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Возвращает все уведомления текущего юзера,
    плюс количество непрочитанных.
    """    
    notifs: List[Notification] = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.sent_at.desc())
        .all()
    )
    unread = sum(1 for n in notifs if not n.is_read)

    data = [{
        "id": uuid_to_sid(n.id),
        "title": n.title,
        "body": n.body,
        "sent_at": n.sent_at.isoformat(),
        "is_read": n.is_read,
        "status": n.status
    } for n in notifs]

    return {"unread_count": unread, "notifications": data}


@router.patch("/{notif_id}/read", response_model=dict)
async def mark_as_read(
        notif_id: str,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Помечает одно уведомление как прочитанное.
    """
    notif_uuid = safe_sid_to_uuid(notif_id)
    notif = (
        db.query(Notification)
        .filter(
            Notification.id == notif_uuid,
            Notification.user_id == current_user.id
        )
        .first()
    )
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")

    notif.is_read = True
    db.commit()
    return {"success": True, "id": notif_id}
