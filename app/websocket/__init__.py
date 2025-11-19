"""
WebSocket модуль для real-time обновлений
"""
from app.websocket.manager import ConnectionManager
from app.websocket.router import websocket_router

__all__ = ["ConnectionManager", "websocket_router"]

