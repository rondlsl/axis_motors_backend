import asyncio
import base64
import os
from typing import Dict, Any

import anyio
import httpx

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Form
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from starlette.middleware.cors import CORSMiddleware
from fastapi.requests import Request

from sqlalchemy.orm import Session
from app.auth.router import Auth_router
from app.core.config import logger
from app.dependencies.database.database import get_db
import logging

# Настройка логирования для вывода в консоль Docker
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
from app.gps_api.router import Vehicle_Router
from app.mechanic.router import MechanicRouter
from app.models.car_model import Car, CarBodyType
from app.models.user_model import User, UserRole
from app.rent.router import RentRouter
from app.rent.utils.billing import billing_job
from app.push.router import router as PushRouter
from app.mechanic_delivery.router import MechanicDeliveryRouter
from app.owner.router import OwnerRouter
from app.guarantor.router import guarantor_router
from app.admin.router import admin_router
from app.financier.router import FinancierRouter
# from app.mvd.router import MvdRouter  

# === APP ===
app = FastAPI(
    title="Azv Motors API",
    swagger_ui_parameters={
        "persistAuthorization": True
    }
)
scheduler = AsyncIOScheduler()

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Создаем папку contracts если не существует
import os
os.makedirs("contracts", exist_ok=True)
app.mount("/contracts", StaticFiles(directory="contracts"), name="contracts")


def run_migrations():
    try:
        alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
        command.upgrade(alembic_cfg, "head")
    except Exception as e:
        logger.error(f"Ошибка миграции БД: {e}")


async def get_last_vehicles_data():
    url = "http://195.93.152.69:8666/vehicles/?skip=0&limit=100"
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
                # Обновляем координаты всегда
                if vehicle.get("latitude") is not None:
                    car.latitude = vehicle["latitude"]
                if vehicle.get("longitude") is not None:
                    car.longitude = vehicle["longitude"]
                
                # Обновляем fuel_level, если пришло валидное значение (не null и не 0)
                fuel = vehicle.get("fuel_level")
                if fuel is not None and fuel != 0 and fuel != 0.0:
                    car.fuel_level = fuel
                
                # Обновляем пробег всегда
                if vehicle.get("mileage") is not None:
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
        scheduler.add_job(
            billing_job,
            trigger="interval",
            seconds=10,
            max_instances=1,  # не запустит новую итерацию, пока старая не завершилась
            coalesce=True  # если промедлили — слить «пропущенные» вызовы в один
        )
        scheduler.start()

        try:
            owner_phone = "77000250400"
            owner = db.query(User).filter(User.phone_number == owner_phone).first()
            if not owner:
                owner = User(phone_number=owner_phone, role=UserRole.CLIENT, wallet_balance=0)
                db.add(owner)
                db.commit()
                db.refresh(owner)

            if not db.query(Car).filter(Car.id == 1).first():
                photos_dir = os.path.join(os.path.dirname(__file__), "uploads", "cars", "1")
                photos = []
                if os.path.isdir(photos_dir):
                    for fname in sorted(os.listdir(photos_dir)):
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
                    body_type=CarBodyType.CROSSOVER,
                    owner_id=owner.id,
                    course=90,
                    description="Машина в идеальном состоянии.",
                    photos=photos
                )
                db.add(car1)
                db.commit()
                print("✅ HAVAL F7x (id=1) добавлена")
            else:
                print("ℹ️ HAVAL F7x (id=1) уже существует")

            if not db.query(Car).filter(Car.id == 2).first():
                photos_dir = os.path.join(os.path.dirname(__file__), "uploads", "cars", "2")
                photos = []
                if os.path.isdir(photos_dir):
                    for fname in sorted(os.listdir(photos_dir)):
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
                    latitude=43.224048,
                    longitude=76.961871,
                    fuel_level=40,
                    course=23,
                    body_type=CarBodyType.SEDAN,
                    owner_id=owner.id,
                    description="Разбита левая передняя фара. Разбит задний правый фонарь. Вмятина и царапина на правой задней двери.",
                    photos=photos
                )
                db.add(car2)
                db.commit()
                print("✅ MB CLA45s (id=2) добавлена")
            else:
                print("ℹ️ MB CLA45s (id=2) уже существует")

            if not db.query(Car).filter(Car.id == 3).first():
                photos_dir = os.path.join(os.path.dirname(__file__), "uploads", "cars", "3")
                photos = []
                if os.path.isdir(photos_dir):
                    for fname in sorted(os.listdir(photos_dir)):
                        if os.path.isfile(os.path.join(photos_dir, fname)):
                            photos.append(f"/uploads/cars/3/{fname}")

                car3 = Car(
                    id=3,
                    name="Hongqi e-qm5",
                    gps_id="800283232",
                    gps_imei="869132074464026",
                    price_per_minute=70,
                    price_per_hour=3125,
                    price_per_day=50000,
                    plate_number="890AVB09",
                    body_type=CarBodyType.SEDAN,
                    owner_id=owner.id,
                    photos=photos
                )
                db.add(car3)
                db.commit()
                print("✅ Hongqi e-qm5 (id=3) добавлена")
            else:
                print("ℹ️ Hongqi e-qm5 (id=3) уже существует")

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
            print(e)
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

async def log_exception_handler(request: Request, exc: Exception):
	logger.exception(f"Unhandled exception at {request.url}: {exc}")
	# Показ подробной ошибки по запросу через переменную окружения
	try:
		show_errors = os.getenv("DEBUG_API_ERRORS", "0") == "1"
		if show_errors:
			import traceback
			return ORJSONResponse(
				status_code=500,
				content={
					"detail": str(exc),
					"traceback": traceback.format_exc(),
				}
			)
	except Exception:
		pass
	return ORJSONResponse(status_code=500, content={"detail": "Internal Server Error"})


app.add_exception_handler(Exception, log_exception_handler)

init_app(app)
app.include_router(Auth_router)
app.include_router(Vehicle_Router)
app.include_router(RentRouter)
app.include_router(MechanicRouter)
app.include_router(MechanicDeliveryRouter)
app.include_router(PushRouter)
app.include_router(OwnerRouter)
app.include_router(guarantor_router)
app.include_router(admin_router)
app.include_router(FinancierRouter)
# app.include_router(MvdRouter) 


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

#
# # Ваш SubscriptionKey (можно передать через переменную окружения)
# SUBSCRIPTION_KEY = os.getenv("MXFACE_SUBSCRIPTION_KEY", "HI1vTRQH4NXCfOXevz-6eOxARymKc4200")
# CHECK_URL = "https://faceapi.mxface.ai/api/v3/face/liveness"
# VERIFY_URL = "https://faceapi.mxface.ai/api/v3/face/verify"
# HEADERS = {
#     "Content-Type": "application/json",
#     "subscriptionkey": SUBSCRIPTION_KEY
# }
#
#
# async def _call_mxface(url: str, payload: dict) -> dict:
#     async with httpx.AsyncClient(timeout=20) as client:
#         resp = await client.post(url, json=payload, headers=HEADERS)
#         resp.raise_for_status()
#         return resp.json()
#
#
# @app.post("/face/liveness-passive/")
# async def liveness_passive(photo: UploadFile = File(..., description="Фото для проверки liveness")):
#     data = await photo.read()
#     encoded = base64.b64encode(data).decode("utf-8")
#     return await _call_mxface(CHECK_URL, {"encoded_image": encoded})
#
#
# @app.post("/face/compare-faces/")
# async def compare_faces(
#         file1: UploadFile = File(..., description="Первое фото"),
#         file2: UploadFile = File(..., description="Второе фото")
# ):
#     b1, b2 = await file1.read(), await file2.read()
#     payload = {
#         "encoded_image1": base64.b64encode(b1).decode("utf-8"),
#         "encoded_image2": base64.b64encode(b2).decode("utf-8"),
#         "compareAllFaces": False
#     }
#     return await _call_mxface(VERIFY_URL, payload)
