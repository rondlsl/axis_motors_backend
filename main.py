import asyncio
import os
import random

import httpx

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from starlette.middleware.cors import CORSMiddleware

from sqlalchemy.orm import Session
from app.auth.router import Auth_router
from app.dependencies.database.database import get_db
from app.gps_api.router import Vehicle_Router
from app.mechanic.router import MechanicRouter
from app.models.car_model import Car
from app.models.user_model import User, UserRole
from app.rent.router import RentRouter
from app.websocket.router import WebSocketRouter

# === APP ===
app = FastAPI()
scheduler = AsyncIOScheduler()

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


def run_migrations():
    alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
    command.upgrade(alembic_cfg, "head")


def create_premium_cars(db: Session):
    # список премиум-авто, без id=2
    cars = [
        {"id": 3, "name": "Mercedes GLE", "plate": "B728NMK02", "lat": 43.2380, "lon": 76.9200, "year": 2022,
         "engine": 3.0, "drive": 3},
        {"id": 4, "name": "Audi Q7", "plate": "E543ASA02", "lat": 43.2223, "lon": 76.8888, "year": 2021, "engine": 3.0,
         "drive": 3},
        {"id": 5, "name": "Lexus RX", "plate": "M382KNT02", "lat": 43.2300, "lon": 76.8500, "year": 2022, "engine": 2.5,
         "drive": 3},
        {"id": 6, "name": "Porsche Cayenne", "plate": "X159CTB02", "lat": 43.2750, "lon": 76.8900, "year": 2023,
         "engine": 3.0, "drive": 3},
        {"id": 7, "name": "Tesla Model X", "plate": "R007HAA02", "lat": 43.2400, "lon": 76.8700, "year": 2022,
         "engine": 0.0, "drive": 3},
        {"id": 8, "name": "Range Rover", "plate": "Z999TOM02", "lat": 43.2450, "lon": 76.8600, "year": 2023,
         "engine": 4.4, "drive": 3},
        {"id": 9, "name": "Toyota Land Cruiser", "plate": "O405LIA02", "lat": 43.2500, "lon": 76.9050, "year": 2021,
         "engine": 4.5, "drive": 3},
        {"id": 10, "name": "BMW X7", "plate": "T753OOO02", "lat": 43.2480, "lon": 76.8990, "year": 2023, "engine": 4.4,
         "drive": 3},
        {"id": 11, "name": "Mercedes S-Class", "plate": "K111POP02", "lat": 43.2600, "lon": 76.9150, "year": 2022,
         "engine": 3.0, "drive": 1},
        {"id": 12, "name": "Audi A8", "plate": "Y888LOL02", "lat": 43.2280, "lon": 76.9100, "year": 2022, "engine": 3.0,
         "drive": 1},
        {"id": 13, "name": "Lexus LX570", "plate": "G456FMC02", "lat": 43.2390, "lon": 76.9010, "year": 2021,
         "engine": 5.7, "drive": 3},
        {"id": 14, "name": "Cadillac Escalade", "plate": "V202RAY02", "lat": 43.2440, "lon": 76.8950, "year": 2023,
         "engine": 6.2, "drive": 3},
        {"id": 15, "name": "Genesis GV80", "plate": "N373YUP02", "lat": 43.2410, "lon": 76.8800, "year": 2022,
         "engine": 3.5, "drive": 3},
        {"id": 16, "name": "Volvo XC90", "plate": "B001BAA02", "lat": 43.2530, "lon": 76.8890, "year": 2021,
         "engine": 2.0, "drive": 3},
        {"id": 17, "name": "Infiniti QX80", "plate": "H912PWR02", "lat": 43.2465, "lon": 76.8765, "year": 2020,
         "engine": 5.6, "drive": 3},
        {"id": 18, "name": "Toyota Sequoia", "plate": "C313WOW02", "lat": 43.2266, "lon": 76.8688, "year": 2021,
         "engine": 5.7, "drive": 3},
        {"id": 19, "name": "Jeep Grand Cherokee", "plate": "L454YES02", "lat": 43.2511, "lon": 76.8888, "year": 2022,
         "engine": 3.6, "drive": 3},
        {"id": 20, "name": "Hyundai Palisade", "plate": "S808QRT02", "lat": 43.2200, "lon": 76.8840, "year": 2021,
         "engine": 3.8, "drive": 3},
        {"id": 21, "name": "Kia Mohave", "plate": "U555NBK02", "lat": 43.2360, "lon": 76.8990, "year": 2021,
         "engine": 3.0, "drive": 3},
    ]

    for idx, car_data in enumerate(cars):
        if not db.query(Car).filter(Car.id == car_data["id"]).first():
            status = "PENDING" if idx < 2 else "FREE"
            car = Car(
                id=car_data["id"],
                name=car_data["name"],
                gps_id=f"premium-{car_data['id']}",
                gps_imei=f"000000000000{car_data['id']:03}",
                engine_volume=car_data["engine"],
                year=car_data["year"],
                drive_type=car_data["drive"],
                price_per_minute=120,
                price_per_hour=5000,
                price_per_day=75000,
                plate_number=car_data["plate"],
                latitude=car_data["lat"],
                longitude=car_data["lon"],
                fuel_level=100,
                course=random.randint(0, 359),
                owner_id=None,
                status=status,
                description=None  # по умолчанию без описания
            )
            db.add(car)
    db.commit()
    print("Премиум-авто (id=3–21) созданы: 2 в PENDING, остальные в FREE")


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
        print(f"Ошибка при получении данных с GPS-сервера: {e}")
        return

    try:
        loop = asyncio.get_event_loop()
        updated_count = await loop.run_in_executor(None, _update_in_thread, vehicles_data)
    except Exception as e:
        print(f"Ошибка при обновлении данных машин в БД: {e}")


async def check_vehicle_conditions():
    await update_vehicle_data()


def init_app(app: FastAPI):
    @app.on_event("startup")
    async def startup_event():
        print("🚀 Приложение запущено")
        run_migrations()

        db_gen = get_db()
        db = next(db_gen)
        try:
            # 1) Владелец HAVAL F7x
            owner_phone = "77000250400"
            owner = db.query(User).filter(User.phone_number == owner_phone).first()
            if not owner:
                owner = User(
                    phone_number=owner_phone,
                    role=UserRole.FIRST,
                    wallet_balance=0
                )
                db.add(owner)
                db.commit()
                db.refresh(owner)

            # 2) HAVAL F7x (id=1) с описанием
            if not db.query(Car).filter(Car.id == 1).first():
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
                    description="Машина в идеальном состоянии."
                )
                db.add(car1)
                db.commit()
                print("✅ HAVAL F7x (id=1) добавлена")
            else:
                print("ℹ️ HAVAL F7x (id=1) уже существует")

            # 3) MB CLA45s (id=2) вручную
            if not db.query(Car).filter(Car.id == 2).first():
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
                    description="Разбита левая передняя фара. Разбит задний правый фонарь. Вмятина и царапина на правой задней двери."
                )
                db.add(car2)
                db.commit()
                print("✅ MB CLA45s (id=2) добавлена")
            else:
                print("ℹ️ MB CLA45s (id=2) уже существует")

            # Создание механика
            mechanic_phone = "77007007070"
            mechanic = db.query(User).filter(User.phone_number == mechanic_phone).first()
            if not mechanic:
                mechanic = User(
                    phone_number=mechanic_phone,
                    role=UserRole.MECHANIC,
                    wallet_balance=0
                )
                db.add(mechanic)
                db.commit()
                db.refresh(mechanic)
                print("✅ Механик успешно добавлен")
            else:
                print("ℹ️ Механик уже существует")

            # Премиум авто
            create_premium_cars(db)

        finally:
            db.close()

        # scheduler.add_job(check_vehicle_conditions, "interval", seconds=1)
        scheduler.start()

    @app.on_event("shutdown")
    async def shutdown_event():
        print("🛑 Приложение остановлено")
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
app.include_router(MechanicRouter)
app.include_router(WebSocketRouter)


@app.get("/")
def root():
    return {"message": "salam?"}


@app.get("/list_routes")
async def list_routes():
    lines = []
    for route in app.router.routes:
        lines.append(
            f"name={route.name}, path={getattr(route, 'path', '-')}, methods={getattr(route, 'methods', '-')}"
        )
    return {"routes": lines}
