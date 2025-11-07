"""
Middleware для автоматического логирования ошибок в Telegram
"""
import traceback
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session

from app.utils.telegram_logger import log_error_to_telegram
from app.auth.security.tokens import verify_token
from app.dependencies.database.database import get_db


class ErrorLoggerMiddleware(BaseHTTPMiddleware):
    """
    Middleware для перехвата всех необработанных исключений
    и отправки информации в Telegram группу мониторинга
    """
    
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except Exception as error:
            # Пытаемся получить информацию о пользователе из токена
            user = None
            try:
                auth_header = request.headers.get("Authorization")
                if auth_header and auth_header.startswith("Bearer "):
                    token = auth_header.split(" ")[1]
                    payload = verify_token(token)
                    
                    if payload:
                        user_id = payload.get("sub")
                        
                        # Получаем пользователя из БД
                        db_gen = get_db()
                        db = next(db_gen)
                        try:
                            from app.models.user_model import User
                            from app.utils.short_id import safe_sid_to_uuid
                            
                            user_uuid = safe_sid_to_uuid(user_id)
                            user = db.query(User).filter(User.id == user_uuid).first()
                        finally:
                            db.close()
            except:
                pass  # Если не удалось получить пользователя, продолжаем без него
            
            # Собираем дополнительный контекст
            additional_context = {}
            
            # Добавляем информацию о теле запроса (если есть)
            try:
                if request.method in ["POST", "PUT", "PATCH"]:
                    # Для безопасности не логируем пароли
                    body = await request.body()
                    if body and len(body) < 1000:  # Только небольшие тела
                        additional_context["request_body_size"] = len(body)
            except:
                pass
            
            # Логируем в Telegram
            try:
                await log_error_to_telegram(
                    error=error,
                    request=request,
                    user=user,
                    additional_context=additional_context
                )
            except Exception as telegram_error:
                print(f"Ошибка отправки в Telegram: {telegram_error}")
            
            # Возвращаем HTTP 500
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "detail": "Internal server error",
                    "error": str(error),
                    "type": type(error).__name__
                }
            )

