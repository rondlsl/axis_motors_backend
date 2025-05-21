from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.user_model import User
from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.push.schemas import PushPayload
from app.push.utils import send_push_notification_async

router = APIRouter(tags=["Push"], prefix="/push")


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
