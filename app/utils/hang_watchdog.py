"""
Watchdog для детектирования и логирования зависаний приложения

Периодически проверяет активные запросы и сохраняет информацию о зависших в БД
"""
import asyncio
import time
from typing import Set, Optional
from datetime import datetime

from app.core.logging_config import get_logger

logger = get_logger(__name__)
from app.middleware.hang_detector_middleware import get_hang_detector_instance
from app.utils.hang_logger import save_hang_to_db_async, get_all_thread_stacks


class HangWatchdog:
    """
    Watchdog для мониторинга зависаний
    
    Периодически проверяет активные запросы и сохраняет информацию о зависших в БД
    """
    
    def __init__(
        self,
        check_interval: float = 5.0,
        hang_threshold: float = 10.0,
        min_check_interval: float = 1.0
    ):
        """
        Args:
            check_interval: Интервал проверки в секундах (по умолчанию 5 сек)
            hang_threshold: Порог в секундах, после которого запрос считается зависшим (по умолчанию 10 сек)
            min_check_interval: Минимальный интервал между проверками (защита от спама)
        """
        self.check_interval = check_interval
        self.hang_threshold = hang_threshold
        self.min_check_interval = min_check_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_check_time = 0.0
        self._reported_hangs: Set[str] = set()  # Множество уже залогированных зависаний
    
    async def start(self) -> None:
        """Запустить watchdog"""
        if self._running:
            logger.warning("HangWatchdog уже запущен")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._watchdog_loop())
        logger.info(
            f"✅ HangWatchdog запущен: "
            f"check_interval={self.check_interval}s, "
            f"hang_threshold={self.hang_threshold}s"
        )
    
    async def stop(self) -> None:
        """Остановить watchdog"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("HangWatchdog остановлен")
    
    async def _watchdog_loop(self) -> None:
        """Основной цикл watchdog"""
        while self._running:
            try:
                await self._check_hangs()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в HangWatchdog: {e}")
                # Продолжаем работу даже при ошибке
                await asyncio.sleep(self.check_interval)
    
    async def _check_hangs(self) -> None:
        """Проверить зависшие запросы"""
        try:
            # Проверяем минимальный интервал между проверками
            current_time = time.time()
            if current_time - self._last_check_time < self.min_check_interval:
                return
            
            self._last_check_time = current_time
            
            # Получаем экземпляр HangDetectorMiddleware
            hang_detector = get_hang_detector_instance()
            if not hang_detector:
                # Middleware еще не инициализирован
                return
            
            # Получаем зависшие запросы
            hanging_requests = hang_detector.get_hanging_requests(self.hang_threshold)
            
            if not hanging_requests:
                return
            
            # Обрабатываем каждый зависший запрос
            for request_id, active_request in hanging_requests.items():
                # Проверяем, не логировали ли мы уже это зависание
                if request_id in self._reported_hangs:
                    # Уже логировали, пропускаем (чтобы не спамить)
                    continue
                
                # Помечаем как залогированное
                self._reported_hangs.add(request_id)
                
                # Получаем stack traces всех потоков
                stack_traces = get_all_thread_stacks()
                
                # Формируем дополнительный контекст
                additional_context = {
                    "request_id": request_id,
                    "detection_time": datetime.utcnow().isoformat(),
                }
                
                # Сохраняем зависание в БД (асинхронно, в отдельном потоке)
                save_hang_to_db_async(
                    method=active_request.method,
                    path=active_request.path,
                    duration_ms=active_request.duration_ms,
                    trace_id=active_request.trace_id,
                    stack_traces=stack_traces,
                    additional_context=additional_context
                )
                
                logger.warning(
                    f"🚨 Hang detected: {active_request.method} {active_request.path} "
                    f"(duration: {round(active_request.duration_ms/1000.0, 2)}s, "
                    f"trace_id: {active_request.trace_id})"
                )
            
            # Очищаем старые записи из _reported_hangs (чтобы не накапливать память)
            # Оставляем только те, которые все еще активны
            active_request_ids = set(hanging_requests.keys())
            self._reported_hangs = {
                req_id for req_id in self._reported_hangs
                if req_id in active_request_ids
            }
            
        except Exception as e:
            logger.error(f"Ошибка при проверке зависаний: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def reset_reported_hangs(self) -> None:
        """Сбросить список залогированных зависаний (для тестирования)"""
        self._reported_hangs.clear()


# Глобальный экземпляр watchdog
_hang_watchdog_instance: Optional[HangWatchdog] = None


def get_hang_watchdog() -> Optional[HangWatchdog]:
    """Получить глобальный экземпляр HangWatchdog"""
    return _hang_watchdog_instance


def set_hang_watchdog(instance: HangWatchdog) -> None:
    """Установить глобальный экземпляр HangWatchdog"""
    global _hang_watchdog_instance
    _hang_watchdog_instance = instance
