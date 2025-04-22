from fastapi import APIRouter, WebSocket, Query, Depends, WebSocketDisconnect
from sqlalchemy.orm import Session
from app.websocket.connection_manager import manager
from app.auth.dependencies.get_current_user import get_current_user
from app.dependencies.database.database import get_db

WebSocketRouter = APIRouter()


@WebSocketRouter.websocket("/ws/notifications")
async def websocket_notifications(
        websocket: WebSocket,
        token: str = Query(...),
        db: Session = Depends(get_db)
):
    """
    Единственный WebSocket‑канал для уведомлений.
    Клиент передаёт ?token=<JWT>.
    """
    # Аутентифицируем по JWT; вернёт объект User (любую роль)
    user = await get_current_user(db=db, token=token)
    user_id = user.id

    await manager.connect(websocket, user_id)
    try:
        while True:
            # Держим соединение открытым; игнорируем входящие
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id)
