from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
import firebase_admin
from firebase_admin import credentials, messaging

from app.models.user_model import User
from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user

router = APIRouter(tags=["Push"], prefix="/push")

cred = credentials.Certificate("app/push/firebase-service-account.json")
firebase_admin.initialize_app(cred)


class TokenRequest(BaseModel):
    fcm_token: str


@router.post("/save_token", status_code=status.HTTP_200_OK)
def save_fcm_token(payload: TokenRequest,
                   db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    current_user.fcm_token = payload.fcm_token
    db.commit()
    return {"detail": "FCM token saved"}


def send_push_notification(token: str, title: str, body: str):
    try:
        # Android: sound and vibration (via channel)
        android_config = messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                title=title,
                body=body,
                sound="default",           # Воспроизведение звука
                channel_id="high_importance_channel",  # Канал должен быть настроен на вибрацию
            )
        )
        # iOS: sound
        apns_config = messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    alert=messaging.ApsAlert(
                        title=title,
                        body=body
                    ),
                    sound="default"           # Воспроизведение звука на iOS
                )
            )
        )
        message = messaging.Message(
            android=android_config,
            apns=apns_config,
            token=token
        )
        response = messaging.send(message)
        print('Successfully sent message:', response)
        return True
    except Exception as e:
        print('Push error:', e)
        return False


class PushPayload(BaseModel):
    token: str
    title: str
    body: str


@router.post("/send_push")
def send_push(payload: PushPayload):
    success = send_push_notification(payload.token, payload.title, payload.body)
    return {"success": success}
