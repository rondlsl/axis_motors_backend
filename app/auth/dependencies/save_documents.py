import os
import uuid
from uuid import uuid4

from fastapi import UploadFile, HTTPException


async def save_file(file: UploadFile, user_id: uuid.UUID, UPLOAD_DIR: str) -> str:
    """
    Сохраняет файл и возвращает путь к нему
    """
    # Создаем директорию для документов если её нет
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # Генерируем уникальное имя файла
    file_extension = os.path.splitext(file.filename)[1]
    unique_filename = f"{user_id}_{uuid4()}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)

    # Сохраняем файл
    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)

    return file_path


PHOTO_COUNT_RULE = (1, 10)  # min, max
ALLOWED_TYPES = ["image/jpeg", "image/png"]


def validate_photos(photos: list, field_name: str):
    min_c, max_c = PHOTO_COUNT_RULE
    if len(photos) < min_c or len(photos) > max_c:
        raise HTTPException(status_code=400,
                            detail=f"You must provide between {min_c} and {max_c} files for '{field_name}'"
                            )
    for p in photos:
        if p.content_type not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"File {p.filename} in '{field_name}' is not JPEG or PNG"
            )
