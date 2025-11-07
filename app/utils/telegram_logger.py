"""
Telegram Logger для отправки ошибок и критических событий в Telegram группу мониторинга
"""
import asyncio
import logging
import traceback
from datetime import datetime
from typing import Optional, Dict, Any
import httpx
from fastapi import Request

from app.core.config import TELEGRAM_BOT_MONITOR, MONITOR_GROUP_ID

logger = logging.getLogger(__name__)


class TelegramErrorLogger:
    def __init__(self):
        self.bot_token = TELEGRAM_BOT_MONITOR
        self.chat_id = MONITOR_GROUP_ID
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        
    async def send_error(
        self,
        error: Exception,
        user_info: Optional[Dict[str, Any]] = None,
        request_info: Optional[Dict[str, Any]] = None,
        additional_context: Optional[Dict[str, Any]] = None
    ):
        """
        Отправить информацию об ошибке в Telegram группу мониторинга
        
        Args:
            error: Исключение, которое произошло
            user_info: Информация о пользователе (id, name, phone, role и т.д.)
            request_info: Информация о запросе (method, url, headers, body)
            additional_context: Дополнительный контекст (параметры, данные и т.д.)
        """
        try:
            # Формируем сообщение
            message_parts = ["🚨 <b>ОШИБКА В ПРИЛОЖЕНИИ</b>"]
            
            # Время
            message_parts.append(f"\n⏰ <b>Время:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
            
            # Информация о пользователе
            if user_info:
                message_parts.append("\n👤 <b>ПОЛЬЗОВАТЕЛЬ:</b>")
                if user_info.get("id"):
                    message_parts.append(f"  • ID: <code>{user_info['id']}</code>")
                if user_info.get("name"):
                    message_parts.append(f"  • Имя: {user_info['name']}")
                if user_info.get("phone"):
                    message_parts.append(f"  • Телефон: {user_info['phone']}")
                if user_info.get("role"):
                    message_parts.append(f"  • Роль: {user_info['role']}")
                if user_info.get("email"):
                    message_parts.append(f"  • Email: {user_info['email']}")
            
            # Информация о запросе
            if request_info:
                message_parts.append("\n🌐 <b>ЗАПРОС:</b>")
                if request_info.get("method"):
                    message_parts.append(f"  • Метод: <code>{request_info['method']}</code>")
                if request_info.get("url"):
                    message_parts.append(f"  • URL: <code>{request_info['url']}</code>")
                if request_info.get("endpoint"):
                    message_parts.append(f"  • Endpoint: <code>{request_info['endpoint']}</code>")
                if request_info.get("client_ip"):
                    message_parts.append(f"  • IP: <code>{request_info['client_ip']}</code>")
            
            # Информация об ошибке
            message_parts.append("\n❌ <b>ОШИБКА:</b>")
            message_parts.append(f"  • Тип: <code>{type(error).__name__}</code>")
            message_parts.append(f"  • Сообщение: <code>{str(error)}</code>")
            
            # Traceback
            tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
            tb_text = "".join(tb_lines)
            
            # Ограничиваем traceback, чтобы не превысить лимит Telegram (4096 символов)
            if len(tb_text) > 2000:
                tb_text = tb_text[:1000] + "\n...\n" + tb_text[-1000:]
            
            message_parts.append(f"\n📋 <b>TRACEBACK:</b>\n<pre>{tb_text}</pre>")
            
            # Дополнительный контекст
            if additional_context:
                message_parts.append("\n📝 <b>ДОПОЛНИТЕЛЬНО:</b>")
                for key, value in additional_context.items():
                    # Ограничиваем длину значения
                    str_value = str(value)
                    if len(str_value) > 200:
                        str_value = str_value[:200] + "..."
                    message_parts.append(f"  • {key}: <code>{str_value}</code>")
            
            full_message = "\n".join(message_parts)
            
            # Разбиваем на части, если превышает лимит Telegram
            await self._send_message_parts(full_message)
            
        except Exception as e:
            logger.error(f"Ошибка отправки в Telegram: {e}")
            logger.error(traceback.format_exc())
    
    async def _send_message_parts(self, message: str):
        """Разбить и отправить длинное сообщение частями"""
        max_length = 4096
        
        if len(message) <= max_length:
            await self._send_single_message(message)
            return
        
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
            await self._send_single_message(prefix + part)
            if i < len(parts):
                await asyncio.sleep(0.5)
    
    async def _send_single_message(self, text: str):
        """Отправить одно сообщение в Telegram"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": "HTML"
                    }
                )
                
                if response.status_code != 200:
                    logger.error(f"Telegram API error: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Ошибка HTTP-запроса в Telegram: {e}")
    
    async def send_info(self, message: str, context: Optional[Dict[str, Any]] = None):
        """Отправить информационное сообщение"""
        try:
            message_parts = [f"ℹ️ <b>ИНФОРМАЦИЯ</b>\n"]
            message_parts.append(f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n")
            message_parts.append(message)
            
            if context:
                message_parts.append("\n\n📝 <b>Контекст:</b>")
                for key, value in context.items():
                    message_parts.append(f"  • {key}: <code>{value}</code>")
            
            await self._send_single_message("\n".join(message_parts))
        except Exception as e:
            logger.error(f"Ошибка отправки info в Telegram: {e}")
    
    async def send_warning(self, message: str, context: Optional[Dict[str, Any]] = None):
        """Отправить предупреждение"""
        try:
            message_parts = [f"⚠️ <b>ПРЕДУПРЕЖДЕНИЕ</b>\n"]
            message_parts.append(f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n")
            message_parts.append(message)
            
            if context:
                message_parts.append("\n\n📝 <b>Контекст:</b>")
                for key, value in context.items():
                    message_parts.append(f"  • {key}: <code>{value}</code>")
            
            await self._send_single_message("\n".join(message_parts))
        except Exception as e:
            logger.error(f"Ошибка отправки warning в Telegram: {e}")


# Глобальный экземпляр логгера
telegram_error_logger = TelegramErrorLogger()


async def log_error_to_telegram(
    error: Exception,
    request: Optional[Request] = None,
    user: Optional[Any] = None,
    additional_context: Optional[Dict[str, Any]] = None
):
    """
    Удобная функция для логирования ошибок
    
    Args:
        error: Исключение
        request: FastAPI Request объект
        user: Объект пользователя из БД
        additional_context: Дополнительный контекст
    """
    user_info = None
    request_info = None
    
    # Извлекаем информацию о пользователе
    if user:
        user_info = {
            "id": str(getattr(user, "id", None)),
            "name": f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip(),
            "phone": getattr(user, "phone_number", None),
            "email": getattr(user, "email", None),
            "role": getattr(user, "role", None).value if hasattr(getattr(user, "role", None), "value") else str(getattr(user, "role", None))
        }
    
    # Извлекаем информацию о запросе
    if request:
        request_info = {
            "method": request.method,
            "url": str(request.url),
            "endpoint": request.url.path,
            "client_ip": request.client.host if request.client else None
        }
        
        # Добавляем query параметры
        if request.query_params:
            if not additional_context:
                additional_context = {}
            additional_context["query_params"] = dict(request.query_params)
    
    await telegram_error_logger.send_error(
        error=error,
        user_info=user_info,
        request_info=request_info,
        additional_context=additional_context
    )

