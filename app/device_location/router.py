"""
Endpoint for device background location updates from the native app.
Data is only logged, not saved or forwarded.
"""
from fastapi import APIRouter, Request
from app.core.logging_config import get_logger
from app.device_location.schemas import DeviceLocationPayload

logger = get_logger(__name__)

router = APIRouter(prefix="/device", tags=["device"])


@router.post("/location", status_code=200)
async def report_device_location(payload: DeviceLocationPayload, request: Request):
    """
    Receive location update from the native app (background).
    Only logs the payload; does not save or forward.
    """
    return {"ok": True}
