from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import Dict, Any

import asyncio

from app.core.config import GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD
from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.car_model import Car
from app.models.user_model import User
from app.gps_api.utils.auth_api import get_auth_token
from app.gps_api.utils.get_active_rental import get_active_rental_car
from app.gps_api.utils.car_data import send_command_to_terminal
from app.gps_api.schemas import CommandRequest

Vehicle_Router = APIRouter(prefix="/vehicles", tags=["Vehicles"])

AUTH_TOKEN = ""
BASE_URL = "https://regions.glonasssoft.ru"
started = False


@Vehicle_Router.on_event("startup")
async def start_token_refresh():
    global started
    if not started:
        started = True

        async def refresh_token():
            global AUTH_TOKEN
            while True:
                try:
                    AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
                except Exception as e:
                    print(f"Ошибка обновления токена: {e}")
                await asyncio.sleep(70)

        asyncio.create_task(refresh_token())


@Vehicle_Router.get("/get_vehicles")
def get_vehicle_info(db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        cars = db.query(Car).all()

        vehicles_data = [{
            "id": car.id,
            "name": car.name,
            "plate_number": car.plate_number,
            "latitude": car.latitude,
            "longitude": car.longitude,
            "fuel_level": car.fuel_level,
            "price_per_minute": car.price_per_minute,
            "price_per_hour": car.price_per_hour,
            "price_per_day": car.price_per_day,
            "engine_volume": car.engine_volume,
            "year": car.year,
            "drive_type": car.drive_type,
            "photos": car.photos,
            "owner_id": car.owner_id,
            "current_renter_id": car.current_renter_id,
        } for car in cars]

        return {"vehicles": vehicles_data}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching vehicles data: {str(e)}")


# === КОМАНДЫ GlonassSoft ===

@Vehicle_Router.post("/open")
async def open_vehicle(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Dict:
    car = get_active_rental_car(db, current_user)
    return await send_command_to_terminal(int(car.gps_id), "*!CEVT 1", AUTH_TOKEN)


@Vehicle_Router.post("/close")
async def close_vehicle(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Dict:
    car = get_active_rental_car(db, current_user)
    return await send_command_to_terminal(int(car.gps_id), "*!CEVT 2", AUTH_TOKEN)


@Vehicle_Router.post("/give_key")
async def give_key(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Dict:
    car = get_active_rental_car(db, current_user)
    return await send_command_to_terminal(int(car.gps_id), "*!2Y", AUTH_TOKEN)


@Vehicle_Router.post("/take_key")
async def take_key(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Dict:
    car = get_active_rental_car(db, current_user)
    return await send_command_to_terminal(int(car.gps_id), "*!2N", AUTH_TOKEN)

# @Vehicle_Router.post("/block")
# async def block_engine(request: CommandRequest) -> Dict:
#     return await send_command_to_terminal(request.vehicle_id, "*!1Y", AUTH_TOKEN)
#
#
# @Vehicle_Router.post("/unblock")
# async def unblock_engine(request: CommandRequest) -> Dict:
#     return await send_command_to_terminal(request.vehicle_id, "*!1N", AUTH_TOKEN)
