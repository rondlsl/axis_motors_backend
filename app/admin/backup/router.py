from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional

from app.core.logging_config import get_logger
from app.auth.dependencies.get_current_user import get_current_user
from app.dependencies.database.database import get_db
from app.models.user_model import User, UserRole
from app.services.backup_service import get_backup_service

logger = get_logger(__name__)

backup_admin_router = APIRouter(tags=["Admin Backup"])


def _ensure_admin(user: User):
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")


@backup_admin_router.post("/backup", status_code=201)
async def create_backup(
    backup_name: Optional[str] = Query(None, description="Имя бэкапа (опционально)"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Создать бэкап базы данных.
    Все бэкапы создаются асинхронно в фоновом режиме.
    """
    _ensure_admin(current_user)
    
    # Асинхронное создание для всех бэкапов
    async def create_backup_task():
        import asyncio
        loop = asyncio.get_event_loop()
        
        def run_backup():
            service = get_backup_service()
            result = service.create_backup(backup_name)
            if result:
                logger.info(f"Background backup created: {result}")
            else:
                logger.error("Background backup failed")
            return result
        
        # Выполняем в отдельном потоке, чтобы не блокировать API
        result = await loop.run_in_executor(None, run_backup)
        return result
    
    # Добавляем в фоновые задачи
    background_tasks.add_task(create_backup_task)
    
    return {
        "message": "Бэкап создаётся в фоновом режиме",
        "status": "in_progress"
    }


@backup_admin_router.get("/backups")
def list_backups(
    limit: int = Query(50, ge=1, le=1000, description="Максимальное количество бэкапов"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Получить список бэкапов."""
    _ensure_admin(current_user)
    
    service = get_backup_service()
    backups = service.list_backups(limit)
    
    return {
        "backups": backups,
        "total": len(backups)
    }


@backup_admin_router.post("/backup/{backup_name}/restore")
async def restore_backup(
    backup_name: str,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Восстановить базу данных из бэкапа.
    ОПАСНО: эта операция перезапишет текущую базу данных!
    """
    _ensure_admin(current_user)
    
    # Асинхронное восстановление в фоновом режиме
    async def restore_task():
        import asyncio
        loop = asyncio.get_event_loop()
        
        def run_restore():
            service = get_backup_service()
            success = service.restore_backup(backup_name)
            if success:
                logger.info(f"Database restored from backup: {backup_name}")
            else:
                logger.error(f"Failed to restore database from backup: {backup_name}")
            return success
        
        # Выполняем в отдельном потоке, чтобы не блокировать API
        result = await loop.run_in_executor(None, run_restore)
        return result
    
    background_tasks.add_task(restore_task)
    
    return {
        "message": f"Восстановление из бэкапа '{backup_name}' запущено в фоновом режиме",
        "warning": "ОПАСНО: текущая база данных будет перезаписана!",
        "status": "in_progress"
    }


@backup_admin_router.delete("/backup/{backup_name}")
def delete_backup(
    backup_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Удалить бэкап."""
    _ensure_admin(current_user)
    
    service = get_backup_service()
    success = service.delete_backup(backup_name)
    
    if not success:
        raise HTTPException(status_code=404, detail="Бэкап не найден или ошибка удаления")
    
    return {
        "message": f"Бэкап '{backup_name}' успешно удален"
    }


@backup_admin_router.post("/backups/cleanup")
def cleanup_old_backups(
    keep_count: int = Query(30, ge=1, le=1000, description="Сколько последних бэкапов оставить"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Удалить старые бэкапы, оставив только последние N.
    """
    _ensure_admin(current_user)
    
    service = get_backup_service()
    deleted_count = service.cleanup_old_backups(keep_count)
    
    return {
        "message": f"Очистка завершена",
        "deleted_count": deleted_count,
        "kept_count": keep_count
    }
