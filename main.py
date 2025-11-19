import asyncio
import base64
import os
from typing import Dict, Any
from datetime import datetime

import anyio
import httpx

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Form, status
from fastapi.responses import ORJSONResponse, Response
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.requests import Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from sqlalchemy.orm import Session
from app.auth.router import Auth_router
from app.core.config import logger, TELEGRAM_BOT_TOKEN_2
from app.dependencies.database.database import get_db
from app.middleware.error_logger_middleware import ErrorLoggerMiddleware
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
from app.seed.init_data import init_test_data
from app.models.car_model import Car
from app.rent.router import RentRouter
from app.rent.utils.billing import billing_job
from app.push.router import router as PushRouter
from app.mechanic_delivery.router import MechanicDeliveryRouter
from app.owner.router import OwnerRouter
from app.guarantor.router import guarantor_router
from app.admin.router import admin_router
from app.financier.router import FinancierRouter
from app.mvd.router import MvdRouter  
from app.wallet.router import WalletRouter
from app.contracts.router import ContractsRouter
from app.support.router import router as SupportRouter
from app.support import setup_support_system
from app.monitoring.router import router as MonitoringRouter
from app.websocket.router import websocket_router

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


def run_migrations():
    try:
        alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
        command.upgrade(alembic_cfg, "head")
    except Exception as e:
        logger.error(f"Ошибка миграции БД: {e}")


async def get_last_vehicles_data():
    url = "http://195.93.152.69:8667/vehicles/?skip=0&limit=100"
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
                lat = vehicle.get("latitude")
                lon = vehicle.get("longitude")
                coordinates_updated = False
                if lat is not None and lon is not None:
                    if lat != 0.0 or lon != 0.0:
                        car.latitude = lat
                        car.longitude = lon
                        coordinates_updated = True
                elif lat is not None and lat != 0.0:
                    car.latitude = lat
                    coordinates_updated = True
                elif lon is not None and lon != 0.0:
                    car.longitude = lon
                    coordinates_updated = True
                
                if coordinates_updated:
                    car.updated_at = datetime.utcnow()
                
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
        updated = await loop.run_in_executor(None, _update_in_thread, vehicles_data)
        
        if updated > 0:
            from app.websocket.notifications import notify_vehicles_list_update
            asyncio.create_task(notify_vehicles_list_update())
    except Exception as e:
        logger.error(f"Ошибка в процессе run_in_executor: {e}")


async def check_vehicle_conditions():
    await update_vehicle_data()


def _auto_close_support_chats_sync() -> int:
    """Синхронная функция для автоматического закрытия чатов поддержки"""
    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.services.support_service import SupportService
        support_service = SupportService(db)
        return support_service.auto_close_resolved_chats(hours_threshold=12)
    except Exception as e:
        logger.error(f"Ошибка при автоматическом закрытии чатов: {e}")
        return 0
    finally:
        db.close()


async def auto_close_support_chats():
    """Автоматически закрыть чаты поддержки в статусе resolved"""
    try:
        loop = asyncio.get_event_loop()
        closed_count = await loop.run_in_executor(None, _auto_close_support_chats_sync)
        if closed_count > 0:
            logger.info(f"Автоматически закрыто {closed_count} чатов поддержки")
    except Exception as e:
        logger.error(f"Ошибка в процессе автоматического закрытия чатов: {e}")


def init_app(app: FastAPI):
    @app.on_event("startup")
    async def startup_event():
        print("Приложение запущено")
        print("Проверка")
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
            # Инициализируем тестовые данные
            init_test_data(db)
        except Exception as e:
            print(e)
            logger.error(f"Ошибка в стартап-инициализации: {e}")
        finally:
            db.close()

        try:
            scheduler.add_job(check_vehicle_conditions, "interval", seconds=1)
            scheduler.add_job(auto_close_support_chats, "interval", hours=1)  # Каждый час проверяем чаты
            scheduler.start()
            logger.info("Планировщик задач запущен")
        except Exception as e:
            logger.error(f"Ошибка запуска планировщика задач: {e}")
        
        # Запускаем систему поддержки
        try:
            from app.dependencies.database.database import SessionLocal
            start_support_task = setup_support_system(app, SessionLocal)
            await start_support_task()
            print("Система поддержки запущена успешно")
        except Exception as e:
            print(f"Ошибка запуска системы поддержки: {e}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")

    @app.on_event("shutdown")
    async def shutdown_event():
        print("Приложение остановлено")
        try:
            scheduler.shutdown()
        except Exception as e:
            logger.error(f"Ошибка остановки планировщика: {e}")


# Настройка пароля для Swagger UI
SWAGGER_USERNAME = os.getenv("SWAGGER_USERNAME", "azv_admin")
SWAGGER_PASSWORD = os.getenv("SWAGGER_PASSWORD", "dev789456")

# HTTP Basic для защиты Swagger
swagger_security = HTTPBasic()

def verify_swagger_credentials(credentials: HTTPBasicCredentials):
    """Проверка credentials для доступа к Swagger UI"""
    correct_username = credentials.username == SWAGGER_USERNAME
    correct_password = credentials.password == SWAGGER_PASSWORD
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

class SwaggerAuthMiddleware(BaseHTTPMiddleware):
    """Middleware для защиты Swagger UI паролем"""
    async def dispatch(self, request: Request, call_next):
        # Проверяем, является ли запрос к Swagger документации
        if request.url.path.startswith("/docs") or request.url.path.startswith("/redoc") or request.url.path.startswith("/openapi.json"):
            # Проверяем наличие авторизации
            authorization = request.headers.get("Authorization")
            if not authorization or not authorization.startswith("Basic "):
                return Response(
                    content="Unauthorized",
                    status_code=401,
                    headers={"WWW-Authenticate": "Basic realm=\"Swagger UI\""},
                    media_type="text/plain"
                )
            
            # Декодируем Basic Auth
            try:
                import base64
                encoded = authorization.split(" ")[1]
                decoded = base64.b64decode(encoded).decode("utf-8")
                username, password = decoded.split(":", 1)
                
                # Проверяем credentials
                if username != SWAGGER_USERNAME or password != SWAGGER_PASSWORD:
                    return Response(
                        content="Unauthorized",
                        status_code=401,
                        headers={"WWW-Authenticate": "Basic realm=\"Swagger UI\""},
                        media_type="text/plain"
                    )
            except Exception:
                return Response(
                    content="Unauthorized",
                    status_code=401,
                    headers={"WWW-Authenticate": "Basic realm=\"Swagger UI\""},
                    media_type="text/plain"
                )
        
        response = await call_next(request)
        return response

app.add_middleware(SwaggerAuthMiddleware)
app.add_middleware(ErrorLoggerMiddleware)
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
app.include_router(MvdRouter) 
app.include_router(WalletRouter)
app.include_router(ContractsRouter)
app.include_router(SupportRouter)
app.include_router(MonitoringRouter)
app.include_router(websocket_router)

@app.get("/")
async def root(db: Session = Depends(get_db)):
    return {"message": "salam?"}


@app.get("/list_routes")
async def list_routes():
    lines = []
    websocket_routes = []
    for route in app.router.routes:
        # Проверяем, является ли роут WebSocket
        is_websocket = hasattr(route, 'endpoint') and 'websocket' in route.name.lower()
        if not is_websocket:
            # Проверяем по типу роута
            route_type = type(route).__name__
            is_websocket = 'websocket' in route_type.lower()
        
        route_info = {
            "name": route.name,
            "path": getattr(route, 'path', '-'),
            "methods": getattr(route, 'methods', '-') if hasattr(route, 'methods') else 'WEBSOCKET',
            "type": "websocket" if is_websocket else "http"
        }
        lines.append(
            f"name={route_info['name']}, path={route_info['path']}, methods={route_info['methods']}, type={route_info['type']}"
        )
        if route_info['type'] == 'websocket':
            websocket_routes.append({
                "path": route_info['path'],
                "name": route_info['name']
            })
    return {
        "routes": lines,
        "websocket_endpoints": websocket_routes,
        "websocket_count": len(websocket_routes),
        "note": "WebSocket endpoints are not visible in Swagger UI. Use /list_routes to see them."
    }

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
