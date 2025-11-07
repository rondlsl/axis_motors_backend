"""
Декоратор для автоматического логирования ошибок в Telegram
"""
import functools
from typing import Callable, Any
from fastapi import Request, HTTPException
from app.utils.telegram_logger import log_error_to_telegram


def log_errors_to_telegram(action_name: str):
    """
    Декоратор для автоматического логирования ошибок в критичных операциях
    
    Args:
        action_name: Название операции для контекста (напр. "start_rental", "topup_wallet")
    
    Usage:
        @log_errors_to_telegram("start_rental")
        async def start_rental(...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Пытаемся извлечь request и current_user из аргументов
            request = None
            current_user = None
            additional_context = {"action": action_name}
            
            # Ищем request в kwargs
            if "request" in kwargs:
                request = kwargs["request"]
            
            # Ищем current_user в kwargs
            if "current_user" in kwargs:
                current_user = kwargs["current_user"]
            
            # Добавляем параметры функции в контекст
            for key, value in kwargs.items():
                if key not in ["request", "current_user", "db"]:
                    # Ограничиваем длину значения для безопасности
                    str_value = str(value)
                    if len(str_value) > 200:
                        str_value = str_value[:200] + "..."
                    additional_context[key] = str_value
            
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                # HTTPException не логируем - это ожидаемые ошибки (400, 404 и т.д.)
                raise
            except Exception as e:
                # Логируем неожиданные ошибки
                try:
                    await log_error_to_telegram(
                        error=e,
                        request=request,
                        user=current_user,
                        additional_context=additional_context
                    )
                except:
                    # Если не удалось залогировать - не падаем
                    pass
                
                # Пробрасываем ошибку дальше
                raise
        
        return wrapper
    return decorator

