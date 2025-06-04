import asyncio
import os

import anyio
import httpx

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from starlette.middleware.cors import CORSMiddleware

from sqlalchemy.orm import Session
from app.auth.router import Auth_router
from app.core.config import logger
from app.dependencies.database.database import get_db
from app.gps_api.router import Vehicle_Router
from app.mechanic.router import MechanicRouter
from app.models.car_model import Car
from app.models.user_model import User, UserRole
from app.rent.router import RentRouter
from app.rent.utils.billing import rental_billing_loop
from app.push.router import router as PushRouter

# === APP ===
app = FastAPI()
scheduler = AsyncIOScheduler()

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


def run_migrations():
    try:
        alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
        command.upgrade(alembic_cfg, "head")
    except Exception as e:
        logger.error(f"Ошибка миграции БД: {e}")


async def get_last_vehicles_data():
    url = "http://195.49.210.50:8666/vehicles/?skip=0&limit=100"
    headers = {"accept": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Ошибка получения данных с GPS-сервера: {e}")
        return []


def _update_vehicle_data_sync(vehicles_data: list, db: Session) -> int:
    updated = 0
    try:
        for vehicle in vehicles_data:
            vehicle_id = str(vehicle["vehicle_id"])
            car = db.query(Car).filter(Car.gps_id == vehicle_id).first()
            if car:
                car.latitude = vehicle["latitude"]
                car.longitude = vehicle["longitude"]
                car.fuel_level = vehicle["fuel_level"]
                car.mileage = vehicle["mileage"]
                updated += 1
        db.commit()
    except Exception as e:
        logger.error(f"Ошибка при обновлении данных машин в БД: {e}")
    return updated


def _update_in_thread(vehicles_data: list) -> int:
    db_gen = get_db()
    db = next(db_gen)
    try:
        return _update_vehicle_data_sync(vehicles_data, db)
    except Exception as e:
        logger.error(f"Ошибка в потоке обновления данных: {e}")
        return 0
    finally:
        db.close()


async def update_vehicle_data():
    vehicles_data = await get_last_vehicles_data()
    if not vehicles_data:
        return

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _update_in_thread, vehicles_data)
    except Exception as e:
        logger.error(f"Ошибка в процессе run_in_executor: {e}")


async def check_vehicle_conditions():
    await update_vehicle_data()


def init_app(app: FastAPI):
    @app.on_event("startup")
    async def startup_event():
        print("🚀 Приложение запущено")
        run_migrations()

        db_gen = get_db()
        db = next(db_gen)
        asyncio.create_task(rental_billing_loop())
        try:
            owner_phone = "77000250400"
            owner = db.query(User).filter(User.phone_number == owner_phone).first()
            if not owner:
                owner = User(phone_number=owner_phone, role=UserRole.FIRST, wallet_balance=0)
                db.add(owner)
                db.commit()
                db.refresh(owner)

            if not db.query(Car).filter(Car.id == 1).first():
                photos_dir = os.path.join(os.path.dirname(__file__), "uploads", "cars", "1")
                # Собираем список URL для доступа через StaticFiles (/uploads/…)
                photos = []
                if os.path.isdir(photos_dir):
                    for fname in sorted(os.listdir(photos_dir)):
                        # Фильтруем только файлы (JPG, PNG и т.п.)
                        if os.path.isfile(os.path.join(photos_dir, fname)):
                            photos.append(f"/uploads/cars/1/{fname}")

                car1 = Car(
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
                    latitude=43.238949,
                    longitude=76.889709,
                    fuel_level=80,
                    owner_id=owner.id,
                    course=90,
                    description="Машина в идеальном состоянии.",
                    photos=photos  # <- вот тут передаём массив путей к фотографиям
                )
                db.add(car1)
                db.commit()

                print("✅ HAVAL F7x (id=1) добавлена")
            else:
                print("ℹ️ HAVAL F7x (id=1) уже существует")

            if not db.query(Car).filter(Car.id == 2).first():
                photos_dir = os.path.join(os.path.dirname(__file__), "uploads", "cars", "2")
                # Собираем список URL для доступа через StaticFiles (/uploads/…)
                photos = []
                if os.path.isdir(photos_dir):
                    for fname in sorted(os.listdir(photos_dir)):
                        # Фильтруем только файлы (JPG, PNG и т.п.)
                        if os.path.isfile(os.path.join(photos_dir, fname)):
                            photos.append(f"/uploads/cars/2/{fname}")

                car2 = Car(
                    id=2,
                    name="MB CLA45s",
                    gps_id="800212421",
                    gps_imei="866011056074131",
                    engine_volume=2.0,
                    year=2019,
                    drive_type=3,
                    price_per_minute=140,
                    price_per_hour=5600,
                    price_per_day=100000,
                    plate_number="666AZV02",
                    latitude=43.224048333333336,
                    longitude=76.96187166666667,
                    fuel_level=40,
                    course=23,
                    owner_id=owner.id,
                    description="Разбита левая передняя фара. Разбит задний правый фонарь. Вмятина и царапина на правой задней двери.",
                    photos=photos  # <- вот тут передаём массив путей к фотографиям
                )
                db.add(car2)
                db.commit()
                print("✅ MB CLA45s (id=2) добавлена")
            else:
                print("ℹ️ MB CLA45s (id=2) уже существует")

            mechanic_phone = "77007007070"
            mechanic = db.query(User).filter(User.phone_number == mechanic_phone).first()
            if not mechanic:
                mechanic = User(phone_number=mechanic_phone, role=UserRole.MECHANIC, wallet_balance=0)
                db.add(mechanic)
                db.commit()
                db.refresh(mechanic)
                print("✅ Механик успешно добавлен")
            else:
                print("ℹ️ Механик уже существует")

        except Exception as e:
            logger.error(f"Ошибка в стартап-инициализации: {e}")
        finally:
            db.close()

        try:
            scheduler.add_job(check_vehicle_conditions, "interval", seconds=1)
            scheduler.start()
        except Exception as e:
            logger.error(f"Ошибка запуска планировщика задач: {e}")

    @app.on_event("shutdown")
    async def shutdown_event():
        print("🛑 Приложение остановлено")
        try:
            scheduler.shutdown()
        except Exception as e:
            logger.error(f"Ошибка остановки планировщика: {e}")


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
app.include_router(MechanicRouter)
app.include_router(PushRouter)


@app.get("/")
async def root(db: Session = Depends(get_db)):
    return {"message": "salam?"}


@app.get("/list_routes")
async def list_routes():
    lines = []
    for route in app.router.routes:
        lines.append(
            f"name={route.name}, path={getattr(route, 'path', '-')}, methods={getattr(route, 'methods', '-')}"
        )
    return {"routes": lines}
