import asyncio
import logging
from typing import Optional, Dict, Any
from uuid import UUID

from app.websocket.manager import connection_manager
from app.websocket.handlers import get_vehicles_data_for_user, get_user_status_data
from app.dependencies.database.database import SessionLocal
from app.models.user_model import User
from app.models.application_model import Application
from app.models.history_model import RentalHistory
from app.models.car_model import Car
from app.models.guarantor_model import Guarantor
from app.models.contract_model import UserContractSignature, ContractFile
from app.utils.time_utils import get_local_time

logger = logging.getLogger(__name__)

# Ограничение одновременных уведомлений, чтобы не исчерпывать лимит файловых дескрипторов (сессии БД + сокеты)
_NOTIFICATION_SEMAPHORE: Optional[asyncio.Semaphore] = None


def _get_notification_semaphore() -> asyncio.Semaphore:
    global _NOTIFICATION_SEMAPHORE
    if _NOTIFICATION_SEMAPHORE is None:
        _NOTIFICATION_SEMAPHORE = asyncio.Semaphore(8)
    return _NOTIFICATION_SEMAPHORE


def _ensure_uuid(value: Optional[str]) -> Optional[UUID]:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except Exception:
        return None


async def notify_vehicles_list_update(user_id: Optional[str] = None) -> None:
    """
    Отправить обновление списка машин через WebSocket.
    Ограничено семафором, чтобы не создавать слишком много одновременных сессий БД.
    """
    semaphore = _get_notification_semaphore()
    async with semaphore:
        db = None
        try:
            db = SessionLocal()
            if user_id:
                user_uuid = _ensure_uuid(user_id)
                if not user_uuid:
                    return
                db.expire_all()
                user = db.query(User).filter(User.id == user_uuid).first()
                if user:
                    db.refresh(user)
                    vehicles_data = await get_vehicles_data_for_user(user, db)
                    await connection_manager.send_personal_message(
                        connection_type="vehicles_list",
                        subscription_key="all",
                        user_id=str(user_uuid),
                        message={
                            "type": "vehicles_list",
                            "data": vehicles_data,
                            "timestamp": get_local_time().isoformat()
                        }
                    )
            else:
                connected_users = connection_manager.get_connected_users("vehicles_list")
                for uid in connected_users:
                    user_uuid = _ensure_uuid(uid)
                    if not user_uuid:
                        continue
                    db.expire_all()
                    user = db.query(User).filter(User.id == user_uuid).first()
                    if not user:
                        continue
                    db.refresh(user)
                    vehicles_data = await get_vehicles_data_for_user(user, db)
                    await connection_manager.send_personal_message(
                        connection_type="vehicles_list",
                        subscription_key="all",
                        user_id=str(user_uuid),
                        message={
                            "type": "vehicles_list",
                            "data": vehicles_data,
                            "timestamp": get_local_time().isoformat()
                        }
                    )
        except Exception as e:
            logger.error("Error notifying vehicles list update: %s", e)
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception as close_err:
                    logger.error("Error closing DB session in notify_vehicles_list_update: %s", close_err)


async def notify_user_status_update(user_id: str) -> None:
    """
    Отправить обновление статуса пользователя через WebSocket.
    Ограничено семафором, чтобы не создавать слишком много одновременных сессий БД.
    """
    semaphore = _get_notification_semaphore()
    async with semaphore:
        user_uuid = _ensure_uuid(user_id)
        if not user_uuid:
            return
        db = None
        try:
            db = SessionLocal()
            db.expire_all()
            user = db.query(User).filter(User.id == user_uuid).first()
            if user:
                db.refresh(user)
                application = db.query(Application).filter(Application.user_id == user.id).first()
                if application:
                    db.refresh(application)
                db.expire_all()
                db.refresh(user)
                if application:
                    db.refresh(application)
                user_data = await get_user_status_data(user, db)
                await connection_manager.send_personal_message(
                    connection_type="user_status",
                    subscription_key=str(user_uuid),
                    user_id=str(user_uuid),
                    message={
                        "type": "user_status",
                        "data": user_data,
                        "timestamp": get_local_time().isoformat()
                    }
                )
        except Exception as e:
            logger.error("Error notifying user status update: %s", e)
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception as close_err:
                    logger.error("Error closing DB session in notify_user_status_update: %s", close_err)


async def notify_telemetry_update(car_id: str, telemetry_data: Dict[str, Any]) -> None:
    """
    Отправить обновление телеметрии через WebSocket.
    
    Args:
        car_id: ID автомобиля
        telemetry_data: Данные телеметрии
    """
    try:
        await connection_manager.broadcast_to_subscription(
            connection_type="telemetry",
            subscription_key=car_id,
            message={
                "type": "telemetry",
                "data": telemetry_data,
                "timestamp": get_local_time().isoformat()
            }
        )
    except Exception as e:
        logger.error(f"Error notifying telemetry update: {e}")

