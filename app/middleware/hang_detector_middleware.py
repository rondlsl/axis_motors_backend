"""
Middleware для отслеживания активных запросов и детектирования зависаний
"""
import time
import threading
from typing import Dict, Optional
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging_config import get_logger
logger = get_logger(__name__)
from app.middleware.request_logger_middleware import get_trace_id


class ActiveRequest:
    """Информация об активном запросе"""
    def __init__(self, method: str, path: str, start_time: float, trace_id: Optional[str] = None):
        self.method = method
        self.path = path
        self.start_time = start_time
        self.trace_id = trace_id
        self.duration_ms = 0.0
    
    def update_duration(self):
        """Обновить длительность запроса"""
        self.duration_ms = (time.time() - self.start_time) * 1000


class HangDetectorMiddleware(BaseHTTPMiddleware):
    """
    Middleware для отслеживания активных запросов
    
    Сохраняет информацию о каждом активном запросе в глобальном словаре,
    который проверяется watchdog таском на предмет зависаний.
    """
    
    def __init__(self, app):
        super().__init__(app)
        # Глобальный словарь активных запросов: {request_id: ActiveRequest}
        # Используем threading.Lock для thread-safety
        self._active_requests: Dict[str, ActiveRequest] = {}
        self._lock = threading.Lock()
        
        # Сохраняем ссылку на себя в глобальной переменной при инициализации
        set_hang_detector_instance(self)
    
    def register_request(self, request_id: str, request: Request) -> None:
        """Зарегистрировать активный запрос"""
        trace_id = get_trace_id()
        active_request = ActiveRequest(
            method=request.method,
            path=str(request.url.path),
            start_time=time.time(),
            trace_id=trace_id
        )
        
        with self._lock:
            self._active_requests[request_id] = active_request
    
    def unregister_request(self, request_id: str) -> None:
        """Удалить запрос из активных"""
        with self._lock:
            self._active_requests.pop(request_id, None)
    
    def get_active_requests(self) -> Dict[str, ActiveRequest]:
        """Получить копию словаря активных запросов"""
        with self._lock:
            # Возвращаем копию, чтобы избежать проблем с concurrent access
            return {req_id: req for req_id, req in self._active_requests.items()}
    
    def get_hanging_requests(self, threshold_seconds: float) -> Dict[str, ActiveRequest]:
        """
        Получить список зависших запросов (дольше threshold_seconds)
        
        Args:
            threshold_seconds: Порог в секундах, после которого запрос считается зависшим
            
        Returns:
            Словарь зависших запросов: {request_id: ActiveRequest}
        """
        current_time = time.time()
        hanging = {}
        
        with self._lock:
            for request_id, active_request in self._active_requests.items():
                active_request.update_duration()
                duration_seconds = active_request.duration_ms / 1000.0
                
                if duration_seconds >= threshold_seconds:
                    hanging[request_id] = active_request
        
        return hanging
    
    async def dispatch(self, request: Request, call_next):
        # Генерируем уникальный ID для этого запроса
        import uuid
        request_id = str(uuid.uuid4())
        
        # Регистрируем запрос
        self.register_request(request_id, request)
        
        try:
            # Выполняем запрос
            response = await call_next(request)
            return response
        finally:
            # Удаляем запрос из активных (даже если произошла ошибка)
            self.unregister_request(request_id)


# Глобальный экземпляр middleware (будет установлен при инициализации)
_hang_detector_instance: Optional[HangDetectorMiddleware] = None


def set_hang_detector_instance(instance: HangDetectorMiddleware) -> None:
    """Установить глобальный экземпляр HangDetectorMiddleware"""
    global _hang_detector_instance
    _hang_detector_instance = instance


def get_hang_detector_instance() -> Optional[HangDetectorMiddleware]:
    """Получить глобальный экземпляр HangDetectorMiddleware"""
    return _hang_detector_instance
