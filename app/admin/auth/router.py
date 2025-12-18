from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from decimal import Decimal
import traceback

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.core.config import logger


admin_auth_router = APIRouter(tags=["Admin Auth"])


class AdminProfileUpdateSchema(BaseModel):
    """Данные, которые админ может изменить в своём профиле."""
    phone_number: Optional[str] = Field(None, description="Новый номер телефона администратора")
    email: Optional[str] = Field(None, description="Новый email администратора")
    first_name: Optional[str] = Field(None, description="Имя")
    last_name: Optional[str] = Field(None, description="Фамилия")
    middle_name: Optional[str] = Field(None, description="Отчество")
    birth_date: Optional[datetime] = Field(
        None,
        description="Дата рождения (ISO формат, например 1990-01-01)"
    )
    wallet_balance: Optional[Decimal] = Field(
        None,
        description="Баланс кошелька администратора"
    )


@admin_auth_router.get("/user/me")
async def admin_read_users_me(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Эндпоинт профиля администратора
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    try:
        from app.utils.user_data import get_user_me_data
        return await get_user_me_data(db, current_user)
    except HTTPException as e:
        if e.status_code in [401, 403]:
            raise e
        else:
            raise HTTPException(status_code=401, detail="Authentication failed")
    except Exception as e:
        logger.error(f"Error in /admin/auth/user/me: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal Server Error")


@admin_auth_router.patch("/user/me")
async def admin_update_profile(
        payload: AdminProfileUpdateSchema,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Обновление профиля администратора (phone_number, email, ФИО, birth_date, wallet_balance).
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    if payload.phone_number and payload.phone_number != current_user.phone_number:
        existing = (
            db.query(User)
            .filter(User.phone_number == payload.phone_number)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Пользователь с таким номером телефона уже существует"
            )

    if payload.phone_number is not None:
        current_user.phone_number = payload.phone_number
    if payload.email is not None:
        current_user.email = payload.email
    if payload.first_name is not None:
        current_user.first_name = payload.first_name
    if payload.last_name is not None:
        current_user.last_name = payload.last_name
    if payload.middle_name is not None:
        current_user.middle_name = payload.middle_name
    if payload.birth_date is not None:
        current_user.birth_date = payload.birth_date
    if payload.wallet_balance is not None:
        current_user.wallet_balance = payload.wallet_balance

    try:
        db.add(current_user)
        db.commit()
        db.refresh(current_user)

        from app.utils.user_data import get_user_me_data
        return await get_user_me_data(db, current_user)
    except Exception as e:
        db.rollback()
        logger.error(f"Error in PATCH /admin/auth/user/me: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal Server Error")

