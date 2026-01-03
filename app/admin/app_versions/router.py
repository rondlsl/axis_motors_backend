from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.app_version_model import AppVersion
from app.app_versions.schemas import AppVersionResponse
from app.utils.short_id import uuid_to_sid

router = APIRouter(tags=["Admin App Versions"])


class UpdateAIStatusRequest(BaseModel):
    """Схема для обновления статуса AI"""
    ai_is_worked: bool = Field(..., description="Включить/выключить AI")


@router.patch("/ai-status", response_model=AppVersionResponse)
async def update_ai_status(
    request: UpdateAIStatusRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Включить/выключить AI (только для админов)
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав. Только администраторы или техподдержка могут изменять статус AI"
        )
    
    app_version = db.query(AppVersion).first()
    
    if not app_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Конфигурация версий приложения не найдена"
        )
    
    app_version.ai_is_worked = request.ai_is_worked
    app_version.update_timestamp()
    
    db.commit()
    db.refresh(app_version)
    
    return {
        "id": uuid_to_sid(app_version.id),
        "android_version": app_version.android_version,
        "ios_version": app_version.ios_version,
        "ios_link": app_version.ios_link,
        "android_link": app_version.android_link,
        "ai_is_worked": app_version.ai_is_worked,
        "created_at": app_version.created_at,
        "updated_at": app_version.updated_at
    }


@router.get("/ai-status", response_model=AppVersionResponse)
async def get_ai_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Получить текущий статус AI (только для админов)
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав. Только администраторы или техподдержка могут просматривать статус AI"
        )
    
    app_version = db.query(AppVersion).first()
    
    if not app_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Конфигурация версий приложения не найдена"
        )
    
    return {
        "id": uuid_to_sid(app_version.id),
        "android_version": app_version.android_version,
        "ios_version": app_version.ios_version,
        "ios_link": app_version.ios_link,
        "android_link": app_version.android_link,
        "ai_is_worked": app_version.ai_is_worked,
        "created_at": app_version.created_at,
        "updated_at": app_version.updated_at
    }

