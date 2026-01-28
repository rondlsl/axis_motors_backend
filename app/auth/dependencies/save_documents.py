from app.core.logging_config import get_logger
logger = get_logger(__name__)

import uuid
import time
from typing import List

from fastapi import UploadFile, HTTPException

from app.services.minio_service import save_file_to_minio


async def save_file(file: UploadFile, user_id: uuid.UUID, folder: str) -> str:
    """
    Сохраняет файл в MinIO и возвращает URL.
    
    Args:
        file: FastAPI UploadFile объект
        user_id: UUID пользователя или объекта
        folder: Папка для сохранения (например: "documents", "cars/ABC123")
        
    Returns:
        str: Публичный URL файла в MinIO
    """
    save_file_start = time.time()
    logger.info(f"[SAVE_FILE] START: filename={file.filename}, user_id={user_id}, folder={folder}")
    
    # Нормализуем путь папки (убираем "uploads/" если есть, так как bucket уже называется "uploads")
    normalized_folder = folder
    if normalized_folder.startswith("uploads/"):
        normalized_folder = normalized_folder[8:]  # убираем "uploads/"
    normalized_folder = normalized_folder.strip("/")
    
    # Загружаем в MinIO
    url = await save_file_to_minio(file, user_id, normalized_folder)
    
    total_duration = time.time() - save_file_start
    logger.info(f"[SAVE_FILE] TOTAL took {total_duration:.3f}s, URL: {url}")
    
    return url


PHOTO_COUNT_RULE = (1, 10)  # min, max
ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp", "image/jpg"]


def validate_photos(photos: List[UploadFile], field_name: str):
    """Валидация списка фотографий"""
    min_c, max_c = PHOTO_COUNT_RULE
    if len(photos) < min_c or len(photos) > max_c:
        raise HTTPException(
            status_code=400,
            detail=f"You must provide between {min_c} and {max_c} files for '{field_name}'"
        )
    for p in photos:
        if p.content_type not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"File {p.filename} in '{field_name}' is not JPEG or PNG"
            )
