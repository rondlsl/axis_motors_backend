from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.security.auth_bearer import JWTBearer
from app.auth.dependencies.token_cache import TokenCache
from app.models.user_model import User, UserRole
from app.models.token_model import TokenRecord
from app.dependencies.database.database import get_db
from app.utils.time_utils import get_local_time


async def get_current_user(
        db: Session = Depends(get_db),
        token: str = Depends(JWTBearer(expected_token_type="any"))
):
    phone_number: str = token.get("sub")
    raw_token: str = token.get("raw_token")
    if phone_number is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials"
        )
    if not raw_token:
        raise HTTPException(status_code=401, detail="Token not provided")

    # === Шаг 1: Проверяем кэш ===
    cached_user_id = await TokenCache.get_token_user_id(raw_token)
    if cached_user_id:
        # Токен найден в кэше - загружаем пользователя по ID
        user = db.query(User).filter(
            User.id == UUID(cached_user_id),
            User.is_active == True
        ).first()
        if user:
            return user
        # Пользователь не найден или неактивен - инвалидируем кэш
        await TokenCache.invalidate_token(raw_token)

    # === Шаг 2: Cache MISS - идем в БД (как раньше) ===
    user = db.query(User).filter(User.phone_number == phone_number, User.is_active == True).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found or inactive")

    # Проверяем, что токен существует в БД (access или refresh)
    token_row = (
        db.query(TokenRecord)
        .filter(
            TokenRecord.user_id == user.id,
            TokenRecord.token_type.in_(["access", "refresh"]),
            TokenRecord.token == raw_token,
        )
        .first()
    )
    if token_row is None:
        raise HTTPException(status_code=401, detail="Token is not valid")

    # === Шаг 3: Кэшируем для следующих запросов ===
    await TokenCache.set_token_user_id(raw_token, user.id)

    # Обновляем last_used_at
    token_row.last_used_at = get_local_time()
    db.add(token_row)
    db.commit()
    return user


async def get_current_mechanic(
        db: Session = Depends(get_db),
        token: str = Depends(JWTBearer(expected_token_type="access"))
):
    phone_number: str = token.get("sub")
    if phone_number is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials"
        )
    # Ищем активного пользователя с заданным номером
    user = db.query(User).filter(User.phone_number == phone_number, User.is_active == True).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found or inactive")

    if user.role != UserRole.MECHANIC:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    return user


async def get_current_accountant(
        db: Session = Depends(get_db),
        token: str = Depends(JWTBearer(expected_token_type="access"))
):
    """Проверяет, что текущий пользователь - бухгалтер"""
    phone_number: str = token.get("sub")
    if phone_number is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials"
        )
    # Ищем активного пользователя с заданным номером
    user = db.query(User).filter(User.phone_number == phone_number, User.is_active == True).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found or inactive")

    if user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Access denied. Accountant role required.")

    return user


async def get_current_support(
        db: Session = Depends(get_db),
        token: str = Depends(JWTBearer(expected_token_type="access"))
):
    """Проверяет, что текущий пользователь — поддержка (SUPPORT)."""
    phone_number: str = token.get("sub")
    if phone_number is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials"
        )
    user = db.query(User).filter(User.phone_number == phone_number, User.is_active == True).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found or inactive")

    if user.role != UserRole.SUPPORT:
        raise HTTPException(status_code=403, detail="Access denied. Support role required.")

    return user
