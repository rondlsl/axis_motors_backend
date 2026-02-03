"""Зависимости для support-роутов (избегаем циклических импортов)."""
from fastapi import Depends, HTTPException

from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole


def require_support_role(current_user: User = Depends(get_current_user)) -> User:
    """Проверка, что пользователь имеет роль SUPPORT или ADMIN"""
    if current_user.role not in [UserRole.SUPPORT, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Access denied. Support role required.")
    return current_user


def require_admin_role(current_user: User = Depends(get_current_user)) -> User:
    """Проверка, что пользователь имеет роль ADMIN"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied. Admin role required.")
    return current_user
