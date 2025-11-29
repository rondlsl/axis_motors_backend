from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
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


class DeviceRegisterRequest(BaseModel):
    device_uuid: Optional[str] = None
    fcm_token: str
    platform: Optional[str] = None
    model: Optional[str] = None
    os_version: Optional[str] = None
    app_version: Optional[str] = None
    last_lat: Optional[float] = None
    last_lng: Optional[float] = None


class UserDeviceResponse(BaseModel):
    id: str
    device_uuid: Optional[str] = None
    platform: Optional[str] = None
    model: Optional[str] = None
    os_version: Optional[str] = None
    app_version: Optional[str] = None
    last_ip: Optional[str] = None
    last_lat: Optional[float] = None
    last_lng: Optional[float] = None
    last_active_at: Optional[datetime] = None
    is_active: bool
    revoked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
