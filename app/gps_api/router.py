import asyncio
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies.get_current_user import get_current_user
from app.dependencies.database.database import get_db
from app.gps_api.utils.auth_api import get_auth_token
from app.gps_api.utils.get_active_rental import get_active_rental_car
from app.gps_api.utils.last_car_data import get_last_vehicles_data, send_command_to_terminal, get_vehicle_data
from app.gps_api.schemas import VehicleIdsRequest, CommandRequest
from app.core.config import GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD
from app.models.user_model import User

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
                await asyncio.sleep(70)

        asyncio.create_task(refresh_token())


# @Vehicle_Router.post("/get_info")
# def get_vehicle_info(request: VehicleIdsRequest) -> Dict[str, Any]:
#     result = get_last_vehicles_data(AUTH_TOKEN, request.ids)
#     if result is None:
#         raise HTTPException(status_code=500, detail="Ошибка получения данных о машинах")
#     return {"vehicles": result}

@Vehicle_Router.post("/get_vehicles")
def get_vehicle_info() -> Dict[str, Any]:
    result = get_last_vehicles_data(AUTH_TOKEN, [800149805])
    if result is None:
        raise HTTPException(status_code=500, detail="Ошибка получения данных о машинах")
    return {"vehicles": result}


@Vehicle_Router.post("/open")
def open_vehicle(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> Dict:
    """Open the vehicle from current active rental"""
    car = get_active_rental_car(db, current_user)
    return send_command_to_terminal(
        vehicle_id=int(car.gps_id),
        command="chat OP",
        token=AUTH_TOKEN
    )


@Vehicle_Router.post("/close")
def close_vehicle(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> Dict:
    """Close the vehicle from current active rental"""
    car = get_active_rental_car(db, current_user)
    return send_command_to_terminal(
        vehicle_id=int(car.gps_id),
        command="chat CL",
        token=AUTH_TOKEN
    )


@Vehicle_Router.post("/give_key")
def give_vehicle_key(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> Dict:
    """Give key to the vehicle from current active rental"""
    car = get_active_rental_car(db, current_user)
    return send_command_to_terminal(
        vehicle_id=int(car.gps_id),
        command="OUTPUT0 1",
        token=AUTH_TOKEN
    )


@Vehicle_Router.post("/take_key")
def take_vehicle_key(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> Dict:
    """Take key from the vehicle from current active rental"""
    car = get_active_rental_car(db, current_user)
    return send_command_to_terminal(
        vehicle_id=int(car.gps_id),
        command="OUTPUT0 0",
        token=AUTH_TOKEN
    )


# @Vehicle_Router.post("/block")
# def block_vehicle(request: CommandRequest) -> Dict:
#     """Заблокировать транспортное средство"""
#     return send_command_to_terminal(
#         vehicle_id=request.vehicle_id,
#         command="OUTPUT1 1",
#         token=AUTH_TOKEN
#     )


# @Vehicle_Router.post("/unblock")
# def unblock_vehicle(request: CommandRequest) -> Dict:
#     """Разблокировать транспортное средство"""
#     return send_command_to_terminal(
#         vehicle_id=request.vehicle_id,
#         command="OUTPUT1 0",
#         token=AUTH_TOKEN
#     )


@Vehicle_Router.get("/{vehicle_id}")
def get_vehicle_by_id(vehicle_id: int):
    """
    Эндпоинт для получения данных машины по ID.

    :param vehicle_id: ID машины (передается в URL).
    :return: Данные машины или ошибка.
    """
    result = get_vehicle_data(AUTH_TOKEN, vehicle_id)
    if result is None:
        raise HTTPException(status_code=500, detail="Ошибка получения данных о машине")
    return {"vehicle": result}
