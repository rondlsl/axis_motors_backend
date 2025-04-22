from fastapi import APIRouter, WebSocket, Query, WebSocketDisconnect, HTTPException, Depends
from sqlalchemy.orm import Session

from app.auth.security.tokens import verify_token
from app.websocket.connection_manager import manager
from app.dependencies.database.database import get_db
from app.models.user_model import User

WebSocketRouter = APIRouter()

@WebSocketRouter.websocket("/ws/notifications")
async def websocket_notifications(
    websocket: WebSocket,
    token: str = Query(...),  # JWT в ?token=
    db: Session = Depends(get_db),
):
    # 1) Аутентификация
    try:
        payload = verify_token(token, "access")
    except HTTPException:
        # сразу закрываем, не делаем accept() здесь
        await websocket.close(code=1008, reason="Invalid token")
        return

    user = db.query(User).filter(
        User.phone_number == payload.get("sub"),
        User.is_active == True
    ).first()
    if not user:
        await websocket.close(code=1008, reason="User not found")
        return

    # 2) Регистрируемся (connect сам делает accept)
    await manager.connect(user.id, websocket)

    # 3) Держим соединение живым
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user.id)
