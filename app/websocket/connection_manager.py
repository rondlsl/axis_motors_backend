from typing import Dict
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}
        print("ConnectionManager initialized. Active connections: 0")

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        print(f"[CONNECT] user_id={user_id} connected. Total: {len(self.active_connections)}")

    def disconnect(self, user_id: int):
        removed = self.active_connections.pop(user_id, None)
        if removed:
            print(f"[DISCONNECT] user_id={user_id} disconnected. Total: {len(self.active_connections)}")
        else:
            print(f"[DISCONNECT] user_id={user_id} was not connected.")

    async def send_personal_message(self, user_id: int, message: dict):
        print(f"[SEND] to user_id={user_id}: {message}")
        ws = self.active_connections.get(user_id)
        if ws and ws.client_state == WebSocketState.CONNECTED:
            await ws.send_json(message)
            print(f"[SENT] user_id={user_id}")
        else:
            print(f"[WARN] cannot send, user_id={user_id} not connected or socket closed.")


manager = ConnectionManager()
