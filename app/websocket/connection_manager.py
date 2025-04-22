from typing import Dict
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        # единственный accept
        await websocket.accept()
        self.active_connections[user_id] = websocket
        print(f"[CONNECT] user_id={user_id}, total={len(self.active_connections)}")

    def disconnect(self, user_id: int):
        ws = self.active_connections.pop(user_id, None)
        if ws:
            print(f"[DISCONNECT] user_id={user_id}, total={len(self.active_connections)}")

    async def send_personal_message(self, user_id: int, message: dict):
        ws = self.active_connections.get(user_id)
        if ws and ws.client_state == WebSocketState.CONNECTED:
            await ws.send_json(message)


manager = ConnectionManager()
