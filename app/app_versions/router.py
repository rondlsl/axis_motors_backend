from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User
from app.models.app_version_model import AppVersion
from app.app_versions.schemas import AppVersionCreate, AppVersionResponse
from app.utils.short_id import uuid_to_sid

router = APIRouter(prefix="/app-versions", tags=["app-versions"])


@router.post("/", response_model=AppVersionResponse, status_code=status.HTTP_201_CREATED)
async def create_app_version(
    app_version_data: AppVersionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Создать или обновить запись о последних версиях приложения.
    Если запись уже существует, она будет обновлена.
    """
    existing = db.query(AppVersion).first()
    
    if existing:
        existing.android_version = app_version_data.android_version
        existing.ios_version = app_version_data.ios_version
        existing.ios_link = app_version_data.ios_link
        existing.android_link = app_version_data.android_link
        existing.update_timestamp()
        db.commit()
        db.refresh(existing)
        
        return {
            "id": uuid_to_sid(existing.id),
            "android_version": existing.android_version,
            "ios_version": existing.ios_version,
            "ios_link": existing.ios_link,
            "android_link": existing.android_link,
            "created_at": existing.created_at,
            "updated_at": existing.updated_at
        }
    
    app_version = AppVersion(
        android_version=app_version_data.android_version,
        ios_version=app_version_data.ios_version,
        ios_link=app_version_data.ios_link,
        android_link=app_version_data.android_link
    )
    
    db.add(app_version)
    db.commit()
    db.refresh(app_version)
    
    return {
        "id": uuid_to_sid(app_version.id),
        "android_version": app_version.android_version,
        "ios_version": app_version.ios_version,
        "ios_link": app_version.ios_link,
        "android_link": app_version.android_link,
        "created_at": app_version.created_at,
        "updated_at": app_version.updated_at
    }


@router.get("/", response_model=AppVersionResponse)
async def get_app_version(
    db: Session = Depends(get_db)
):
    """
    Получить последние версии приложения.
    """
    app_version = db.query(AppVersion).first()
    
    if not app_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App version not found"
        )
    
    return {
        "id": uuid_to_sid(app_version.id),
        "android_version": app_version.android_version,
        "ios_version": app_version.ios_version,
        "ios_link": app_version.ios_link,
        "android_link": app_version.android_link,
        "created_at": app_version.created_at,
        "updated_at": app_version.updated_at
    }


@router.delete("/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app_version(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Удалить запись о версиях приложения.
    """
    app_version = db.query(AppVersion).first()
    
    if not app_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App version not found"
        )
    
    db.delete(app_version)
    db.commit()
    
    return None

