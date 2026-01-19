import os
import uuid
import time
from uuid import uuid4

from fastapi import UploadFile, HTTPException


async def save_file(file: UploadFile, user_id: uuid.UUID, UPLOAD_DIR: str) -> str:
    """
    Сохраняет файл и возвращает путь к нему
    """
    save_file_start = time.time()
    print(f"[SAVE_FILE] START: filename={file.filename}, user_id={user_id}, dir={UPLOAD_DIR}")
    
    # Создаем директорию для документов если её нет
    mkdir_start = time.time()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    print(f"[SAVE_FILE] mkdir took {time.time() - mkdir_start:.3f}s")

    # Генерируем уникальное имя файла
    file_extension = os.path.splitext(file.filename)[1]
    unique_filename = f"{user_id}_{uuid4()}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    print(f"[SAVE_FILE] Generated file_path: {file_path}")

    # Сохраняем файл
    read_start = time.time()
    content = await file.read()
    read_duration = time.time() - read_start
    print(f"[SAVE_FILE] File read took {read_duration:.3f}s, size={len(content)} bytes")
    
    write_start = time.time()
    with open(file_path, "wb") as buffer:
        buffer.write(content)
    write_duration = time.time() - write_start
    print(f"[SAVE_FILE] File write took {write_duration:.3f}s")

    total_duration = time.time() - save_file_start
    print(f"[SAVE_FILE] TOTAL took {total_duration:.3f}s")

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
