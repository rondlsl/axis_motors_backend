"""
Менеджер WebSocket подключений с поддержкой кластера через Redis Pub/Sub.

В кластерном режиме:
- Локальные подключения хранятся в памяти инстанса
- Сообщения публикуются в Redis Pub/Sub
- Каждый инстанс обрабатывает сообщения для своих локальных подключений

Graceful degradation:
    При недоступности Redis - работаем только с локальными подключениями
"""
from typing import Dict, Set, Optional, Any, List
from fastapi import WebSocket, WebSocketDisconnect
import json
import logging
from datetime import datetime
from uuid import UUID

logger = logging.getLogger(__name__)

# Import будет выполнен при первом использовании (избегаем circular import)
_pubsub_initialized = False


class ConnectionManager:
    """
    Менеджер для управления WebSocket подключениями.
    
    Поддерживает:
    - Группировку подключений по типам подписок
    - Отправку сообщений конкретному пользователю или группе
    - Автоматическую очистку при отключении
    - Кластерный режим через Redis Pub/Sub
    """
    
    def __init__(self):
        # Локальные подключения этого инстанса
        self._connections: Dict[str, Dict[str, Dict[str, WebSocket]]] = {}
        self._user_subscriptions: Dict[str, Dict[str, Set[str]]] = {}
        self._connection_metadata: Dict[str, Dict[str, Any]] = {}
        # Флаг инициализации Pub/Sub
        self._pubsub_ready = False
    
    async def init_pubsub(self) -> bool:
        """
        Инициализировать Redis Pub/Sub для кластерного режима.
        
        Вызывать при startup приложения ПОСЛЕ init_redis().
        
        Returns:
            True если Pub/Sub инициализирован
        """
        try:
            from app.websocket.pubsub import get_ws_pubsub
            
            pubsub = get_ws_pubsub()
            
            # Устанавливаем обработчик входящих сообщений
            pubsub.set_message_handler(self._handle_pubsub_message)
            
            # Запускаем Pub/Sub
            self._pubsub_ready = await pubsub.start()
            
            if self._pubsub_ready:
                logger.info("ConnectionManager: Pub/Sub initialized for cluster mode")
            else:
                logger.info("ConnectionManager: Running in single-instance mode (no Pub/Sub)")
            
            return self._pubsub_ready
            
        except Exception as e:
            logger.error(f"Failed to initialize Pub/Sub: {e}")
            self._pubsub_ready = False
            return False
    
    async def shutdown_pubsub(self) -> None:
        """Остановить Redis Pub/Sub."""
        if self._pubsub_ready:
            try:
                from app.websocket.pubsub import get_ws_pubsub
                await get_ws_pubsub().stop()
            except Exception as e:
                logger.error(f"Error shutting down Pub/Sub: {e}")
            self._pubsub_ready = False
    
    async def _handle_pubsub_message(self, channel: str, payload: dict) -> None:
        """
        Обработчик входящих сообщений из Redis Pub/Sub.
        
        Вызывается для каждого сообщения, полученного от других инстансов.
        Проверяет наличие локальных подключений и отправляет через WebSocket.
        """
        try:
            # Персональное сообщение пользователю
            if channel.startswith("ws:user:"):
                user_id = payload.get("user_id")
                connection_type = payload.get("connection_type")
                subscription_key = payload.get("subscription_key")
                message = payload.get("message")
                
                if all([user_id, connection_type, subscription_key, message]):
                    # Отправляем только если есть локальное подключение
                    await self._send_local_message(
                        connection_type, subscription_key, user_id, message
                    )
            
            # Broadcast сообщение
            elif channel.startswith("ws:broadcast:"):
                connection_type = payload.get("connection_type")
                subscription_key = payload.get("subscription_key")
                message = payload.get("message")
                exclude_user_id = payload.get("exclude_user_id")
                
                if connection_type and message:
                    if subscription_key:
                        await self._broadcast_local_to_subscription(
                            connection_type, subscription_key, message, exclude_user_id
                        )
                    else:
                        await self._broadcast_local_to_type(
                            connection_type, message, exclude_user_id
                        )
                        
        except Exception as e:
            logger.error(f"Error handling Pub/Sub message: {e}")
    
    async def connect(
        self,
        websocket: WebSocket,
        connection_type: str,
        subscription_key: str,
        user_id: str,
        user_metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Подключить клиента к WebSocket.
        
        Args:
            websocket: WebSocket соединение
            connection_type: Тип подключения (telemetry, vehicles_list, user_status)
            subscription_key: Ключ подписки (car_id для телеметрии, user_id для статуса и т.д.)
            user_id: ID пользователя
            user_metadata: Дополнительные метаданные пользователя
        """
        await websocket.accept()
        
        if connection_type not in self._connections:
            self._connections[connection_type] = {}
        if subscription_key not in self._connections[connection_type]:
            self._connections[connection_type][subscription_key] = {}
        
        self._connections[connection_type][subscription_key][user_id] = websocket
        
        if user_id not in self._user_subscriptions:
            self._user_subscriptions[user_id] = {}
        if connection_type not in self._user_subscriptions[user_id]:
            self._user_subscriptions[user_id][connection_type] = set()
        self._user_subscriptions[user_id][connection_type].add(subscription_key)
        
        if user_metadata:
            self._connection_metadata[user_id] = user_metadata
        
        logger.info(
            f"WebSocket connected: user={user_id}, type={connection_type}, "
            f"subscription={subscription_key}"
        )
    
    async def disconnect(
        self,
        connection_type: str,
        subscription_key: str,
        user_id: str
    ) -> None:
        """
        Отключить клиента от WebSocket.
        
        Args:
            connection_type: Тип подключения
            subscription_key: Ключ подписки
            user_id: ID пользователя
        """
        try:
            if (connection_type in self._connections and
                subscription_key in self._connections[connection_type] and
                user_id in self._connections[connection_type][subscription_key]):
                
                websocket = self._connections[connection_type][subscription_key][user_id]
                try:
                    await websocket.close()
                except Exception as e:
                    logger.warning(f"Error closing websocket: {e}")
                
                del self._connections[connection_type][subscription_key][user_id]
                
                if not self._connections[connection_type][subscription_key]:
                    del self._connections[connection_type][subscription_key]
                if not self._connections[connection_type]:
                    del self._connections[connection_type]
            
            if (user_id in self._user_subscriptions and
                connection_type in self._user_subscriptions[user_id]):
                self._user_subscriptions[user_id][connection_type].discard(subscription_key)
                if not self._user_subscriptions[user_id][connection_type]:
                    del self._user_subscriptions[user_id][connection_type]
                if not self._user_subscriptions[user_id]:
                    del self._user_subscriptions[user_id]
            
            if user_id in self._connection_metadata and user_id not in self._user_subscriptions:
                del self._connection_metadata[user_id]
            
            logger.info(
                f"WebSocket disconnected: user={user_id}, type={connection_type}, "
                f"subscription={subscription_key}"
            )
        except Exception as e:
            logger.error(f"Error disconnecting WebSocket: {e}")
    
    async def disconnect_user(self, user_id: str) -> None:
        """
        Отключить все подключения пользователя.
        
        Args:
            user_id: ID пользователя
        """
        if user_id not in self._user_subscriptions:
            return
        
        subscriptions_to_remove = []
        for connection_type, subscription_keys in self._user_subscriptions[user_id].items():
            for subscription_key in subscription_keys:
                subscriptions_to_remove.append((connection_type, subscription_key, user_id))
        
        for connection_type, subscription_key, user_id in subscriptions_to_remove:
            await self.disconnect(connection_type, subscription_key, user_id)
    
    async def _send_local_message(
        self,
        connection_type: str,
        subscription_key: str,
        user_id: str,
        message: Dict[str, Any]
    ) -> bool:
        """
        Отправить сообщение через ЛОКАЛЬНОЕ WebSocket подключение.
        
        Используется для отправки сообщений только на этом инстансе.
        НЕ публикует в Redis Pub/Sub.
        """
        try:
            if (connection_type in self._connections and
                subscription_key in self._connections[connection_type] and
                user_id in self._connections[connection_type][subscription_key]):
                
                websocket = self._connections[connection_type][subscription_key][user_id]
                await websocket.send_json(message)
                return True
            return False
        except WebSocketDisconnect:
            await self.disconnect(connection_type, subscription_key, user_id)
            return False
        except Exception as e:
            logger.error(f"Error sending local message: {e}")
            await self.disconnect(connection_type, subscription_key, user_id)
            return False
    
    async def send_personal_message(
        self,
        connection_type: str,
        subscription_key: str,
        user_id: str,
        message: Dict[str, Any]
    ) -> bool:
        """
        Отправить сообщение конкретному пользователю.
        
        В кластерном режиме: публикует в Redis Pub/Sub, чтобы 
        сообщение дошло до инстанса с активным подключением.
        
        Args:
            connection_type: Тип подключения
            subscription_key: Ключ подписки
            user_id: ID пользователя
            message: Сообщение для отправки
            
        Returns:
            True если сообщение отправлено (локально или через Pub/Sub)
        """
        # Сначала пробуем локально
        local_sent = await self._send_local_message(
            connection_type, subscription_key, user_id, message
        )
        
        if local_sent:
            return True
        
        # Если локально не отправлено и Pub/Sub доступен - публикуем
        if self._pubsub_ready:
            try:
                from app.websocket.pubsub import get_ws_pubsub
                pubsub = get_ws_pubsub()
                return await pubsub.publish_to_user(
                    user_id, connection_type, subscription_key, message
                )
            except Exception as e:
                logger.error(f"Error publishing to Pub/Sub: {e}")
        
        return False
    
    async def _broadcast_local_to_subscription(
        self,
        connection_type: str,
        subscription_key: str,
        message: Dict[str, Any],
        exclude_user_id: Optional[str] = None
    ) -> int:
        """
        Broadcast на ЛОКАЛЬНЫЕ подключения подписки.
        НЕ публикует в Redis.
        """
        sent_count = 0
        
        if (connection_type not in self._connections or
            subscription_key not in self._connections[connection_type]):
            return sent_count
        
        users_to_send = list(self._connections[connection_type][subscription_key].keys())
        
        for user_id in users_to_send:
            if exclude_user_id and user_id == exclude_user_id:
                continue
            
            if await self._send_local_message(connection_type, subscription_key, user_id, message):
                sent_count += 1
        
        return sent_count
    
    async def broadcast_to_subscription(
        self,
        connection_type: str,
        subscription_key: str,
        message: Dict[str, Any],
        exclude_user_id: Optional[str] = None
    ) -> int:
        """
        Отправить сообщение всем подписанным на конкретную подписку.
        
        В кластерном режиме: публикует в Redis Pub/Sub для доставки
        на все инстансы.
        
        Args:
            connection_type: Тип подключения
            subscription_key: Ключ подписки
            message: Сообщение для отправки
            exclude_user_id: ID пользователя, которому не отправлять
            
        Returns:
            Количество локально отправленных сообщений
        """
        # Отправляем локально
        sent_count = await self._broadcast_local_to_subscription(
            connection_type, subscription_key, message, exclude_user_id
        )
        
        # Публикуем в Pub/Sub для других инстансов
        if self._pubsub_ready:
            try:
                from app.websocket.pubsub import get_ws_pubsub
                await get_ws_pubsub().publish_broadcast(
                    connection_type, subscription_key, message, exclude_user_id
                )
            except Exception as e:
                logger.error(f"Error publishing broadcast to Pub/Sub: {e}")
        
        return sent_count
    
    async def _broadcast_local_to_type(
        self,
        connection_type: str,
        message: Dict[str, Any],
        exclude_user_id: Optional[str] = None
    ) -> int:
        """
        Broadcast на все ЛОКАЛЬНЫЕ подключения типа.
        НЕ публикует в Redis.
        """
        sent_count = 0
        
        if connection_type not in self._connections:
            return sent_count
        
        subscriptions = list(self._connections[connection_type].keys())
        
        for subscription_key in subscriptions:
            count = await self._broadcast_local_to_subscription(
                connection_type, subscription_key, message, exclude_user_id
            )
            sent_count += count
        
        return sent_count
    
    async def broadcast_to_type(
        self,
        connection_type: str,
        message: Dict[str, Any],
        exclude_user_id: Optional[str] = None
    ) -> int:
        """
        Отправить сообщение всем подключенным к типу подключения.
        
        В кластерном режиме: публикует в Redis Pub/Sub для доставки
        на все инстансы.
        
        Args:
            connection_type: Тип подключения
            message: Сообщение для отправки
            exclude_user_id: ID пользователя, которому не отправлять
            
        Returns:
            Количество локально отправленных сообщений
        """
        # Отправляем локально
        sent_count = await self._broadcast_local_to_type(
            connection_type, message, exclude_user_id
        )
        
        # Публикуем в Pub/Sub для других инстансов
        if self._pubsub_ready:
            try:
                from app.websocket.pubsub import get_ws_pubsub
                await get_ws_pubsub().publish_broadcast(
                    connection_type, None, message, exclude_user_id
                )
            except Exception as e:
                logger.error(f"Error publishing type broadcast to Pub/Sub: {e}")
        
        return sent_count
    
    def get_connection_count(self, connection_type: Optional[str] = None) -> int:
        """
        Получить количество активных подключений.
        
        Args:
            connection_type: Тип подключения (если None, возвращает общее количество)
            
        Returns:
            Количество активных подключений
        """
        if connection_type:
            if connection_type not in self._connections:
                return 0
            total = 0
            for subscriptions in self._connections[connection_type].values():
                total += len(subscriptions)
            return total
        else:
            total = 0
            for connection_type_conns in self._connections.values():
                for subscriptions in connection_type_conns.values():
                    total += len(subscriptions)
            return total
    
    def is_connected(
        self,
        connection_type: str,
        subscription_key: str,
        user_id: str
    ) -> bool:
        """
        Проверить, подключен ли пользователь.
        
        Args:
            connection_type: Тип подключения
            subscription_key: Ключ подписки
            user_id: ID пользователя
            
        Returns:
            True если подключен, False иначе
        """
        return (connection_type in self._connections and
                subscription_key in self._connections[connection_type] and
                user_id in self._connections[connection_type][subscription_key])

    def get_connected_users(self, connection_type: Optional[str] = None) -> List[str]:
        """
        Получить список user_id с активными подключениями.
        """
        users: Set[str] = set()
        if connection_type:
            if connection_type not in self._connections:
                return []
            for subscriptions in self._connections[connection_type].values():
                users.update(subscriptions.keys())
        else:
            for connection_type_conns in self._connections.values():
                for subscriptions in connection_type_conns.values():
                    users.update(subscriptions.keys())
        return list(users)


connection_manager = ConnectionManager()

