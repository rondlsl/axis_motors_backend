from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.security.auth_bearer import JWTBearer
from app.models.user_model import User, UserRole  # обязательно импортируем UserRole
from app.dependencies.database.database import get_db


async def get_current_user(
        db: Session = Depends(get_db),
        token: str = Depends(JWTBearer(expected_token_type="access"))
):
    phone_number: str = token.get("sub")
    if phone_number is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials"
        )
    user = db.query(User).filter(User.phone_number == phone_number).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
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
    user = db.query(User).filter(User.phone_number == phone_number).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.role != UserRole.MECHANIC:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    return user
