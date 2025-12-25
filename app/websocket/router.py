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
from app.utils.short_id import safe_sid_to_uuid, uuid_to_sid
from app.models.car_model import Car
from app.models.history_model import RentalHistory, RentalStatus
from app.websocket.admin_handlers import get_admin_cars_list_data, get_admin_users_list_data
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
        
        # Получаем информацию об арендаторе
        current_renter_info = None
        current_rental_info = None
        if car.current_renter_id:
            current_renter = db.query(User).filter(User.id == car.current_renter_id).first()
            if current_renter:
                active_rental_for_car = (
                    db.query(RentalHistory)
                    .filter(
                        RentalHistory.car_id == car.id,
                        RentalHistory.user_id == current_renter.id,
                        RentalHistory.rental_status.in_([
                            RentalStatus.RESERVED,
                            RentalStatus.IN_USE,
                            RentalStatus.DELIVERING,
                            RentalStatus.DELIVERY_RESERVED,
                            RentalStatus.DELIVERING_IN_PROGRESS
                        ])
                    )
                    .order_by(RentalHistory.reservation_time.desc())
                    .first()
                )
                
                current_renter_info = {
                    "id": uuid_to_sid(current_renter.id),
                    "first_name": current_renter.first_name,
                    "last_name": current_renter.last_name,
                    "middle_name": current_renter.middle_name,
                    "phone_number": current_renter.phone_number,
                    "selfie_url": current_renter.selfie_with_license_url
                }
                
                if active_rental_for_car:
                    current_rental_info = {
                        "rental_id": uuid_to_sid(active_rental_for_car.id),
                        "rental_status": active_rental_for_car.rental_status.value if active_rental_for_car.rental_status else None,
                        "rental_type": active_rental_for_car.rental_type.value if active_rental_for_car.rental_type else None,
                        "reservation_time": active_rental_for_car.reservation_time.isoformat() if active_rental_for_car.reservation_time else None,
                        "start_time": active_rental_for_car.start_time.isoformat() if active_rental_for_car.start_time else None,
                        "end_time": active_rental_for_car.end_time.isoformat() if active_rental_for_car.end_time else None
                    }
        
        try:
            glonassoft_data = await glonassoft_client.get_vehicle_data(vehicle_imei)
            if glonassoft_data:
                telemetry = process_glonassoft_data(glonassoft_data, car.name)
                telemetry_payload = jsonable_encoder(telemetry)
                # Добавляем информацию об арендаторе
                telemetry_payload["current_renter"] = current_renter_info
                telemetry_payload["current_rental"] = current_rental_info
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
                    db.expire_all()
                    db.refresh(car)
                    
                    glonassoft_data = await glonassoft_client.get_vehicle_data(vehicle_imei)
                    
                    if glonassoft_data:
                        telemetry = process_glonassoft_data(glonassoft_data, car.name)
                        telemetry_payload = jsonable_encoder(telemetry)
                        if car.current_renter_id:
                            current_renter = db.query(User).filter(User.id == car.current_renter_id).first()
                            if current_renter:
                                active_rental_for_car = (
                                    db.query(RentalHistory)
                                    .filter(
                                        RentalHistory.car_id == car.id,
                                        RentalHistory.user_id == current_renter.id,
                                        RentalHistory.rental_status.in_([
                                            RentalStatus.RESERVED,
                                            RentalStatus.IN_USE,
                                            RentalStatus.DELIVERING,
                                            RentalStatus.DELIVERY_RESERVED,
                                            RentalStatus.DELIVERING_IN_PROGRESS
                                        ])
                                    )
                                    .order_by(RentalHistory.reservation_time.desc())
                                    .first()
                                )
                                
                                telemetry_payload["current_renter"] = {
                                    "id": uuid_to_sid(current_renter.id),
                                    "first_name": current_renter.first_name,
                                    "last_name": current_renter.last_name,
                                    "middle_name": current_renter.middle_name,
                                    "phone_number": current_renter.phone_number,
                                    "selfie_url": current_renter.selfie_with_license_url
                                }
                                
                                if active_rental_for_car:
                                    telemetry_payload["current_rental"] = {
                                        "rental_id": uuid_to_sid(active_rental_for_car.id),
                                        "rental_status": active_rental_for_car.rental_status.value if active_rental_for_car.rental_status else None,
                                        "rental_type": active_rental_for_car.rental_type.value if active_rental_for_car.rental_type else None,
                                        "reservation_time": active_rental_for_car.reservation_time.isoformat() if active_rental_for_car.reservation_time else None,
                                        "start_time": active_rental_for_car.start_time.isoformat() if active_rental_for_car.start_time else None,
                                        "end_time": active_rental_for_car.end_time.isoformat() if active_rental_for_car.end_time else None
                                    }
                                else:
                                    telemetry_payload["current_rental"] = None
                            else:
                                telemetry_payload["current_renter"] = None
                                telemetry_payload["current_rental"] = None
                        else:
                            telemetry_payload["current_renter"] = None
                            telemetry_payload["current_rental"] = None
                        
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
                    db.expire_all()
                    db.refresh(user)
                    
                    vehicles_data = await get_vehicles_data_for_user(user, db)
                    await websocket.send_json({
                        "type": "vehicles_list",
                        "data": vehicles_data,
                        "timestamp": get_local_time().isoformat()
                    })
                    
                    await asyncio.sleep(1)
                    
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Error in vehicles list loop: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": "Error fetching vehicles data",
                        "timestamp": get_local_time().isoformat()
                    })
                    await asyncio.sleep(1)
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
                    db.expire_all()
                    db.refresh(user)
                    
                    user_data = await get_user_status_data(user, db)
                    await websocket.send_json({
                        "type": "user_status",
                        "data": user_data,
                        "timestamp": get_local_time().isoformat()
                    })
                    
                    await asyncio.sleep(2)
                    
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Error in user status loop: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": "Error fetching user status data",
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

@websocket_router.websocket("/ws/admin/cars/list")
async def websocket_admin_cars_list(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search_query: Optional[str] = Query(None)
):
    """WebSocket эндпоинт для списка машин админа (копия логики http)."""
    user = None
    db = SessionLocal()
    
    try:
        user = await authenticate_websocket(websocket, token, db)
        if not user:
            return
            
        if user.role != UserRole.ADMIN:
            await websocket.close(code=1008, reason="Not authorized")
            return
        
        user_id_str = str(user.id)
        
        await connection_manager.connect(
            websocket=websocket,
            connection_type="admin_cars_list",
            subscription_key="all",
            user_id=user_id_str,
            user_metadata={"phone": user.phone_number, "role": user.role.value}
        )
        
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
                    db.expire_all()
                    
                    # Получаем данные (аналогично HTTP эндпоинту)
                    cars_data = await get_admin_cars_list_data(db, status, search_query)
                    
                    await websocket.send_json({
                        "type": "admin_cars_list",
                        "data": cars_data,
                        "timestamp": get_local_time().isoformat()
                    })
                    
                    await asyncio.sleep(2) # Обновление каждые 2 секунды
                    
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Error in admin cars list loop: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": "Error fetching admin cars data",
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
        logger.info(f"WebSocket disconnected: user={user.id if user else 'unknown'}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if user:
            await connection_manager.disconnect(
                connection_type="admin_cars_list",
                subscription_key="all",
                user_id=str(user.id)
            )
        db.close()


@websocket_router.websocket("/ws/admin/users/list")
async def websocket_admin_users_list(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    search_query: Optional[str] = Query(None),
    has_active_rental: Optional[bool] = Query(None),
    is_blocked: Optional[bool] = Query(None),
    car_status: Optional[str] = Query(None)
):
    """WebSocket эндпоинт для real-time списка пользователей с координатами (для админки)."""
    user = None
    db = SessionLocal()
    
    try:
        user = await authenticate_websocket(websocket, token, db)
        if not user:
            return
        
        if user.role != UserRole.ADMIN:
            await websocket.close(code=1008, reason="Admin access required")
            return
        
        user_id_str = str(user.id)
        
        await connection_manager.connect(
            websocket=websocket,
            connection_type="admin_users_list",
            subscription_key="all",
            user_id=user_id_str,
            user_metadata={"phone": user.phone_number, "role": user.role.value}
        )
        
        async def receive_messages():
            while True:
                try:
                    message = await websocket.receive_text()
                    data = json.loads(message)
                    if data.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except WebSocketDisconnect:
                    break
                except Exception:
                    pass
        
        receive_task = asyncio.create_task(receive_messages())
        
        try:
            while True:
                try:
                    db.expire_all()
                    
                    users_data = await get_admin_users_list_data(
                        db=db,
                        role=role,
                        search_query=search_query,
                        has_active_rental=has_active_rental,
                        is_blocked=is_blocked,
                        car_status_filter=car_status
                    )
                    
                    await websocket.send_json({
                        "type": "users_list",
                        "data": users_data,
                        "timestamp": get_local_time().isoformat()
                    })
                    
                    await asyncio.sleep(2)
                    
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Error in admin users list loop: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": "Error fetching users data",
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
        logger.info(f"WebSocket disconnected: user={user.id if user else 'unknown'}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if user:
            await connection_manager.disconnect(
                connection_type="admin_users_list",
                subscription_key="all",
                user_id=str(user.id)
            )
        db.close()
