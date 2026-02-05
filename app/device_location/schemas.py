from typing import Optional
from pydantic import BaseModel, Field


class DeviceLocationPayload(BaseModel):
    """Payload from native app: background location update (only logged, not stored)."""
    latitude: float = Field(..., description="Latitude")
    longitude: float = Field(..., description="Longitude")
    accuracy: Optional[float] = Field(None, description="Accuracy in meters")
    altitude: Optional[float] = None
    timestamp: Optional[int] = Field(None, description="Client timestamp (ms)")
    device_id: Optional[str] = None
    app_version: Optional[str] = None
