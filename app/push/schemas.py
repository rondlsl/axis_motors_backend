from pydantic import BaseModel
from typing import Optional
from app.push.enums import NotificationStatus


class PushPayload(BaseModel):
    token: str
    title: str
    body: str


class NotificationResponse(BaseModel):
    id: str
    title: str
    body: str
    sent_at: str
    is_read: bool
    status: Optional[NotificationStatus] = None


class NotificationListResponse(BaseModel):
    unread_count: int
    notifications: list[NotificationResponse]
