"""
Утилита для сохранения информации о зависаниях в БД

Использует отдельный поток для записи, чтобы работать даже при блокировке event loop
"""
import threading
import traceback
import sys
from typing import Optional, Dict, Any
from datetime import datetime

from app.core.logging_config import get_logger

logger = get_logger(__name__)


def get_all_thread_stacks() -> str:
    """
    Получить stack traces всех потоков
    
    Использует sys._current_frames() для получения фреймов всех потоков
    """
    try:
        frames = sys._current_frames()
        stack_traces = []
        
        for thread_id, frame in frames.items():
            # Получаем имя потока
            thread_name = None
            for thread in threading.enumerate():
                if thread.ident == thread_id:
                    thread_name = thread.name
                    break
            
            # Формируем stack trace для этого потока
            stack_lines = traceback.format_stack(frame)
            stack_trace = f"\n--- Thread {thread_id} ({thread_name or 'Unknown'}) ---\n"
            stack_trace += "".join(stack_lines)
            stack_traces.append(stack_trace)
        
        return "\n".join(stack_traces)
    except Exception as e:
        logger.error(f"Ошибка получения stack traces: {e}")
        return f"Error getting stack traces: {str(e)}"


def save_hang_to_db_sync(
    method: str,
    path: str,
    duration_ms: float,
    trace_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_phone: Optional[str] = None,
    stack_traces: Optional[str] = None,
    additional_context: Optional[Dict[str, Any]] = None
) -> None:
    """
    Синхронная функция для сохранения зависания в БД
    
    Вызывается из отдельного потока, чтобы работать даже при блокировке event loop
    """
    try:
        from app.dependencies.database.database import SessionLocal
        from app.models.error_log_model import ErrorLog
        from app.utils.short_id import safe_sid_to_uuid
        from uuid import UUID
        
        db = SessionLocal()
        try:
            # Подготавливаем контекст
            context = {
                "duration_ms": round(duration_ms, 2),
                "duration_seconds": round(duration_ms / 1000.0, 2),
                "detected_at": datetime.utcnow().isoformat(),
            }
            
            if trace_id:
                context["trace_id"] = trace_id
            if additional_context:
                context.update(additional_context)
            
            # Конвертируем user_id в UUID если нужно
            user_uuid = None
            if user_id:
                try:
                    if isinstance(user_id, str):
                        user_uuid = safe_sid_to_uuid(user_id)
                    elif isinstance(user_id, UUID):
                        user_uuid = user_id
                except Exception:
                    pass  # Если не удалось конвертировать, оставляем None
            
            # Формируем сообщение
            message = f"Hang detected: {method} {path} (duration: {round(duration_ms/1000.0, 2)}s)"
            
            # Создаем запись об ошибке
            error_log = ErrorLog(
                error_type="HANG",
                message=message[:1000] if message else None,
                endpoint=path[:500] if path else None,
                method=method[:10] if method else None,
                user_id=user_uuid,
                user_phone=user_phone[:50] if user_phone else None,
                traceback=stack_traces[:50000] if stack_traces else None,  # Увеличиваем лимит для stack traces
                context=context,
                source="BACKEND"
            )
            
            db.add(error_log)
            db.commit()
            
            logger.warning(
                f"✅ Hang saved to DB: {method} {path} "
                f"(duration: {round(duration_ms/1000.0, 2)}s, trace_id: {trace_id})"
            )
            
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения зависания в БД: {e}")
            logger.error(traceback.format_exc())
            db.rollback()
        finally:
            db.close()
            
    except Exception as e:
        # Даже если не удалось подключиться к БД, логируем в консоль
        logger.error(f"❌ Критическая ошибка при сохранении зависания: {e}")
        logger.error(traceback.format_exc())


def save_hang_to_db_async(
    method: str,
    path: str,
    duration_ms: float,
    trace_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_phone: Optional[str] = None,
    stack_traces: Optional[str] = None,
    additional_context: Optional[Dict[str, Any]] = None
) -> None:
    """
    Асинхронная функция для сохранения зависания в БД
    
    Запускает сохранение в отдельном потоке, чтобы не блокировать event loop
    и работать даже если event loop заблокирован
    """
    # Запускаем сохранение в отдельном потоке
    thread = threading.Thread(
        target=save_hang_to_db_sync,
        args=(method, path, duration_ms, trace_id, user_id, user_phone, stack_traces, additional_context),
        daemon=True,  # Daemon thread - не будет блокировать завершение процесса
        name="HangLoggerThread"
    )
    thread.start()
    
    # Не ждем завершения потока - это fire-and-forget операция
    # Важно: поток должен быть daemon, чтобы не блокировать завершение процесса
