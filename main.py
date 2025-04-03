import asyncio
import httpx
import logging

from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from starlette.middleware.cors import CORSMiddleware

from sqlalchemy.orm import Session
from app.auth.router import Auth_router
from app.dependencies.database.database import get_db
from app.gps_api.router import Vehicle_Router
from app.models.car_model import Car
from app.models.user_model import User, UserRole
from app.rent.router import RentRouter

# === ЛОГИ ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# === APP ===
app = FastAPI()
scheduler = AsyncIOScheduler()


async def get_last_vehicles_data():
    url = "http://195.49.210.50:8666/vehicles/?skip=0&limit=100"
    headers = {"accept": "application/json"}

    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()


def _update_vehicle_data_sync(vehicles_data: list, db: Session) -> int:
    updated = 0
    for vehicle in vehicles_data:
        vehicle_id = str(vehicle["vehicle_id"])
        car = db.query(Car).filter(Car.gps_id == vehicle_id).first()
        if car:
            car.latitude = vehicle["latitude"]
            car.longitude = vehicle["longitude"]
            car.fuel_level = vehicle["fuel_level"]
            updated += 1

    db.commit()
    return updated


def _update_in_thread(vehicles_data: list) -> int:
    db_gen = get_db()
    db = next(db_gen)
    try:
        return _update_vehicle_data_sync(vehicles_data, db)
    finally:
        db.close()


async def update_vehicle_data():
    try:
        vehicles_data = await get_last_vehicles_data()
    except Exception as e:
        logger.error(f"Ошибка при получении данных с GPS-сервера: {e}")
        return

    try:
        loop = asyncio.get_event_loop()
        updated_count = await loop.run_in_executor(None, _update_in_thread, vehicles_data)
    except Exception as e:
        logger.error(f"Ошибка при обновлении данных машин в БД: {e}")


async def check_vehicle_conditions():
    await update_vehicle_data()


def init_app(app: FastAPI):
    @app.on_event("startup")
    async def startup_event():
        logger.info("🚀 Приложение запущено")
        db_gen = get_db()
        db = next(db_gen)
        try:
            # 1. Создать юзера если не существует
            phone_number = "77000250400"
            owner = db.query(User).filter(User.phone_number == phone_number).first()
            if not owner:
                owner = User(
                    phone_number=phone_number,
                    role=UserRole.FIRST,
                    wallet_balance=0
                )
                db.add(owner)
                db.commit()
                db.refresh(owner)
                logger.info("Владелец HAVAL F7x создан")

            # 2. Добавить HAVAL F7x если не существует
            existing_car = db.query(Car).filter(Car.id == 1).first()
            if not existing_car:
                new_car = Car(
                    id=1,
                    name="HAVAL F7x",
                    gps_id="800153076",
                    gps_imei="866011056063951",
                    engine_volume=2.0,
                    year=2021,
                    drive_type=3,
                    price_per_minute=70,
                    price_per_hour=3125,
                    price_per_day=50000,
                    plate_number="422ABK02",
                    owner_id=owner.id  # назначаем владельца
                )
                db.add(new_car)
                db.commit()
                logger.info("Машина HAVAL F7x добавлена в базу данных и привязана к владельцу")
            else:
                logger.info("HAVAL F7x уже существует в базе данных")

        finally:
            db.close()

        scheduler.add_job(check_vehicle_conditions, "interval", seconds=1)
        scheduler.start()

    @app.on_event("shutdown")
    async def shutdown_event():
        logger.info("🛑 Приложение остановлено")
        scheduler.shutdown()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_app(app)
app.include_router(Auth_router)
app.include_router(Vehicle_Router)
app.include_router(RentRouter)


@app.get("/")
def root():
    return {"message": "че надо тут?"}
