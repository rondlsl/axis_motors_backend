"""
Утилиты для атомарных операций с автоматическим откатом
"""
from app.core.logging_config import get_logger
logger = get_logger(__name__)

from typing import List, Optional, Callable, Any
from sqlalchemy.orm import Session
from contextlib import contextmanager


def delete_uploaded_files(file_urls: List[str]) -> None:
    """
    Удаляет загруженные файлы из MinIO.
    
    Args:
        file_urls: Список URL файлов для удаления
    """
    from app.services.minio_service import delete_minio_files
    delete_minio_files(file_urls)


@contextmanager
def atomic_upload_transaction(db: Session, uploaded_files: Optional[List[str]] = None):
    """
    Context manager для атомарных операций с загрузкой файлов в MinIO.
    При ошибке автоматически удаляет загруженные файлы и откатывает транзакцию БД.
    
    Usage:
        uploaded_files = []
        with atomic_upload_transaction(db, uploaded_files):
            # Сохраняем файлы
            url = await save_file(...)
            uploaded_files.append(url)
            
            # Обновляем БД
            rental.photos = uploaded_files
            
            # Выполняем GPS команды
            result = await execute_gps_sequence(...)
            if not result["success"]:
                raise Exception("GPS command failed")
            
            # Если всё успешно, коммитим
            db.commit()
    """
    if uploaded_files is None:
        uploaded_files = []
    
    try:
        yield uploaded_files
    except Exception as e:
        logger.error(f" in atomic transaction, rolling back...")
        logger.debug(f"Exception: {type(e).__name__}: {str(e)}")
        
        db.rollback()
        delete_uploaded_files(uploaded_files)
        
        raise


async def atomic_operation_with_gps(
    db: Session,
    save_files_fn: Callable[[], Any],
    update_db_fn: Callable[[List[str]], None],
    gps_fn: Optional[Callable[[], Any]] = None,
    cleanup_on_error: bool = True
) -> dict:
    """
    Выполняет атомарную операцию: сохранение файлов в MinIO → обновление БД → GPS команды.
    При ошибке откатывает все изменения.
    
    Args:
        db: Сессия базы данных
        save_files_fn: Async функция для сохранения файлов, возвращает список URL
        update_db_fn: Функция для обновления БД, принимает список URL
        gps_fn: Опциональная async функция для выполнения GPS команд
        cleanup_on_error: Удалять ли файлы при ошибке
        
    Returns:
        dict: {"success": True, "file_count": N} или {"success": False, "error": "..."}
        
    Raises:
        Exception: Перебрасывает исключение после отката
    """
    uploaded_files = []
    
    try:
        uploaded_files = await save_files_fn()
        
        update_db_fn(uploaded_files)
        
        if gps_fn:
            gps_result = await gps_fn()
            if isinstance(gps_result, dict) and not gps_result.get("success"):
                raise Exception(f"GPS sequence failed: {gps_result.get('error', 'Unknown error')}")
        
        db.commit()
        
        return {"success": True, "file_count": len(uploaded_files)}
        
    except Exception as e:
        logger.error(f" in atomic operation: {type(e).__name__}: {str(e)}")
        db.rollback()
        
        if cleanup_on_error and uploaded_files:
            delete_uploaded_files(uploaded_files)
        
        raise
