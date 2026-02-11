"""
Middleware для автоматического логирования всех HTTP запросов
Логирует: method, path, status, duration_ms, trace_id, user_id, vehicle_id
"""
import logging
import sys
import time
import traceback
import uuid
from contextvars import ContextVar
from typing import Optional
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging_config import get_logger
from app.auth.security.tokens import verify_token

logger = get_logger(__name__)


def _flush_log_handlers():
    """Принудительно сбросить буфер логгеров (для Docker/K8s, чтобы логи сразу попадали в вывод)."""
    try:
        root = logging.getLogger()
        for h in root.handlers:
            h.flush()
        if hasattr(sys.stdout, "flush"):
            sys.stdout.flush()
    except Exception:
        pass

# Context variable для trace_id - доступен во всем приложении
trace_id_var: ContextVar[Optional[str]] = ContextVar('trace_id', default=None)


def get_trace_id() -> Optional[str]:
    """Получить trace_id из контекста текущего запроса"""
    return trace_id_var.get()


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    """
    Middleware для автоматического логирования всех HTTP запросов
    
    Логирует:
    - method + path
    - status code
    - duration_ms
    - trace_id (для корреляции событий)
    - user_id (если есть токен)
    - vehicle_id/car_id (если есть в path)
    
    Правила:
    - duration_ms > 1000 → WARN
    - exception → ERROR + traceback
    - запросы к путям из LOG_SKIP_PATHS не логируются (шум от частых обновлений)
    """
    # Пути, которые не логируем (method, path без trailing slash)
    LOG_SKIP_PATHS = {("POST", "/device/location")}

    async def dispatch(self, request: Request, call_next):
        # Генерируем trace_id для этого запроса
        trace_id = str(uuid.uuid4())
        trace_id_var.set(trace_id)
        
        # Добавляем trace_id в заголовки ответа для клиента
        start_time = time.time()
        
        # Извлекаем user_id из токена (если есть)
        user_id = None
        try:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
                # verify_token может выбросить HTTPException, ловим все исключения
                try:
                    payload = verify_token(token, expected_token_type="any")
                    if payload:
                        user_id = payload.get("sub")  # phone_number
                except Exception:
                    # Токен невалидный или истек - это нормально, просто не логируем user_id
                    pass
        except Exception:
            pass  # Если не удалось получить user_id, продолжаем без него
        
        # Извлекаем vehicle_id/car_id из path (если есть)
        vehicle_id = self._extract_vehicle_id_from_path(request.url.path)
        
        # Выполняем запрос
        exception_occurred = False
        exception_traceback = None
        status_code = 500
        
        try:
            response = await call_next(request)
            # Получаем status_code безопасно (на случай, если response не имеет этого атрибута)
            status_code = getattr(response, 'status_code', 200)
            
            # Добавляем trace_id в заголовки ответа
            if hasattr(response, 'headers'):
                response.headers["X-Trace-Id"] = trace_id
            
            return response
            
        except Exception as e:
            exception_occurred = True
            exception_traceback = traceback.format_exc()
            status_code = 500
            raise
            
        finally:
            # Вычисляем длительность запроса
            duration_ms = (time.time() - start_time) * 1000
            
            # Не логируем запросы к шумным эндпоинтам (например частые POST /device/location)
            skip_log = (request.method, request.url.path.rstrip("/")) in self.LOG_SKIP_PATHS

            if not skip_log:
                # Формируем данные для логирования
                log_data = {
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "duration_ms": round(duration_ms, 2),
                    "trace_id": trace_id,
                }
                
                # Добавляем опциональные поля
                if user_id:
                    log_data["user_id"] = user_id
                if vehicle_id:
                    log_data["vehicle_id"] = vehicle_id
                
                # Определяем уровень логирования (всегда логируем каждый запрос)
                if exception_occurred:
                    # ERROR для исключений
                    log_message = (
                        f"ERROR {log_data['method']} {log_data['path']} "
                        f"status={log_data['status']} duration_ms={log_data['duration_ms']} "
                        f"trace_id={log_data['trace_id']}"
                    )
                    if user_id:
                        log_message += f" user_id={user_id}"
                    if vehicle_id:
                        log_message += f" vehicle_id={vehicle_id}"
                    
                    logger.error(log_message, extra=log_data)
                    if exception_traceback:
                        logger.error(f"Exception traceback:\n{exception_traceback}")
                        
                elif duration_ms > 1000:
                    # WARN для медленных запросов (> 1 секунда)
                    log_message = (
                        f"WARN {log_data['method']} {log_data['path']} "
                        f"status={log_data['status']} duration_ms={log_data['duration_ms']} "
                        f"trace_id={log_data['trace_id']}"
                    )
                    if user_id:
                        log_message += f" user_id={user_id}"
                    if vehicle_id:
                        log_message += f" vehicle_id={vehicle_id}"
                    
                    logger.warning(log_message, extra=log_data)
                else:
                    # INFO для обычных запросов
                    log_message = (
                        f"{log_data['method']} {log_data['path']} "
                        f"status={log_data['status']} duration_ms={log_data['duration_ms']} "
                        f"trace_id={log_data['trace_id']}"
                    )
                    if user_id:
                        log_message += f" user_id={user_id}"
                    if vehicle_id:
                        log_message += f" vehicle_id={vehicle_id}"
                    
                    logger.info(log_message, extra=log_data)

            # Сброс буфера, чтобы логи сразу попадали в stdout (важно в Docker/K8s)
            _flush_log_handlers()
    
    def _extract_vehicle_id_from_path(self, path: str) -> Optional[str]:
        """
        Извлекает vehicle_id/car_id из path параметров
        
        Примеры путей:
        - /cars/{car_id}/...
        - /admin/cars/{car_id}/details
        - /vehicles/{vehicle_id}/open
        - /mechanic/check-car/{id}
        - /rent/{rent_id}/...
        """
        import re
        
        # Список служебных слов, которые не являются ID
        service_words = {
            'details', 'availability', 'history', 'trips', 'open', 'close',
            'unlock_engine', 'lock_engine', 'give_key', 'take_key', 'telemetry',
            'start', 'cancel', 'complete', 'upload-photos-before', 'upload-photos-after'
        }
        
        # Паттерны для vehicle/car ID в различных форматах (в порядке приоритета)
        patterns = [
            r'/vehicles/([^/]+)',      # /vehicles/{vehicle_id} (высокий приоритет)
            r'/cars/([^/]+)',          # /cars/{car_id} или /admin/cars/{car_id}
            r'/car/([^/]+)',           # /car/{car_id}
            r'/vehicle/([^/]+)',       # /vehicle/{vehicle_id}
            r'/mechanic/check-car/([^/]+)',  # /mechanic/check-car/{id}
            r'/mechanic/start/([^/]+)',      # /mechanic/start/{id}
            r'/rent/([^/]+)',          # /rent/{rent_id} (может быть связан с vehicle)
        ]
        
        for pattern in patterns:
            match = re.search(pattern, path)
            if match:
                vehicle_id = match.group(1)
                # Пропускаем служебные слова
                if vehicle_id not in service_words:
                    # Проверяем, что это похоже на ID (не пустая строка, не только цифры для UUID/short_id)
                    if vehicle_id and len(vehicle_id) > 0:
                        return vehicle_id
        
        return None
