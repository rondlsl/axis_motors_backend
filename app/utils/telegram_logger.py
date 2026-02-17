"""
Telegram Logger для отправки ошибок и критических событий в Telegram группу мониторинга.
Учитывает лимиты Telegram: не более ~1 сообщения в секунду в один чат, при 429 — ожидание retry_after и повтор.
В parse_mode=HTML весь динамический текст экранируется, иначе Telegram возвращает 400 (can't parse entities).
"""
import asyncio
import html
import logging
import time
import traceback
from typing import Optional, Dict, Any
import httpx
from fastapi import Request

from app.core.config import TELEGRAM_BOT_MONITOR, MONITOR_GROUP_ID
from app.utils.time_utils import get_local_time

logger = logging.getLogger(__name__)

# Минимальный интервал между отправками в один чат (секунды), чтобы не получать 429
TELEGRAM_MIN_INTERVAL = 1.2


class TelegramErrorLogger:
    def __init__(self):
        self.bot_token = TELEGRAM_BOT_MONITOR
        self.chat_id = MONITOR_GROUP_ID
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self._last_send_time = 0.0
        self._send_lock = asyncio.Lock()
        
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
            message_parts.append("🖥️ <b>Источник:</b> BACKEND")
            
            # Время
            message_parts.append(f"\n⏰ <b>Время (GMT+5):</b> {get_local_time().strftime('%Y-%m-%d %H:%M:%S')}")
            
            def _esc(s: str) -> str:
                return html.escape(str(s), quote=True)

            # Информация о пользователе
            if user_info:
                message_parts.append("\n👤 <b>ПОЛЬЗОВАТЕЛЬ:</b>")
                if user_info.get("id"):
                    message_parts.append(f"  • ID: <code>{_esc(user_info['id'])}</code>")
                if user_info.get("name"):
                    message_parts.append(f"  • Имя: {_esc(user_info['name'])}")
                if user_info.get("phone"):
                    message_parts.append(f"  • Телефон: {_esc(user_info['phone'])}")
                if user_info.get("role"):
                    message_parts.append(f"  • Роль: {_esc(user_info['role'])}")
                if user_info.get("email"):
                    message_parts.append(f"  • Email: {_esc(user_info['email'])}")
            
            # Информация о запросе
            if request_info:
                message_parts.append("\n🌐 <b>ЗАПРОС:</b>")
                if request_info.get("method"):
                    message_parts.append(f"  • Метод: <code>{_esc(request_info['method'])}</code>")
                if request_info.get("url"):
                    message_parts.append(f"  • URL: <code>{_esc(request_info['url'])}</code>")
                if request_info.get("endpoint"):
                    message_parts.append(f"  • Endpoint: <code>{_esc(request_info['endpoint'])}</code>")
                if request_info.get("client_ip"):
                    message_parts.append(f"  • IP: <code>{_esc(request_info['client_ip'])}</code>")
            
            # Информация об ошибке (экранируем — в тексте могут быть <, >, &)
            message_parts.append("\n❌ <b>ОШИБКА:</b>")
            message_parts.append(f"  • Тип: <code>{_esc(type(error).__name__)}</code>")
            message_parts.append(f"  • Сообщение: <code>{_esc(str(error))}</code>")
            
            # Дополнительный контекст
            if additional_context:
                message_parts.append("\n📝 <b>ДОПОЛНИТЕЛЬНО:</b>")
                for key, value in additional_context.items():
                    str_value = str(value)
                    if len(str_value) > 200:
                        str_value = str_value[:200] + "..."
                    message_parts.append(f"  • {_esc(key)}: <code>{_esc(str_value)}</code>")
            
            full_message = "\n".join(message_parts)
            if len(full_message) > 4090:
                full_message = full_message[:4080] + "\n… (обрезано)"
            # Основное сообщение — всегда одним куском HTML, без traceback (чтобы не разрывать <pre> при разбиении)
            await self._send_single_message(full_message)

            # Traceback — отдельным сообщением без parse_mode (plain text), иначе при длине >4096 ломаются теги
            tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
            tb_text = "".join(tb_lines)
            if len(tb_text) > 3900:
                tb_text = tb_text[:1950] + "\n...\n" + tb_text[-1950:]
            if tb_text.strip():
                await self._send_single_message("📋 TRACEBACK:\n\n" + tb_text, parse_mode=None)
            
            await self._save_error_to_db(
                error=error,
                user_info=user_info,
                request_info=request_info,
                additional_context=additional_context
            )
            
        except Exception as e:
            logger.error(f"Ошибка отправки в Telegram: {e}")
            logger.error(traceback.format_exc())
    
    async def _save_error_to_db(
        self,
        error: Exception,
        user_info: Optional[Dict[str, Any]] = None,
        request_info: Optional[Dict[str, Any]] = None,
        additional_context: Optional[Dict[str, Any]] = None
    ):
        """Сохранить ошибку в БД для аналитики"""
        try:
            from app.dependencies.database.database import SessionLocal
            from app.models.error_log_model import ErrorLog
            import asyncio
            
            def _save():
                db = SessionLocal()
                try:
                    tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
                    tb_text = "".join(tb_lines)
                    
                    error_log = ErrorLog(
                        error_type=type(error).__name__,
                        message=str(error)[:1000] if error else None,
                        endpoint=request_info.get("endpoint") if request_info else None,
                        method=request_info.get("method") if request_info else None,
                        user_id=user_info.get("id") if user_info and user_info.get("id") else None,
                        user_phone=user_info.get("phone") if user_info else None,
                        traceback=tb_text[:5000] if tb_text else None,
                        context=additional_context,
                        source="BACKEND"
                    )
                    db.add(error_log)
                    db.commit()
                except Exception as e:
                    logger.error(f"Ошибка сохранения в БД: {e}")
                    db.rollback()
                finally:
                    db.close()
            
            await asyncio.to_thread(_save)
        except Exception as e:
            logger.error(f"Ошибка при сохранении ошибки в БД: {e}")
    
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
    
    async def _send_single_message(self, text: str, parse_mode: str | None = "HTML"):
        """Отправить одно сообщение в Telegram с учётом лимитов и повтором при 429."""
        async with self._send_lock:
            now = time.monotonic()
            wait = self._last_send_time + TELEGRAM_MIN_INTERVAL - now
            if wait > 0:
                await asyncio.sleep(wait)
            await self._do_send_with_retry(text, parse_mode=parse_mode)

    async def _do_send_with_retry(self, text: str, parse_mode: str | None = "HTML"):
        """Выполнить отправку; при 429 подождать retry_after и повторить один раз."""
        payload = {"chat_id": self.chat_id, "text": text}
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self.base_url}/sendMessage",
                    json=payload
                )
                if response.status_code == 200:
                    self._last_send_time = time.monotonic()
                    return
                if response.status_code == 429:
                    retry_after = self._parse_retry_after(response)
                    logger.warning(
                        "Telegram API 429, waiting %s s before retry (monitor chat)",
                        retry_after
                    )
                    await asyncio.sleep(retry_after)
                    retry_response = await client.post(
                        f"{self.base_url}/sendMessage",
                        json=payload
                    )
                    if retry_response.status_code == 200:
                        self._last_send_time = time.monotonic()
                        return
                    logger.error(
                        "Telegram API error after retry: %s - %s",
                        retry_response.status_code,
                        retry_response.text[:500],
                    )
                else:
                    logger.error(
                        "Telegram API error: %s - %s",
                        response.status_code,
                        response.text[:500],
                    )
        except Exception as e:
            logger.error("Ошибка HTTP-запроса в Telegram: %s", e)

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> int:
        """Достать retry_after из ответа 429 (по умолчанию 60 сек)."""
        try:
            data = response.json()
            params = data.get("parameters") or {}
            return int(params.get("retry_after", 60))
        except Exception:
            return 60
    
    async def send_info(self, message: str, context: Optional[Dict[str, Any]] = None):
        """Отправить информационное сообщение"""
        try:
            message_parts = [f"ℹ️ <b>ИНФОРМАЦИЯ</b>\n"]
            message_parts.append(f"⏰ {get_local_time().strftime('%Y-%m-%d %H:%M:%S')} (GMT+5)\n")
            message_parts.append(html.escape(message, quote=True))
            if context:
                message_parts.append("\n\n📝 <b>Контекст:</b>")
                for key, value in context.items():
                    message_parts.append(f"  • {html.escape(str(key), quote=True)}: <code>{html.escape(str(value), quote=True)}</code>")
            await self._send_single_message("\n".join(message_parts))
        except Exception as e:
            logger.error(f"Ошибка отправки info в Telegram: {e}")
    
    async def send_warning(self, message: str, context: Optional[Dict[str, Any]] = None):
        """Отправить предупреждение"""
        try:
            message_parts = [f"⚠️ <b>ПРЕДУПРЕЖДЕНИЕ</b>\n"]
            message_parts.append(f"⏰ {get_local_time().strftime('%Y-%m-%d %H:%M:%S')} (GMT+5)\n")
            message_parts.append(html.escape(message, quote=True))
            if context:
                message_parts.append("\n\n📝 <b>Контекст:</b>")
                for key, value in context.items():
                    message_parts.append(f"  • {html.escape(str(key), quote=True)}: <code>{html.escape(str(value), quote=True)}</code>")
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

