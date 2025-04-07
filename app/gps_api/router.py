from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import or_, func
from sqlalchemy.orm import Session
from typing import Dict, Any
import asyncio

from app.core.config import GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD
from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.car_model import Car
from app.models.history_model import RentalHistory
from app.models.user_model import User
from app.gps_api.utils.auth_api import get_auth_token
from app.gps_api.utils.get_active_rental import get_active_rental_car
from app.gps_api.utils.car_data import send_command_to_terminal

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
                await asyncio.sleep(1800)

        asyncio.create_task(refresh_token())


@Vehicle_Router.get("/get_vehicles")
def get_vehicle_info(db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        # Выбираем только машины со статусом "FREE"
        cars = db.query(Car).filter(Car.status == "FREE").all()

        vehicles_data = [{
            "id": car.id,
            "name": car.name,
            "plate_number": car.plate_number,
            "latitude": car.latitude,
            "longitude": car.longitude,
            "course": car.course,
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
            "status": car.status
        } for car in cars]

        return {"vehicles": vehicles_data}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching vehicles data: {str(e)}")


@Vehicle_Router.get("/search")
def search_vehicles(
        query: str = Query(..., description="Поисковый запрос по названию авто или номеру"),
        db: Session = Depends(get_db)
) -> Dict[str, Any]:
    try:
        # Ищем по имени или номеру и проверяем, что машина свободна по статусу
        cars = db.query(Car).filter(
            or_(
                Car.name.ilike(f"%{query}%"),
                Car.plate_number.ilike(f"%{query}%")
            ),
            Car.status == "FREE"
        ).all()

        vehicles_data = [{
            "id": car.id,
            "name": car.name,
            "plate_number": car.plate_number,
            "latitude": car.latitude,
            "longitude": car.longitude,
            "course": car.course,
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
            "status": car.status
        } for car in cars]

        return {"vehicles": vehicles_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка поиска авто: {str(e)}")


@Vehicle_Router.get("/frequently-used")
def get_frequently_used_vehicles(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    try:
        # Получаем ID машин и количество аренд для текущего пользователя
        rental_counts = (
            db.query(RentalHistory.car_id, func.count(RentalHistory.id).label("rental_count"))
            .filter(RentalHistory.user_id == current_user.id)
            .group_by(RentalHistory.car_id)
            .order_by(func.count(RentalHistory.id).desc())
            .all()
        )

        if not rental_counts:
            raise HTTPException(status_code=404, detail="Вы ещё не арендовали ни одной машины")

        car_ids = [r.car_id for r in rental_counts]

        # Загружаем только свободные машины, проверяя статус
        cars = (
            db.query(Car)
            .filter(
                Car.id.in_(car_ids),
                Car.status == "FREE"
            )
            .all()
        )

        if not cars:
            raise HTTPException(status_code=404, detail="Все часто используемые вами машины сейчас заняты")

        car_dict = {car.id: car for car in cars}

        vehicles_data = []
        for r in rental_counts:
            car = car_dict.get(r.car_id)
            if car:
                vehicles_data.append({
                    "id": car.id,
                    "name": car.name,
                    "plate_number": car.plate_number,
                    "latitude": car.latitude,
                    "longitude": car.longitude,
                    "course": car.course,
                    "fuel_level": car.fuel_level,
                    "price_per_minute": car.price_per_minute,
                    "price_per_hour": car.price_per_hour,
                    "price_per_day": car.price_per_day,
                    "engine_volume": car.engine_volume,
                    "year": car.year,
                    "drive_type": car.drive_type,
                    "photos": car.photos,
                    "owner_id": car.owner_id,
                    "rental_count": r.rental_count
                })

        if not vehicles_data:
            raise HTTPException(status_code=404, detail="Нет свободных машин из тех, что вы часто арендовали")

        return {"vehicles": vehicles_data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


# === КОМАНДЫ GlonassSoft ===

@Vehicle_Router.post("/open")
async def open_vehicle(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Dict:
    car = get_active_rental_car(db, current_user)
    return await send_command_to_terminal(car.gps_id, "*!CEVT 1", AUTH_TOKEN)


@Vehicle_Router.post("/close")
async def close_vehicle(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Dict:
    car = get_active_rental_car(db, current_user)
    return await send_command_to_terminal(car.gps_id, "*!CEVT 2", AUTH_TOKEN)


@Vehicle_Router.post("/give_key")
async def give_key(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Dict:
    car = get_active_rental_car(db, current_user)
    return await send_command_to_terminal(car.gps_id, "*!2Y", AUTH_TOKEN)


@Vehicle_Router.post("/take_key")
async def take_key(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Dict:
    car = get_active_rental_car(db, current_user)
    return await send_command_to_terminal(car.gps_id, "*!2N", AUTH_TOKEN)
# @Vehicle_Router.post("/block")
# async def block_engine(request: CommandRequest) -> Dict:
#     return await send_command_to_terminal(request.vehicle_id, "*!1Y", AUTH_TOKEN)
#
#
# @Vehicle_Router.post("/unblock")
# async def unblock_engine(request: CommandRequest) -> Dict:
#     return await send_command_to_terminal(request.vehicle_id, "*!1N", AUTH_TOKEN)
