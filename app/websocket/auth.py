from fastapi import WebSocket, WebSocketException, status
from sqlalchemy.orm import Session
from typing import Optional
import logging

from app.dependencies.database.database import get_db, SessionLocal
from app.auth.security.tokens import verify_token
from app.models.user_model import User
from app.models.token_model import TokenRecord
from app.utils.time_utils import get_local_time

logger = logging.getLogger(__name__)


async def authenticate_websocket(
    websocket: WebSocket,
    token: Optional[str] = None,
    db: Optional[Session] = None
) -> Optional[User]:
    """
    Аутентифицировать WebSocket подключение по токену.
    
    Args:
        websocket: WebSocket соединение
        token: JWT токен из query параметра
        db: Сессия базы данных (если None, создаётся новая)
        
    Returns:
        User объект если авторизация успешна, None иначе
        
    Raises:
        WebSocketException: Если токен не предоставлен или невалиден
    """
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Token required")
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Authentication token required"
        )
    
    should_close_db = False
    if db is None:
        db = SessionLocal()
        should_close_db = True
    
    try:
        payload = verify_token(token, expected_token_type="any")
        phone_number = payload.get("sub")
        
        if not phone_number:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Invalid token payload"
            )
            raise WebSocketException(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Invalid token payload"
            )
        
        user = db.query(User).filter(
            User.phone_number == phone_number,
            User.is_active == True
        ).first()
        
        if user is None:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="User not found or inactive"
            )
            raise WebSocketException(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="User not found or inactive"
            )
        
        token_row = (
            db.query(TokenRecord)
            .filter(
                TokenRecord.user_id == user.id,
                TokenRecord.token_type.in_(["access", "refresh"]),
                TokenRecord.token == token,
            )
            .first()
        )
        
        if token_row is None:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Token not found in database"
            )
            raise WebSocketException(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Token not found in database"
            )
        
        token_row.last_used_at = get_local_time()
        db.add(token_row)
        db.commit()
        
        logger.info(f"WebSocket authenticated: user_id={user.id}, phone={user.phone_number}")
        return user
        
    except WebSocketException:
        raise
    except Exception as e:
        logger.error(f"WebSocket authentication error: {e}")
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Authentication failed"
        )
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Authentication failed"
        )
    finally:
        if should_close_db:
            db.close()

