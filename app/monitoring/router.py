"""
API endpoints для мониторинга и отправки ошибок от фронтенда
"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
import asyncio
import httpx
import logging

from app.core.config import TELEGRAM_BOT_MONITOR, MONITOR_GROUP_ID

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/monitoring", tags=["Monitoring"])


class FrontendErrorRequest(BaseModel):
    """Схема для отправки ошибок от фронтенда"""
    error_message: str = Field(..., description="Сообщение об ошибке")
    error_type: Optional[str] = Field(None, description="Тип ошибки (например, TypeError, NetworkError)")
    stack_trace: Optional[str] = Field(None, description="Stack trace ошибки")
    user_id: Optional[str] = Field(None, description="ID пользователя")
    user_phone: Optional[str] = Field(None, description="Телефон пользователя")
    page_url: Optional[str] = Field(None, description="URL страницы, где произошла ошибка")
    user_agent: Optional[str] = Field(None, description="User Agent браузера")
    additional_context: Optional[Dict[str, Any]] = Field(None, description="Дополнительный контекст")


async def send_frontend_error_to_telegram(error_data: FrontendErrorRequest):
    """
    Отправить ошибку от фронтенда в Telegram группу мониторинга
    """
    try:
        # Формируем сообщение
        message_parts = ["🚨 <b>ОШИБКА В ПРИЛОЖЕНИИ</b>"]
        message_parts.append("📱 <b>Источник:</b> FRONTEND")
        
        # Время
        message_parts.append(f"\n⏰ <b>Время:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
        
        # Информация о пользователе
        if error_data.user_id or error_data.user_phone:
            message_parts.append("\n👤 <b>ПОЛЬЗОВАТЕЛЬ:</b>")
            if error_data.user_id:
                message_parts.append(f"  • ID: <code>{error_data.user_id}</code>")
            if error_data.user_phone:
                message_parts.append(f"  • Телефон: {error_data.user_phone}")
        
        # Информация о странице
        if error_data.page_url or error_data.user_agent:
            message_parts.append("\n🌐 <b>БРАУЗЕР:</b>")
            if error_data.page_url:
                message_parts.append(f"  • URL: <code>{error_data.page_url}</code>")
            if error_data.user_agent:
                # Обрезаем user agent, если слишком длинный
                ua = error_data.user_agent[:100] + "..." if len(error_data.user_agent) > 100 else error_data.user_agent
                message_parts.append(f"  • User Agent: <code>{ua}</code>")
        
        # Информация об ошибке
        message_parts.append("\n❌ <b>ОШИБКА:</b>")
        if error_data.error_type:
            message_parts.append(f"  • Тип: <code>{error_data.error_type}</code>")
        message_parts.append(f"  • Сообщение: <code>{error_data.error_message}</code>")
        
        # Stack trace
        if error_data.stack_trace:
            stack = error_data.stack_trace
            # Ограничиваем размер stack trace
            if len(stack) > 2000:
                stack = stack[:1000] + "\n...\n" + stack[-1000:]
            message_parts.append(f"\n📋 <b>STACK TRACE:</b>\n<pre>{stack}</pre>")
        
        # Дополнительный контекст
        if error_data.additional_context:
            message_parts.append("\n📝 <b>ДОПОЛНИТЕЛЬНО:</b>")
            for key, value in error_data.additional_context.items():
                # Ограничиваем длину значения
                str_value = str(value)
                if len(str_value) > 200:
                    str_value = str_value[:200] + "..."
                message_parts.append(f"  • {key}: <code>{str_value}</code>")
        
        full_message = "\n".join(message_parts)
        
        # Отправляем в Telegram
        await _send_message_to_telegram(full_message)
        
    except Exception as e:
        logger.error(f"Ошибка отправки frontend ошибки в Telegram: {e}")


async def _send_message_to_telegram(message: str):
    """Отправить сообщение в Telegram с разбивкой на части при необходимости"""
    if not TELEGRAM_BOT_MONITOR or not MONITOR_GROUP_ID:
        logger.warning("Telegram bot token or group ID not configured")
        return
    
    max_length = 4096
    base_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_MONITOR}"
    
    try:
        if len(message) <= max_length:
            await _send_single_message(base_url, MONITOR_GROUP_ID, message)
        else:
            # Разбиваем на части
            parts = []
            current_part = ""
            
            for line in message.split("\n"):
                if len(current_part) + len(line) + 1 > max_length:
                    parts.append(current_part)
                    current_part = line + "\n"
                else:
                    current_part += line + "\n"
            
            if current_part:
                parts.append(current_part)
            
            # Отправляем по частям
            for i, part in enumerate(parts, 1):
                prefix = f"📄 <b>Часть {i}/{len(parts)}</b>\n\n" if len(parts) > 1 else ""
                await _send_single_message(base_url, MONITOR_GROUP_ID, prefix + part)
                if i < len(parts):
                    await asyncio.sleep(0.5)
    except Exception as e:
        logger.error(f"Ошибка отправки в Telegram: {e}")


async def _send_single_message(base_url: str, chat_id: str, text: str):
    """Отправить одно сообщение в Telegram"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{base_url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML"
                }
            )
            
            if response.status_code != 200:
                logger.error(f"Telegram API error: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Ошибка HTTP-запроса в Telegram: {e}")


@router.post("/error", status_code=status.HTTP_200_OK)
async def log_frontend_error(error_data: FrontendErrorRequest):
    """
    Endpoint для отправки ошибок от фронтенда
    
    Пример использования на фронтенде:
    ```javascript
    window.addEventListener('error', async (event) => {
        try {
            await fetch('https://api.azvmotors.kz/api/monitoring/error', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    error_message: event.message,
                    error_type: event.error?.name || 'Error',
                    stack_trace: event.error?.stack,
                    page_url: window.location.href,
                    user_agent: navigator.userAgent,
                    user_id: getCurrentUserId(),
                    user_phone: getCurrentUserPhone(),
                    additional_context: {
                        timestamp: new Date().toISOString(),
                        viewport: `${window.innerWidth}x${window.innerHeight}`
                    }
                })
            });
        } catch (e) {
            console.error('Failed to send error to backend:', e);
        }
    });
    ```
    """
    try:
        # Логируем в консоль для отладки
        logger.info(f"Получена ошибка от фронтенда: {error_data.error_type} - {error_data.error_message}")
        
        # Отправляем в Telegram
        await send_frontend_error_to_telegram(error_data)
        
        return {
            "success": True,
            "message": "Error logged successfully"
        }
        
    except Exception as e:
        logger.error(f"Ошибка обработки frontend ошибки: {e}")
        # Не бросаем исключение, чтобы не ломать фронтенд
        return {
            "success": False,
            "message": "Failed to log error"
        }


@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """
    Проверка работоспособности системы мониторинга
    """
    return {
        "status": "healthy",
        "monitoring_enabled": bool(TELEGRAM_BOT_MONITOR and MONITOR_GROUP_ID),
        "timestamp": datetime.utcnow().isoformat()
    }

