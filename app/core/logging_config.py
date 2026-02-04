"""
Централизованная конфигурация логирования для AZV Motors Backend.

Использование:
    from app.core.logging_config import get_logger
    logger = get_logger(__name__)
    
    logger.info("Пользователь авторизован", extra={"user_id": user.id, "phone": user.phone_number})
    logger.error("Ошибка оплаты", extra={"rental_id": rental.id, "amount": amount})
"""
import logging
import sys
from os import getenv
from typing import Optional
import json
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """JSON форматтер для структурированных логов (для production)"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Добавляем extra данные
        if hasattr(record, '__dict__'):
            for key, value in record.__dict__.items():
                if key not in ['name', 'msg', 'args', 'created', 'filename', 
                              'funcName', 'levelname', 'levelno', 'lineno',
                              'module', 'msecs', 'pathname', 'process',
                              'processName', 'relativeCreated', 'stack_info',
                              'exc_info', 'exc_text', 'thread', 'threadName',
                              'message', 'asctime']:
                    try:
                        json.dumps(value)  # Проверяем сериализуемость
                        log_data[key] = value
                    except (TypeError, ValueError):
                        log_data[key] = str(value)
        
        # Добавляем exception info
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data, ensure_ascii=False)


class ColoredFormatter(logging.Formatter):
    """Цветной форматтер для разработки"""
    
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'
    BOLD = '\033[1m'
    
    def format(self, record: logging.LogRecord) -> str:
        # Базовый формат
        color = self.COLORS.get(record.levelname, '')
        
        # Время
        timestamp = datetime.now().strftime('%H:%M:%S')
        
        # Уровень
        level = f"{color}{record.levelname:8}{self.RESET}"
        
        # Модуль и функция
        location = f"{self.BOLD}{record.module}.{record.funcName}{self.RESET}"
        
        # Сообщение
        message = record.getMessage()
        
        # Extra данные
        extra_str = ""
        extra_keys = ['user_id', 'phone', 'rental_id', 'car_id', 'amount', 
                      'status', 'error', 'duration', 'request_id']
        extras = []
        for key in extra_keys:
            if hasattr(record, key):
                value = getattr(record, key)
                extras.append(f"{key}={value}")
        
        if extras:
            extra_str = f" | {', '.join(extras)}"
        
        # Финальный формат
        formatted = f"{timestamp} {level} [{location}] {message}{extra_str}"
        
        # Добавляем exception если есть
        if record.exc_info:
            formatted += f"\n{self.formatException(record.exc_info)}"
        
        return formatted


def setup_logging(
    level: str = None,
    json_format: bool = None
) -> None:
    """
    Настройка логирования. Один handler в stdout.
    По умолчанию LOG_LEVEL=DEBUG — видны все логи. Приглушён только APScheduler.

    ENV: LOG_LEVEL=DEBUG | INFO | WARNING | ERROR (по умолчанию DEBUG), LOG_FORMAT=text | json

    Args:
        level: Уровень логирования (DEBUG, INFO, WARNING, ERROR)
        json_format: Использовать JSON формат (для production)
    """
    # По умолчанию DEBUG — видны все логи (DEBUG, INFO, WARNING, ERROR). LOG_LEVEL=INFO уменьшит шум.
    if level is None:
        level = getenv('LOG_LEVEL', 'DEBUG')
    
    log_level = getattr(logging, level.upper(), logging.DEBUG)
    
    # Определяем формат
    if json_format is None:
        json_format = getenv('LOG_FORMAT', 'text').lower() == 'json'
    
    # Создаём handler; line_buffering чтобы каждая строка сразу уходила в stdout (Docker/K8s)
    stream = sys.stdout
    try:
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(line_buffering=True)
    except Exception:
        pass
    handler = logging.StreamHandler(stream)
    handler.setLevel(log_level)

    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(ColoredFormatter())
    
    # Root logger — один handler в stdout, уровень из LOG_LEVEL. Ничего больше не трогаем.
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers = []
    root_logger.addHandler(handler)
    
    # Приглушаем шумные логгеры: APScheduler, httpx/httpcore, OpenTelemetry exporter.
    # OTLP exporter при недоступности Tempo пишет ERROR (Failed to export traces) — не спамим.
    for name in (
        "apscheduler",
        "apscheduler.executors.default",
        "httpx",
        "httpcore",
        "opentelemetry.exporter.otlp",
        "opentelemetry.exporter.otlp.proto.grpc",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Получить логгер для модуля.
    
    Args:
        name: Имя модуля (обычно __name__)
    
    Returns:
        Настроенный логгер
    
    Примеры использования:
        logger = get_logger(__name__)
        
        # Простое сообщение
        logger.info("Запрос обработан")
        
        # С контекстом
        logger.info("Пользователь авторизован", extra={"user_id": "123", "phone": "777"})
        
        # Ошибка с исключением
        try:
            ...
        except Exception as e:
            logger.error("Ошибка обработки", exc_info=True, extra={"rental_id": "456"})
    """
    return logging.getLogger(name)


# Автоматическая настройка при импорте
setup_logging()

