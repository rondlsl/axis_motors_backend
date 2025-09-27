from typing import List

from fastapi import APIRouter, Depends, status, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.translations.notifications import get_notification_text
from app.models.notification_model import Notification
from app.models.user_model import User
from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
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
    current_user.fcm_token = payload.fcm_token
    db.commit()
    return {"detail": "FCM token saved"}


@router.post("/send_push")
async def send_push(payload: PushPayload):
    success = await send_push_notification_async(payload.token, payload.title, payload.body)
    return {"success": success}


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

    data = []
    for n in notifs:
        # Если есть статус, применяем локализацию
        if n.status:
            # Маппинг статусов на ключи переводов
            status_to_key = {
                "out_of_tariff_charges": "overtime_charges",
                "basic_tariff_ending_soon": "pre_overtime_alert",
                "application_approved_financier": "financier_approve",
                "application_approved_mvd": "mvd_approve",
                "application_rejected_financier": "financier_reject_financial",
                "application_rejected_mvd": "mvd_reject",
                "mechanic_assigned": "mechanic_assigned",
                "delivery_started": "delivery_started",
                "car_delivered": "delivery_completed",
                "delivery_cancelled": "delivery_cancelled",
                "delivery_new_order": "delivery_new_order",
                "low_balance": "low_balance",
                "balance_exhausted": "balance_exhausted",
                "delivery_delay_penalty": "delivery_delay_penalty",
                "paid_waiting_soon": "pre_waiting_alert",
                "paid_waiting_started": "waiting_started",
                "new_car_for_inspection": "new_car_for_inspection"
            }
            
            translation_key = status_to_key.get(n.status.value)
            if translation_key:
                try:
                    # Получаем локализованный текст
                    title, body = get_notification_text(current_user.locale or "ru", translation_key)
                    data.append({
                        "id": n.id,
                        "title": title,
                        "body": body,
                        "sent_at": n.sent_at.isoformat(),
                        "is_read": n.is_read,
                        "status": n.status
                    })
                except Exception:
                    # Если ошибка в локализации, используем оригинальный текст
                    data.append({
                        "id": n.id,
                        "title": n.title,
                        "body": n.body,
                        "sent_at": n.sent_at.isoformat(),
                        "is_read": n.is_read,
                        "status": n.status
                    })
            else:
                # Если нет маппинга, используем оригинальный текст
                data.append({
                    "id": n.id,
                    "title": n.title,
                    "body": n.body,
                    "sent_at": n.sent_at.isoformat(),
                    "is_read": n.is_read,
                    "status": n.status
                })
        else:
            # Если нет статуса, но title и body выглядят как ключи локализации, применяем локализацию
            if n.title in ["overtime_charges", "pre_overtime_alert"] and n.body in ["out_of_tariff_charges", "basic_tariff_ending_soon"]:
                try:
                    # Определяем ключ локализации по title
                    translation_key = n.title
                    title, body = get_notification_text(current_user.locale or "ru", translation_key)
                    data.append({
                        "id": n.id,
                        "title": title,
                        "body": body,
                        "sent_at": n.sent_at.isoformat(),
                        "is_read": n.is_read,
                        "status": n.status
                    })
                except Exception:
                    # Если ошибка в локализации, используем оригинальный текст
                    data.append({
                        "id": n.id,
                        "title": n.title,
                        "body": n.body,
                        "sent_at": n.sent_at.isoformat(),
                        "is_read": n.is_read,
                        "status": n.status
                    })
            else:
                # Если нет статуса и это не ключи локализации, используем оригинальный текст (старые уведомления)
                data.append({
                    "id": n.id,
                    "title": n.title,
                    "body": n.body,
                    "sent_at": n.sent_at.isoformat(),
                    "is_read": n.is_read,
                    "status": n.status
                })

    return {"unread_count": unread, "notifications": data}


@router.patch("/{notif_id}/read", response_model=dict)
async def mark_as_read(
        notif_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Помечает одно уведомление как прочитанное.
    """
    notif = (
        db.query(Notification)
        .filter(
            Notification.id == notif_id,
            Notification.user_id == current_user.id
        )
        .first()
    )
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")

    notif.is_read = True
    db.commit()
    return {"success": True, "id": notif.id}
