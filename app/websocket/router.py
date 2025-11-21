from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from fastapi.encoders import jsonable_encoder
from typing import Optional
import logging
import asyncio
import json

from app.dependencies.database.database import SessionLocal
from app.websocket.manager import connection_manager
from app.websocket.auth import authenticate_websocket
from app.websocket.handlers import get_vehicles_data_for_user, get_user_status_data
from app.models.user_model import User, UserRole
from app.utils.short_id import safe_sid_to_uuid
from app.models.car_model import Car
from app.gps_api.utils.glonassoft_client import glonassoft_client
from app.gps_api.utils.telemetry_processor import process_glonassoft_data
from app.utils.time_utils import get_local_time

logger = logging.getLogger(__name__)

websocket_router = APIRouter()


@websocket_router.websocket("/ws/vehicles/telemetry/{car_id}")
async def websocket_vehicle_telemetry(
    websocket: WebSocket,
    car_id: str,
    token: Optional[str] = Query(None)
):
    """WebSocket эндпоинт для real-time телеметрии автомобиля."""
    user = None
    car_uuid = None
    db = SessionLocal()
    
    try:
        user = await authenticate_websocket(websocket, token, db)
        if not user:
            return
        
        if user.role != UserRole.ADMIN:
            await websocket.close(code=1008, reason="Only administrators can access telemetry")
            return
        
        car_uuid = safe_sid_to_uuid(car_id)
        car = db.query(Car).filter(Car.id == car_uuid).first()
        
        if not car:
            await websocket.close(code=1008, reason="Car not found")
            return
        
        vehicle_imei = (
            getattr(car, 'gps_imei', None)
            or getattr(car, 'imei', None)
            or getattr(car, 'vehicle_imei', None)
        )
        
        if not vehicle_imei:
            await websocket.close(code=1008, reason="IMEI not found for this car")
            return
        
        user_id_str = str(user.id)
        subscription_key = car_id
        
        await connection_manager.connect(
            websocket=websocket,
            connection_type="telemetry",
            subscription_key=subscription_key,
            user_id=user_id_str,
            user_metadata={"phone": user.phone_number, "role": user.role.value}
        )
        
        try:
            glonassoft_data = await glonassoft_client.get_vehicle_data(vehicle_imei)
            if glonassoft_data:
                telemetry = process_glonassoft_data(glonassoft_data, car.name)
                telemetry_payload = jsonable_encoder(telemetry)
                await websocket.send_json({
                    "type": "telemetry",
                    "data": telemetry_payload,
                    "timestamp": get_local_time().isoformat()
                })
        except Exception:
            logger.exception("Error sending initial telemetry")
        
        last_data_hash = None
        
        async def receive_messages():
            while True:
                try:
                    data = await websocket.receive_json()
                    if data.get("type") == "ping":
                        await websocket.send_json({
                            "type": "pong",
                            "timestamp": get_local_time().isoformat()
                        })
                except WebSocketDisconnect:
                    break
                except Exception:
                    logger.exception("Error receiving message")
                    break
        
        receive_task = asyncio.create_task(receive_messages())
        
        try:
            while True:
                try:
                    glonassoft_data = await glonassoft_client.get_vehicle_data(vehicle_imei)
                    
                    if glonassoft_data:
                        telemetry = process_glonassoft_data(glonassoft_data, car.name)
                        telemetry_payload = jsonable_encoder(telemetry)
                        current_data_hash = hash(json.dumps(telemetry_payload, sort_keys=True, default=str))
                        
                        if current_data_hash != last_data_hash or last_data_hash is None:
                            await websocket.send_json({
                                "type": "telemetry",
                                "data": telemetry_payload,
                                "timestamp": get_local_time().isoformat()
                            })
                            last_data_hash = current_data_hash
                    
                    await asyncio.sleep(2)
                    
                except WebSocketDisconnect:
                    break
                except Exception:
                    logger.exception("Error in telemetry loop")
                    await websocket.send_json({
                        "type": "error",
                        "message": "Error fetching telemetry data",
                        "timestamp": get_local_time().isoformat()
                    })
                    await asyncio.sleep(2)
        finally:
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: user={user.id if user else 'unknown'}, car_id={car_id}")
    except Exception:
        logger.exception("WebSocket error")
    finally:
        if user and car_id:
            await connection_manager.disconnect(
                connection_type="telemetry",
                subscription_key=car_id,
                user_id=str(user.id)
            )
        db.close()


@websocket_router.websocket("/ws/vehicles/list")
async def websocket_vehicles_list(
    websocket: WebSocket,
    token: Optional[str] = Query(None)
):
    """WebSocket эндпоинт для real-time обновлений списка машин."""
    user = None
    db = SessionLocal()
    
    try:
        user = await authenticate_websocket(websocket, token, db)
        if not user:
            return
        
        user_id_str = str(user.id)
        subscription_key = "all"
        
        await connection_manager.connect(
            websocket=websocket,
            connection_type="vehicles_list",
            subscription_key=subscription_key,
            user_id=user_id_str,
            user_metadata={"phone": user.phone_number, "role": user.role.value}
        )
        
        initial_data = await get_vehicles_data_for_user(user, db)
        await websocket.send_json({
            "type": "vehicles_list",
            "data": initial_data,
            "timestamp": get_local_time().isoformat()
        })
        
        last_data_hash = None
        
        async def receive_messages():
            while True:
                try:
                    data = await websocket.receive_json()
                    if data.get("type") == "ping":
                        await websocket.send_json({
                            "type": "pong",
                            "timestamp": get_local_time().isoformat()
                        })
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Error receiving message: {e}")
                    break
        
        receive_task = asyncio.create_task(receive_messages())
        
        try:
            while True:
                try:
                    vehicles_data = await get_vehicles_data_for_user(user, db)
                    current_data_hash = hash(json.dumps(vehicles_data, sort_keys=True, default=str))
                    
                    if current_data_hash != last_data_hash:
                        await websocket.send_json({
                            "type": "vehicles_list",
                            "data": vehicles_data,
                            "timestamp": get_local_time().isoformat()
                        })
                        last_data_hash = current_data_hash
                    
                    await asyncio.sleep(10)
                    
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Error in vehicles list loop: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": "Error fetching vehicles data",
                        "timestamp": get_local_time().isoformat()
                    })
                    await asyncio.sleep(10)
        finally:
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: user={user.id if user else 'unknown'}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if user:
            await connection_manager.disconnect(
                connection_type="vehicles_list",
                subscription_key="all",
                user_id=str(user.id)
            )
        db.close()


@websocket_router.websocket("/ws/auth/user/status")
async def websocket_user_status(
    websocket: WebSocket,
    token: Optional[str] = Query(None)
):
    """WebSocket эндпоинт для real-time обновлений статуса аренды пользователя."""
    logger.info(f"WebSocket connection attempt to /ws/auth/user/status, token present: {token is not None}")
    user = None
    db = SessionLocal()
    
    try:
        user = await authenticate_websocket(websocket, token, db)
        if not user:
            return
        
        user_id_str = str(user.id)
        subscription_key = user_id_str
        
        await connection_manager.connect(
            websocket=websocket,
            connection_type="user_status",
            subscription_key=subscription_key,
            user_id=user_id_str,
            user_metadata={"phone": user.phone_number, "role": user.role.value}
        )
        
        initial_data = await get_user_status_data(user, db)
        await websocket.send_json({
            "type": "user_status",
            "data": initial_data,
            "timestamp": get_local_time().isoformat()
        })
        
        last_data_hash = None
        
        async def receive_messages():
            while True:
                try:
                    data = await websocket.receive_json()
                    if data.get("type") == "ping":
                        await websocket.send_json({
                            "type": "pong",
                            "timestamp": get_local_time().isoformat()
                        })
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Error receiving message: {e}")
                    break
        
        receive_task = asyncio.create_task(receive_messages())
        
        try:
            while True:
                try:
                    user_data = await get_user_status_data(user, db)
                    current_data_hash = hash(json.dumps(user_data, sort_keys=True, default=str))
                    
                    if current_data_hash != last_data_hash:
                        await websocket.send_json({
                            "type": "user_status",
                            "data": user_data,
                            "timestamp": get_local_time().isoformat()
                        })
                        last_data_hash = current_data_hash
                    
                    await asyncio.sleep(10)
                    
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Error in user status loop: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": "Error fetching user status data",
                        "timestamp": get_local_time().isoformat()
                    })
                    await asyncio.sleep(10)
        finally:
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: user={user.id if user else 'unknown'}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if user:
            await connection_manager.disconnect(
                connection_type="user_status",
                subscription_key=str(user.id),
                user_id=str(user.id)
            )
        db.close()

