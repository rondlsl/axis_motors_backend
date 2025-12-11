from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from packaging import version

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User
from app.models.app_version_model import AppVersion
from app.models.user_device_model import UserDevice
from app.app_versions.schemas import AppVersionCreate, AppVersionResponse, CheckVersionRequest, CheckVersionResponse
from app.utils.short_id import uuid_to_sid

router = APIRouter(prefix="/app-versions", tags=["app-versions"])


def compare_versions(current: str, latest: str) -> bool:
    """
    Сравнивает версии приложений.
    Возвращает True если current < latest (требуется обновление).
    """
    try:
        return version.parse(current) < version.parse(latest)
    except Exception:
        # Если не удается распарсить версии, считаем что обновление нужно
        return current != latest


@router.post("/check-version", response_model=CheckVersionResponse)
async def check_app_version(
    request: CheckVersionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Проверить версию приложения пользователя.
    
    - Игнорирует web платформу
    - Проверяет версию в user_device
    - Сравнивает с последней версией в app_versions
    - Возвращает информацию о необходимости обновления и ссылку
    """
    # Игнорируем web платформу
    if request.platform.lower() == "web":
        return CheckVersionResponse(
            needs_update=False,
            current_version=None,
            latest_version=None,
            update_link=None,
            message="Web platform does not require version check"
        )
    
    # Нормализуем платформу
    platform = request.platform.lower()
    if platform not in ["ios", "android"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid platform: {request.platform}. Must be 'ios' or 'android'"
        )
    
    # Получаем последние версии приложения
    app_version = db.query(AppVersion).first()
    if not app_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App version configuration not found"
        )
    
    # Определяем актуальную версию и ссылку в зависимости от платформы
    if platform == "ios":
        latest_version = app_version.ios_version
        update_link = app_version.ios_link
    else:  # android
        latest_version = app_version.android_version
        update_link = app_version.android_link
    
    if not latest_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Latest version for {platform} not configured"
        )
    
    # Получаем устройство пользователя
    user_device = db.query(UserDevice).filter(
        UserDevice.user_id == current_user.id,
        UserDevice.platform == platform,
        UserDevice.is_active == True
    ).order_by(UserDevice.updated_at.desc()).first()
    
    # Если устройство не найдено в базе
    if not user_device or not user_device.app_version:
        return CheckVersionResponse(
            needs_update=True,
            current_version=request.app_version,
            latest_version=latest_version,
            update_link=update_link,
            message="Необходимо обновить приложение до последней версии"
        )
    
    # Сравниваем версии
    current_version = user_device.app_version
    needs_update = compare_versions(current_version, latest_version)
    
    return CheckVersionResponse(
        needs_update=needs_update,
        current_version=current_version,
        latest_version=latest_version,
        update_link=update_link if needs_update else None,
        message="Необходимо обновить приложение до последней версии" if needs_update else "У вас установлена последняя версия приложения"
    )


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

