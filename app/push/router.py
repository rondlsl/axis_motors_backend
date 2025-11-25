from typing import List

from fastapi import APIRouter, Depends, status, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.translations.notifications import get_notification_text
from app.models.notification_model import Notification
from app.models.user_model import User
from app.models.user_device_model import UserDevice
from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.utils.short_id import uuid_to_sid, safe_sid_to_uuid
from app.push.schemas import (
    PushPayload,
    NotificationListResponse,
    DeviceRegisterRequest,
    UserDeviceResponse,
)
from app.push.utils import send_push_notification_async
from app.push.enums import NotificationStatus
from app.utils.telegram_logger import log_error_to_telegram
from app.utils.time_utils import get_local_time

router = APIRouter(prefix="/notifications", tags=["notifications"])


class TokenRequest(BaseModel):
    fcm_token: str


def _device_to_response(device: UserDevice) -> UserDeviceResponse:
    return UserDeviceResponse.from_orm(device)


def _get_client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


@router.post("/save_token", status_code=status.HTTP_200_OK)
async def save_fcm_token(payload: TokenRequest,
                         db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    """
    Save FCM token for push notifications.
    """
    try:
        token = (payload.fcm_token or "").strip()
        if not token:
            raise HTTPException(status_code=400, detail="FCM token is required")

        print(f"📱 [SAVE_TOKEN] User {current_user.phone_number} - Token: {token[:50]}...")

        duplicates = (
            db.query(User)
            .filter(User.fcm_token == token, User.id != current_user.id)
            .all()
        )

        cleared_users = []
        for user in duplicates:
            cleared_users.append(str(user.id))
            user.fcm_token = None
            db.add(user)

        current_user.fcm_token = token
        db.add(current_user)
        db.flush()
        db.commit()
        db.refresh(current_user)
        
        print(f"✅ [SAVE_TOKEN] Token saved successfully")
        
        response = {
            "detail": "FCM token saved",
            "user_id": str(current_user.id),
            "phone": current_user.phone_number
        }

        if cleared_users:
            response["duplicates_cleared"] = cleared_users

        return response
    except Exception as e:
        db.rollback()
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "save_fcm_token",
                    "user_id": str(current_user.id),
                    "phone": current_user.phone_number,
                    "token_preview": payload.fcm_token[:50] if payload.fcm_token else None
                }
            )
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения push-токена: {str(e)}")


@router.post("/devices", response_model=UserDeviceResponse, status_code=status.HTTP_200_OK)
async def register_device(
    payload: DeviceRegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    token = (payload.fcm_token or "").strip()
    device_uuid = (payload.device_uuid or "").strip()

    if not token:
        raise HTTPException(status_code=400, detail="FCM token is required")
    if not device_uuid:
        raise HTTPException(status_code=400, detail="device_uuid is required")

    try:
        duplicates = (
            db.query(UserDevice)
            .filter(UserDevice.fcm_token == token, UserDevice.device_uuid != device_uuid)
            .all()
        )
        for device in duplicates:
            device.fcm_token = None
            device.is_active = False
            device.revoked_at = get_local_time()
            device.update_timestamp()
            db.add(device)

        device = db.query(UserDevice).filter(UserDevice.device_uuid == device_uuid).first()
        if device is None:
            device = UserDevice(device_uuid=device_uuid, user_id=current_user.id)
        else:
            device.user_id = current_user.id

        device.fcm_token = token
        device.platform = payload.platform
        device.model = payload.model
        device.os_version = payload.os_version
        device.app_version = payload.app_version
        device.last_ip = _get_client_ip(request)
        device.last_lat = payload.last_lat
        device.last_lng = payload.last_lng
        device.last_active_at = get_local_time()
        device.is_active = True
        device.revoked_at = None
        device.update_timestamp()

        db.add(device)

        current_user.fcm_token = token
        db.add(current_user)

        db.commit()
        db.refresh(device)

        return _device_to_response(device)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "register_device",
                    "user_id": str(current_user.id),
                    "device_uuid": device_uuid,
                    "token_preview": token[:50] if token else None
                }
            )
        except:
            pass
        raise HTTPException(status_code=500, detail="Не удалось зарегистрировать устройство")


@router.get("/devices", response_model=List[UserDeviceResponse], status_code=status.HTTP_200_OK)
async def list_devices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    devices = (
        db.query(UserDevice)
        .filter(UserDevice.user_id == current_user.id)
        .order_by(UserDevice.created_at.desc())
        .all()
    )
    return [_device_to_response(device) for device in devices]


@router.delete("/devices/{device_uuid}", status_code=status.HTTP_200_OK)
async def revoke_device(
    device_uuid: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    device = (
        db.query(UserDevice)
        .filter(UserDevice.device_uuid == device_uuid, UserDevice.user_id == current_user.id)
        .first()
    )
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    removed_token = device.fcm_token
    device.is_active = False
    device.fcm_token = None
    device.revoked_at = get_local_time()
    device.update_timestamp()
    db.add(device)

    if current_user.fcm_token and current_user.fcm_token == removed_token:
        current_user.fcm_token = None
        db.add(current_user)

    db.commit()
    return {"detail": "Device revoked"}


@router.post("/send_push")
async def send_push(payload: PushPayload):
    try:
        success = await send_push_notification_async(payload.token, payload.title, payload.body)
        return {"success": success}
    except Exception as e:
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=None,
                additional_context={
                    "action": "send_push_manual",
                    "token_preview": payload.token[:50] if payload.token else None,
                    "title": payload.title,
                    "body": payload.body[:100] if payload.body else None
                }
            )
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Ошибка отправки push: {str(e)}")


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
    """
    from app.models.user_model import UserRole
    
    import sys
    
    print("="*80)
    print("🔔 [TEST_PUSH_BY_PHONE] Запрос получен")
    print(f"📱 Ищем пользователя: {payload.phone}")
    print(f"👤 От: {current_user.phone_number} (роль: {current_user.role.value if current_user.role else None})")
    print(f"📝 Заголовок: {payload.title}")
    print(f"📝 Текст: {payload.body}")
    sys.stdout.flush()
    
    # Проверяем права доступа
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC]:
        print(f"❌ Доступ запрещен - роль {current_user.role}")
        raise HTTPException(
            status_code=403, 
            detail=f"Only admins and mechanics can use test endpoints. Your role: {current_user.role.value if current_user.role else None}"
        )
    
    # Находим пользователя
    target_user = db.query(User).filter(User.phone_number == payload.phone).first()
    
    if not target_user:
        print(f"❌ Пользователь {payload.phone} не найден")
        raise HTTPException(status_code=404, detail=f"User with phone {payload.phone} not found")
    
    print(f"✅ Пользователь найден: {target_user.id}")
    print(f"   Имя: {target_user.first_name} {target_user.last_name}")
    
    # Проверяем токен
    if not target_user.fcm_token:
        print(f"❌ У пользователя нет FCM токена")
        raise HTTPException(status_code=400, detail=f"User {target_user.phone_number} doesn't have FCM token")
    
    print(f"✅ FCM токен найден: {target_user.fcm_token[:50]}...")
    print(f"🚀 Начинаем отправку push-уведомления...")
    print("-"*80)
    sys.stdout.flush()
    
    # Отправляем push
    success = await send_push_notification_async(
        token=target_user.fcm_token,
        title=payload.title,
        body=payload.body
    )
    
    print("-"*80)
    if success:
        print(f"✅ [TEST_PUSH_BY_PHONE] Push отправлен успешно!")
    else:
        print(f"❌ [TEST_PUSH_BY_PHONE] Ошибка отправки push")
    print("="*80)
    print()
    sys.stdout.flush()
    
    # Формируем ответ
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
