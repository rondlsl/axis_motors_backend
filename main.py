from __future__ import annotations

import asyncio
import base64
import os
import faulthandler
import sys
from typing import Dict, Any, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from app.services.telemetry_cache import TelemetryData

import anyio
import httpx

# Включаем faulthandler для получения stack traces при критических ошибках
# Это поможет получить информацию о зависаниях даже если event loop заблокирован
faulthandler.enable()
# Также пишем в stderr для Docker логов
if hasattr(sys.stderr, 'isatty') and sys.stderr.isatty():
    faulthandler.enable(file=sys.stderr, all_threads=True)

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Form, status
from fastapi.responses import ORJSONResponse, Response
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.requests import Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from sqlalchemy.orm import Session
from app.auth.router import Auth_router
from app.core.config import TELEGRAM_BOT_TOKEN_2
from app.core.logging_config import setup_logging, get_logger
from app.dependencies.database.database import get_db
from app.middleware.error_logger_middleware import ErrorLoggerMiddleware
from app.middleware.request_logger_middleware import RequestLoggerMiddleware
from app.middleware.hang_detector_middleware import HangDetectorMiddleware, set_hang_detector_instance
from app.utils.hang_watchdog import HangWatchdog, set_hang_watchdog
import logging

# Инициализация централизованного логирования
setup_logging()
logger = get_logger(__name__)

# Уровень логов apscheduler и остальных задаётся в app.core.logging_config (LOG_LEVEL, LOG_QUIET_LIBRARIES)
from app.gps_api.router import Vehicle_Router
from app.mechanic.router import MechanicRouter
from app.seed.init_data import init_test_data
from app.models.car_model import Car
from app.rent.router import RentRouter
from app.utils.time_utils import get_local_time
from app.rent.utils.billing import billing_job
from app.push.router import router as PushRouter
from app.mechanic_delivery.router import MechanicDeliveryRouter
from app.owner.router import OwnerRouter
from app.owner.availability import update_cars_availability_job, backfill_availability_history
from app.guarantor.router import guarantor_router
from app.admin.router import admin_router
from app.financier.router import FinancierRouter
from app.mvd.router import MvdRouter
from app.accountant.router import accountant_router  
from app.wallet.router import WalletRouter
from app.contracts.router import ContractsRouter
from app.contracts.html_router import HTMLContractsRouter
from app.support.router import router as SupportRouter
from app.support.auth.router import support_auth_router
from app.support.cars.router import support_cars_router
from app.support.users.router import users_router as support_users_router
from app.support.contracts.router import support_contracts_router
from app.support import setup_support_system
from app.monitoring.router import router as MonitoringRouter
from app.websocket.router import websocket_router
from app.app_versions.router import router as AppVersionsRouter
from app.admin.error_logs.router import router as ErrorLogsRouter
from app.device_location.router import router as DeviceLocationRouter

# === APP ===
app = FastAPI(
    title="Azv Motors API",
    swagger_ui_parameters={
        "persistAuthorization": True
    }
)

# === OpenTelemetry Tracing ===
from app.core.telemetry import setup_telemetry
from app.dependencies.database.database import engine
tracer = setup_telemetry(app, engine)

almaty_tz = pytz.FixedOffset(300)  # GMT+5 = 300 минут
scheduler = AsyncIOScheduler(timezone=almaty_tz)

# Файлы теперь хранятся в MinIO (S3)
# URL формат: https://msmain.azvmotors.kz/uploads/...
# StaticFiles mount больше не нужен

# Инициализируем MinIO сервис при старте
from app.services.minio_service import get_minio_service
try:
    _minio = get_minio_service()
    logger.info("MinIO service initialized")
except Exception as e:
    logger.warning("MinIO service initialization warning: %s", e)

# Redis service будет инициализирован в startup_event
from app.services.redis_service import init_redis, shutdown_redis


def run_migrations():
    try:
        alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
        command.upgrade(alembic_cfg, "head")
    except Exception as e:
        logger.error(f"Ошибка миграции БД: {e}")


async def get_last_vehicles_data():
    from app.core.config import VEHICLES_API_URL
    url = f"{VEHICLES_API_URL}/vehicles/?skip=0&limit=100"
    headers = {"accept": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Ошибка получения данных с GPS-сервера: {e}")
        return []


def _update_vehicle_data_sync(
    vehicles_data: list, 
    db: Session, 
    telemetry_cache: dict[str, 'TelemetryData'],
    loop=None
) -> tuple[int, list[tuple[str, float | None, float | None, float | None, float | None, bool]]]:
    """
    Синхронное обновление данных машин с использованием telemetry cache.
    
    Теперь UPDATE в БД происходит только при значимых изменениях:
    - Координаты изменились более чем на 10 метров
    - Топливо изменилось более чем на 0.5 л
    - Пробег увеличился
    - Прошло более 60 секунд с последнего DB update
    
    Args:
        vehicles_data: Данные от GPS API
        db: Сессия БД
        telemetry_cache: Предзагруженный кэш {gps_id: TelemetryData}
        loop: Event loop для async операций
        
    Returns:
        (updated_count, cache_updates) - количество обновлений в БД и список для обновления кэша
    """
    from app.services.telemetry_cache import is_significant_change, TelemetryData, TelemetryStats
    
    updated = 0
    cache_updates: list[tuple[str, float | None, float | None, float | None, float | None, bool]] = []
    
    try:
        for vehicle in vehicles_data:
            vehicle_id = str(vehicle["vehicle_id"])
            car = db.query(Car).filter(Car.gps_id == vehicle_id).first()
            if not car:
                continue
            
            lat = vehicle.get("latitude")
            lon = vehicle.get("longitude")
            fuel = vehicle.get("fuel_level")
            mileage = vehicle.get("mileage")
            
            # Получаем cached данные
            cached = telemetry_cache.get(vehicle_id, TelemetryData())
            
            # Проверяем, нужно ли обновлять БД
            should_update, reason = is_significant_change(
                cached, lat, lon, fuel, mileage
            )
            
            # Записываем статистику
            TelemetryStats.record_update(should_update)
            
            if should_update:
                # Значимое изменение - обновляем БД
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
                    car.updated_at = get_local_time()
                
                # Обновляем fuel_level
                if fuel is not None and fuel != 0 and fuel != 0.0:
                    old_fuel = car.fuel_level
                    # Обнаружение заправки
                    if old_fuel is not None and old_fuel > 0 and fuel > old_fuel:
                        fuel_increase = fuel - old_fuel
                        fuel_increase_percent = (fuel_increase / old_fuel) * 100
                        
                        if fuel_increase_percent > 10:
                            from app.gps_api.utils.get_active_rental import get_active_rental_by_car_id
                            from app.models.user_model import User
                            from app.push.utils import send_localized_notification_to_user_async, get_global_push_notification_semaphore
                            try:
                                rental = get_active_rental_by_car_id(db, car.id)
                                if rental:
                                    user = db.query(User).filter(User.id == rental.user_id).first()
                                    if user and loop:
                                        push_semaphore = get_global_push_notification_semaphore()
                                        
                                        async def _send_fuel_notification():
                                            async with push_semaphore:
                                                try:
                                                    await send_localized_notification_to_user_async(
                                                        user.id,
                                                        "fuel_refill_detected",
                                                        "fuel_refill_detected"
                                                    )
                                                except Exception as e:
                                                    logger.error(f"Ошибка отправки уведомления о заправке пользователю {user.id}: {e}")
                                        
                                        asyncio.run_coroutine_threadsafe(_send_fuel_notification(), loop)
                            except Exception:
                                pass
                    
                    car.fuel_level = fuel
                
                # Обновляем пробег
                if mileage is not None:
                    car.mileage = mileage
                
                updated += 1
                logger.debug(f"DB update for {vehicle_id}: {reason}")
            
            # Добавляем в список для обновления кэша (независимо от DB update)
            cache_updates.append((vehicle_id, lat, lon, fuel, mileage, should_update))
        
        if updated > 0:
            db.commit()
            
    except Exception as e:
        logger.error(f"Ошибка при обновлении данных машин в БД: {e}")
        db.rollback()
    
    return updated, cache_updates


def _update_in_thread(
    vehicles_data: list, 
    telemetry_cache: dict[str, 'TelemetryData'],
    loop=None
) -> tuple[int, list[tuple[str, float | None, float | None, float | None, float | None, bool]]]:
    """Thread-safe обёртка для обновления данных машин."""
    db_gen = get_db()
    db = next(db_gen)
    try:
        return _update_vehicle_data_sync(vehicles_data, db, telemetry_cache, loop)
    except Exception as e:
        logger.error(f"Ошибка в потоке обновления данных: {e}")
        return 0, []
    finally:
        db.close()


async def update_vehicle_data():
    """
    Основная функция обновления данных машин с GPS.
    
    Оптимизирована с использованием Redis telemetry cache:
    1. Загружаем кэш телеметрии из Redis
    2. Выполняем синхронную обработку в thread pool
    3. Сохраняем обновлённый кэш в Redis
    4. UPDATE в БД только при значимых изменениях
    """
    from app.services.telemetry_cache import (
        load_telemetry_batch, 
        save_telemetry_batch,
        TelemetryStats
    )
    
    vehicles_data = await get_last_vehicles_data()
    if not vehicles_data:
        return

    try:
        # Шаг 1: Получаем список gps_id и загружаем кэш из Redis
        gps_ids = [str(v["vehicle_id"]) for v in vehicles_data]
        telemetry_cache = await load_telemetry_batch(gps_ids)
        
        # Шаг 2: Обработка в thread pool с переданным кэшем
        loop = asyncio.get_event_loop()
        updated, cache_updates = await loop.run_in_executor(
            None, 
            _update_in_thread, 
            vehicles_data, 
            telemetry_cache,
            loop
        )
        
        # Шаг 3: Сохраняем обновлённый кэш в Redis
        if cache_updates:
            await save_telemetry_batch(cache_updates)
        
        # Шаг 4: Уведомляем WebSocket клиентов (только если были DB updates)
        if updated > 0:
            from app.websocket.notifications import notify_vehicles_list_update
            asyncio.create_task(notify_vehicles_list_update())
        
        # Логируем статистику периодически (каждые 100 обновлений)
        stats = TelemetryStats.get_stats()
        if stats["total_updates"] > 0 and stats["total_updates"] % 100 == 0:
            logger.info(
                f"Telemetry cache stats: {stats['db_updates']}/{stats['total_updates']} DB updates "
                f"({stats['db_reduction_percent']}% reduction)"
            )
            
    except Exception as e:
        logger.error(f"Ошибка в процессе обновления данных машин: {e}")


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
        logger.info("Приложение запущено")
        # run_migrations()  # авто миграция отключена; запускать вручную: alembic upgrade head
        logger.info("Авто миграция отключена (для применения миграций: alembic upgrade head)")

        # Инициализируем Redis
        try:
            redis_available = await init_redis()
            if redis_available:
                logger.info("Redis service initialized")
            else:
                logger.warning("Redis unavailable, using database fallback")
        except Exception as e:
            logger.warning("Redis initialization error: %s", e)

        # Инициализируем WebSocket Pub/Sub для кластерного режима
        try:
            from app.websocket.manager import connection_manager
            pubsub_ready = await connection_manager.init_pubsub()
            if pubsub_ready:
                logger.info("WebSocket Pub/Sub initialized for cluster mode")
            else:
                logger.info("WebSocket running in single-instance mode")
        except Exception as e:
            logger.warning("WebSocket Pub/Sub initialization error: %s", e)

        db_gen = get_db()
        db = next(db_gen)
        scheduler.add_job(
            billing_job,
            trigger="interval",
            seconds=60,  # Запуск каждую минуту (оптимально для поминутного биллинга)
            max_instances=1,  # не запустит новую итерацию, пока старая не завершилась
            coalesce=True  # если промедлили — слить «пропущенные» вызовы в один
        )
        # scheduler.start() будет вызван ниже после добавления всех задач

        # try:
        #     # Инициализируем тестовые данные
        #     init_test_data(db)
        # except Exception as e:
        #     print(e)
        #     logger.error(f"Ошибка в стартап-инициализации: {e}")
        # finally:
        #     db.close()

        try:
            backfill_availability_history()
        except Exception as e:
            logger.error(f"Ошибка backfill availability history: {e}")

        try:

            scheduler.add_job(
                check_vehicle_conditions,
                "interval",
                seconds=1,
                coalesce=True 
            )
            scheduler.add_job(
                auto_close_support_chats,
                "interval",
                hours=1,
                max_instances=1,
                coalesce=True
            )  
            scheduler.add_job(
                update_cars_availability_job,
                "interval",
                minutes=1,
                id="update_car_availability",
                max_instances=1,  
                coalesce=True,  
            )
            
            # Маркетинговые уведомления
            from app.scheduler.marketing_notifications import (
                check_birthdays,
                check_holidays,
                check_weekend_promotions,
                check_new_cars
            )
            
            # Проверка дней рождения - каждый день в 9:00
            scheduler.add_job(
                check_birthdays,
                trigger="cron",
                hour=9,
                minute=0,
                id="check_birthdays"
            )
            
            # Проверка праздников - каждый день в 8:00
            scheduler.add_job(
                check_holidays,
                trigger="cron",
                hour=8,
                minute=0,
                id="check_holidays"
            )
            
            # Пятница вечер 19:00 по Алматы (GMT+5)
            scheduler.add_job(
                check_weekend_promotions,
                trigger="cron",
                day_of_week="fri",
                hour=19,
                minute=0,
                id="check_friday_evening"
            )
            
            # Понедельник утро 8:00 по Алматы (GMT+5)
            scheduler.add_job(
                check_weekend_promotions,
                trigger="cron",
                day_of_week="mon",
                hour=8,
                minute=0,
                id="check_monday_morning"
            )
            
            # Проверка новых автомобилей - каждый час по Алматы (GMT+5)
            scheduler.add_job(
                check_new_cars,
                trigger="cron",
                minute=0,
                id="check_new_cars"
            )
            scheduler.start()
            logger.info("Планировщик задач запущен")
        except Exception as e:
            logger.error(f"Ошибка запуска планировщика задач: {e}")
        
        # Запускаем систему поддержки (бот в фоне)
        try:
            from app.dependencies.database.database import SessionLocal
            start_support_task = setup_support_system(app, SessionLocal)
            await start_support_task()
            logger.info("Система поддержки запущена успешно")
        except Exception as e:
            logger.error(f"Ошибка запуска системы поддержки: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
        
        # Запускаем HangWatchdog для детектирования зависаний
        try:
            # Настройки можно вынести в переменные окружения
            import os
            check_interval = float(os.getenv("HANG_WATCHDOG_CHECK_INTERVAL", "5.0"))  # Проверка каждые 5 секунд
            hang_threshold = float(os.getenv("HANG_WATCHDOG_THRESHOLD", "10.0"))  # Порог зависания 10 секунд
            
            hang_watchdog = HangWatchdog(
                check_interval=check_interval,
                hang_threshold=hang_threshold
            )
            set_hang_watchdog(hang_watchdog)
            await hang_watchdog.start()
            logger.info("✅ HangWatchdog запущен для детектирования зависаний")
        except Exception as e:
            logger.error(f"❌ Ошибка запуска HangWatchdog: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        # В самом конце startup — восстанавливаем логирование (бот/библиотеки могли его менять).
        # Все логи в stdout; приглушён только APScheduler в logging_config.
        try:
            from app.core.logging_config import setup_logging
            setup_logging()
            logger.info("Логирование применено (все логи в stdout)")
        except Exception as e:
            logger.error(f"Ошибка применения логирования: {e}")

    @app.on_event("shutdown")
    async def shutdown_event():
        logger.info("Приложение остановлено")

        # Останавливаем HangWatchdog
        try:
            from app.utils.hang_watchdog import get_hang_watchdog
            hang_watchdog = get_hang_watchdog()
            if hang_watchdog:
                await hang_watchdog.stop()
        except Exception as e:
            logger.error(f"Ошибка остановки HangWatchdog: {e}")

        # Останавливаем WebSocket Pub/Sub
        try:
            from app.websocket.manager import connection_manager
            await connection_manager.shutdown_pubsub()
        except Exception as e:
            logger.error(f"Ошибка остановки WebSocket Pub/Sub: {e}")

        # Закрываем Redis
        try:
            await shutdown_redis()
        except Exception as e:
            logger.error(f"Ошибка остановки Redis: {e}")

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


from app.middleware.performance_monitor import PerformanceMonitoringMiddleware

# Порядок важен: middleware выполняются в обратном порядке добавления
# (последний добавленный выполняется первым)

# CORS должен быть самым внешним (добавляем последним)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# RequestLoggerMiddleware - логирует все запросы (добавляем перед CORS)
app.add_middleware(RequestLoggerMiddleware)

# HangDetectorMiddleware - отслеживает активные запросы для детектирования зависаний
# Должен быть после RequestLoggerMiddleware, чтобы иметь доступ к trace_id
# Middleware автоматически сохранит ссылку на себя при инициализации
app.add_middleware(HangDetectorMiddleware)

# ErrorLoggerMiddleware - обрабатывает ошибки
app.add_middleware(ErrorLoggerMiddleware)

# SwaggerAuthMiddleware - защита Swagger UI
app.add_middleware(SwaggerAuthMiddleware)

# PerformanceMonitoringMiddleware - мониторинг производительности
app.add_middleware(PerformanceMonitoringMiddleware, slow_threshold=3.0, alert_threshold=10.0)

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
app.include_router(accountant_router)
app.include_router(support_auth_router, prefix="/support/auth")
app.include_router(support_cars_router, prefix="/support/cars")
app.include_router(support_users_router, prefix="/support/users")
app.include_router(WalletRouter)
app.include_router(ContractsRouter)
app.include_router(support_contracts_router, prefix="/support/contracts")
app.include_router(HTMLContractsRouter)
app.include_router(SupportRouter)
app.include_router(MonitoringRouter)
app.include_router(websocket_router)
app.include_router(AppVersionsRouter)
app.include_router(ErrorLogsRouter, prefix="/admin")
app.include_router(DeviceLocationRouter)

@app.get("/")
async def root(db: Session = Depends(get_db)):
    return {"message": "salam?"}


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "service": "azv_motors_backend"
    }


@app.get("/health/cars")
async def health_check_cars():
    """Check if cars service is healthy and send alert if down"""
    from app.core.config import VEHICLES_API_URL
    cars_url = f"{VEHICLES_API_URL}/health"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(cars_url)
            response.raise_for_status()
            data = response.json()
            return {
                "status": "ok",
                "cars_service": data,
                "checked_at": datetime.now().isoformat()
            }
    except Exception as e:
        # Send Telegram alert
        try:
            alert_message = f"🚨 <b>Cars Service is DOWN!</b>\n\nError: {str(e)}\nURL: {cars_url}\nTime: {datetime.now().isoformat()}"
            await send_telegram_message(alert_message, TELEGRAM_BOT_TOKEN_2)  # pyright: ignore[reportUndefinedVariable]
        except:
            pass
        
        raise HTTPException(
            status_code=503,
            detail=f"Cars service is unavailable: {str(e)}"
        )



@app.get("/test-websocket")
async def test_websocket():
    """Проверка доступности WebSocket эндпоинтов"""
    websocket_routes = []
    for route in app.router.routes:
        route_type = type(route).__name__
        if 'websocket' in route_type.lower() or 'websocket' in route.name.lower():
            websocket_routes.append({
                "path": getattr(route, 'path', '-'),
                "name": route.name
            })
    return {
        "websocket_endpoints_found": len(websocket_routes),
        "endpoints": websocket_routes,
        "note": "Если endpoints найдены, но подключение не работает - проблема в nginx конфигурации"
    }


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
