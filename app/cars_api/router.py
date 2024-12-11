import asyncio
from typing import Dict, Any

from fastapi import APIRouter, HTTPException

from app.cars_api.utils.auth_api import get_auth_token
from app.cars_api.utils.last_car_data import get_last_vehicles_data, send_command_to_terminal
from app.cars_api.schemas import VehicleIdsRequest, CommandRequest
from app.core.config import GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD

Vehicle_Router = APIRouter(prefix="/vehicles", tags=["Vehicles"])

AUTH_TOKEN = ""
BASE_URL = "https://regions.glonasssoft.ru"

started = False


@Vehicle_Router.on_event("startup")
async def start_token_refresh():
    """
    Запускает фоновую задачу для обновления токена каждые 10 секунд.
    """
    global started

    if not started:
        started = True

        async def refresh_token():
            global AUTH_TOKEN
            while True:
                try:
                    AUTH_TOKEN = get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
                except Exception as e:
                    print(f"Ошибка обновления токена: {e}")
                await asyncio.sleep(10)  # Ждем 10 секунд перед следующим обновлением

        asyncio.create_task(refresh_token())


@Vehicle_Router.post("/get_info")
def get_vehicle_info(request: VehicleIdsRequest) -> Dict[str, Any]:
    result = get_last_vehicles_data(AUTH_TOKEN, request.ids)
    if result is None:
        raise HTTPException(status_code=500, detail="Ошибка получения данных о машинах")
    return {"vehicles": result}


@Vehicle_Router.post("/open")
def open_vehicle(request: CommandRequest) -> Dict:
    """Открыть транспортное средство"""
    return send_command_to_terminal(
        vehicle_id=request.vehicle_id,
        command="chat OP",
        token=AUTH_TOKEN
    )


@Vehicle_Router.post("/close")
def close_vehicle(request: CommandRequest) -> Dict:
    """Закрыть транспортное средство"""
    return send_command_to_terminal(
        vehicle_id=request.vehicle_id,
        command="chat CL",
        token=AUTH_TOKEN
    )


@Vehicle_Router.post("/block")
def block_vehicle(request: CommandRequest) -> Dict:
    """Заблокировать транспортное средство"""
    return send_command_to_terminal(
        vehicle_id=request.vehicle_id,
        command="OUTPUT1 1",
        token=AUTH_TOKEN
    )


@Vehicle_Router.post("/unblock")
def unblock_vehicle(request: CommandRequest) -> Dict:
    """Разблокировать транспортное средство"""
    return send_command_to_terminal(
        vehicle_id=request.vehicle_id,
        command="OUTPUT1 0",
        token=AUTH_TOKEN
    )


@Vehicle_Router.post("/give_key")
def give_vehicle_key(request: CommandRequest) -> Dict:
    """Выдать ключ от транспортного средства"""
    return send_command_to_terminal(
        vehicle_id=request.vehicle_id,
        command="OUTPUT0 1",
        token=AUTH_TOKEN
    )


@Vehicle_Router.post("/take_key")
def take_vehicle_key(request: CommandRequest) -> Dict:
    """Забрать ключ от транспортного средства"""
    return send_command_to_terminal(
        vehicle_id=request.vehicle_id,
        command="OUTPUT0 0",
        token=AUTH_TOKEN
    )
