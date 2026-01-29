"""
Redis Pub/Sub для WebSocket в кластерном режиме.

Позволяет отправлять WebSocket сообщения пользователям, подключённым 
к любому инстансу бэкенда.

Channel Design:
    ws:user:{user_id}                    - персональные сообщения пользователю
    ws:broadcast:{type}:{subscription}   - broadcast по типу и подписке
    ws:broadcast:{type}                  - broadcast по типу всем

Алгоритм:
1. При отправке сообщения → публикуем в Redis channel
2. Все инстансы подписаны на patterns (ws:*)
3. Каждый инстанс проверяет: есть ли локальное подключение
4. Если есть → отправляет через WebSocket

Graceful degradation:
    При недоступности Redis - работаем только с локальными подключениями.
"""
import asyncio
import json
import logging
import uuid
from typing import Any, Optional, Callable, Coroutine

import redis.asyncio as redis

from app.services.redis_service import get_redis_service

logger = logging.getLogger(__name__)

# Prefixes для Redis channels
CHANNEL_USER = "ws:user"
CHANNEL_BROADCAST = "ws:broadcast"

# Instance ID для отладки и предотвращения эха
INSTANCE_ID = str(uuid.uuid4())[:8]


class WebSocketPubSub:
    """
    Redis Pub/Sub manager для WebSocket сообщений.
    
    Singleton - один экземпляр на приложение.
    """
    
    _instance: Optional['WebSocketPubSub'] = None
    _subscriber_task: Optional[asyncio.Task] = None
    _running: bool = False
    _message_handler: Optional[Callable[[str, dict], Coroutine[Any, Any, None]]] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def set_message_handler(
        self, 
        handler: Callable[[str, dict], Coroutine[Any, Any, None]]
    ) -> None:
        """
        Установить обработчик входящих сообщений.
        
        Handler вызывается с (channel, message_dict) для каждого 
        полученного сообщения из Redis Pub/Sub.
        
        Args:
            handler: async функция (channel: str, message: dict) -> None
        """
        self._message_handler = handler
    
    async def start(self) -> bool:
        """
        Запустить подписку на Redis Pub/Sub.
        
        Вызывать при startup приложения ПОСЛЕ init_redis().
        
        Returns:
            True если подписка запущена, False если Redis недоступен
        """
        if self._running:
            return True
        
        redis = get_redis_service()
        if not redis.is_available or not redis.client:
            logger.info(f"[{INSTANCE_ID}] Redis unavailable, WebSocket Pub/Sub disabled")
            return False
        
        try:
            # Создаём отдельное подключение для Pub/Sub (required by redis-py)
            self._pubsub = redis.client.pubsub()
            
            # Подписываемся на паттерны
            await self._pubsub.psubscribe(
                f"{CHANNEL_USER}:*",
                f"{CHANNEL_BROADCAST}:*"
            )
            
            # Запускаем background task для чтения сообщений
            self._running = True
            self._subscriber_task = asyncio.create_task(
                self._subscriber_loop(),
                name=f"ws_pubsub_{INSTANCE_ID}"
            )
            
            logger.info(f"[{INSTANCE_ID}] WebSocket Pub/Sub started")
            return True
            
        except Exception as e:
            logger.error(f"[{INSTANCE_ID}] Failed to start WebSocket Pub/Sub: {e}")
            return False
    
    async def stop(self) -> None:
        """
        Остановить подписку на Redis Pub/Sub.
        
        Вызывать при shutdown приложения.
        """
        self._running = False
        
        if self._subscriber_task:
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                pass  # Expected - мы сами вызвали cancel()
            self._subscriber_task = None
        
        if hasattr(self, '_pubsub') and self._pubsub:
            try:
                await self._pubsub.punsubscribe()
                await self._pubsub.close()
            except Exception as e:
                logger.warning(f"[{INSTANCE_ID}] Error closing Pub/Sub: {e}")
        
        logger.info(f"[{INSTANCE_ID}] WebSocket Pub/Sub stopped")
    
    async def _subscriber_loop(self) -> None:
        """
        Background loop для чтения сообщений из Pub/Sub.
        
        Включает reconnect логику при потере соединения с Redis.
        Exponential backoff: 1s → 2s → 4s → ... → 30s max
        """
        logger.debug(f"[{INSTANCE_ID}] Subscriber loop started")
        reconnect_delay = 1.0
        max_reconnect_delay = 30.0
        
        while self._running:
            try:
                # Проверяем что pubsub ещё жив
                if not hasattr(self, '_pubsub') or self._pubsub is None:
                    await self._reconnect_pubsub()
                    reconnect_delay = 1.0  # Reset on success
                
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0
                )
                
                if message and message['type'] == 'pmessage':
                    await self._handle_message(message)
                    
            except asyncio.CancelledError:
                raise  # Re-raise для корректного завершения
            except (ConnectionError, TimeoutError) as e:
                # Потеря соединения с Redis - пробуем reconnect
                logger.warning(f"[{INSTANCE_ID}] Pub/Sub connection lost: {e}")
                await self._cleanup_pubsub()
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
            except redis.exceptions.RedisError as e:
                # Redis-specific ошибки - пробуем reconnect
                logger.warning(f"[{INSTANCE_ID}] Redis error in Pub/Sub: {e}")
                await self._cleanup_pubsub()
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
            except Exception as e:
                # Неизвестные ошибки - логируем и продолжаем
                logger.error(f"[{INSTANCE_ID}] Unexpected error in subscriber loop: {e}")
                await asyncio.sleep(1.0)
        
        logger.debug(f"[{INSTANCE_ID}] Subscriber loop stopped")
    
    async def _reconnect_pubsub(self) -> None:
        """Переподключение к Redis Pub/Sub."""
        redis = get_redis_service()
        if not redis.is_available or not redis.client:
            logger.warning(f"[{INSTANCE_ID}] Cannot reconnect - Redis unavailable")
            raise ConnectionError("Redis unavailable")
        
        try:
            self._pubsub = redis.client.pubsub()
            await self._pubsub.psubscribe(
                f"{CHANNEL_USER}:*",
                f"{CHANNEL_BROADCAST}:*"
            )
            logger.info(f"[{INSTANCE_ID}] Pub/Sub reconnected successfully")
        except Exception as e:
            logger.error(f"[{INSTANCE_ID}] Pub/Sub reconnect failed: {e}")
            self._pubsub = None
            raise
    
    async def _cleanup_pubsub(self) -> None:
        """Очистка старого pubsub соединения."""
        if hasattr(self, '_pubsub') and self._pubsub:
            try:
                await self._pubsub.close()
            except Exception:
                pass
            self._pubsub = None
    
    async def _handle_message(self, message: dict) -> None:
        """Обработать полученное сообщение из Pub/Sub."""
        try:
            channel = message.get('channel', '')
            if isinstance(channel, bytes):
                channel = channel.decode('utf-8')
            
            data = message.get('data', '{}')
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            
            payload = json.loads(data)
            
            # Пропускаем сообщения от самого себя
            if payload.get('_instance_id') == INSTANCE_ID:
                return
            
            # Вызываем handler
            if self._message_handler:
                await self._message_handler(channel, payload)
                
        except json.JSONDecodeError as e:
            logger.warning(f"[{INSTANCE_ID}] Invalid JSON in Pub/Sub message: {e}")
        except Exception as e:
            logger.error(f"[{INSTANCE_ID}] Error handling Pub/Sub message: {e}")
    
    # === Publish Methods ===
    
    async def publish_to_user(
        self,
        user_id: str,
        connection_type: str,
        subscription_key: str,
        message: dict[str, Any]
    ) -> bool:
        """
        Опубликовать сообщение для конкретного пользователя.
        
        Сообщение будет доставлено на тот инстанс, где пользователь подключён.
        
        Args:
            user_id: ID пользователя
            connection_type: Тип подключения (vehicles_list, user_status, telemetry)
            subscription_key: Ключ подписки
            message: Сообщение для отправки
            
        Returns:
            True если опубликовано успешно
        """
        redis = get_redis_service()
        if not redis.is_available or not redis.client:
            return False
        
        try:
            channel = f"{CHANNEL_USER}:{user_id}"
            payload = {
                "_instance_id": INSTANCE_ID,
                "user_id": user_id,
                "connection_type": connection_type,
                "subscription_key": subscription_key,
                "message": message
            }
            
            await redis.client.publish(channel, json.dumps(payload))
            return True
            
        except Exception as e:
            logger.error(f"[{INSTANCE_ID}] Failed to publish to user {user_id}: {e}")
            return False
    
    async def publish_broadcast(
        self,
        connection_type: str,
        subscription_key: Optional[str],
        message: dict[str, Any],
        exclude_user_id: Optional[str] = None
    ) -> bool:
        """
        Опубликовать broadcast сообщение.
        
        Args:
            connection_type: Тип подключения
            subscription_key: Ключ подписки (None = все подписки типа)
            message: Сообщение для отправки
            exclude_user_id: ID пользователя для исключения
            
        Returns:
            True если опубликовано успешно
        """
        redis = get_redis_service()
        if not redis.is_available or not redis.client:
            return False
        
        try:
            if subscription_key:
                channel = f"{CHANNEL_BROADCAST}:{connection_type}:{subscription_key}"
            else:
                channel = f"{CHANNEL_BROADCAST}:{connection_type}"
            
            payload = {
                "_instance_id": INSTANCE_ID,
                "connection_type": connection_type,
                "subscription_key": subscription_key,
                "message": message,
                "exclude_user_id": exclude_user_id
            }
            
            await redis.client.publish(channel, json.dumps(payload))
            return True
            
        except Exception as e:
            logger.error(f"[{INSTANCE_ID}] Failed to publish broadcast: {e}")
            return False
    
    @property
    def is_running(self) -> bool:
        """Проверить, запущен ли Pub/Sub."""
        return self._running
    
    @staticmethod
    def get_instance_id() -> str:
        """Получить ID текущего инстанса."""
        return INSTANCE_ID


# Глобальный экземпляр
_ws_pubsub: Optional[WebSocketPubSub] = None


def get_ws_pubsub() -> WebSocketPubSub:
    """Получить экземпляр WebSocket Pub/Sub."""
    global _ws_pubsub
    if _ws_pubsub is None:
        _ws_pubsub = WebSocketPubSub()
    return _ws_pubsub


async def init_ws_pubsub() -> bool:
    """
    Инициализировать WebSocket Pub/Sub при старте.
    
    Вызывать в startup_event ПОСЛЕ init_redis().
    """
    pubsub = get_ws_pubsub()
    return await pubsub.start()


async def shutdown_ws_pubsub() -> None:
    """Остановить WebSocket Pub/Sub при остановке."""
    pubsub = get_ws_pubsub()
    await pubsub.stop()
