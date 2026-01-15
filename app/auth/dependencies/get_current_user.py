from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.security.auth_bearer import JWTBearer
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
    # Ищем только активного пользователя
    user = db.query(User).filter(User.phone_number == phone_number, User.is_active == True).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found or inactive")
    # Проверяем, что токен существует в БД (access или refresh)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Token not provided")
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
    # обновляем last_used_at
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
