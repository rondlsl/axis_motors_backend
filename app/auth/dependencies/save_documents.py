import os
from uuid import uuid4

from fastapi import UploadFile


async def save_file(file: UploadFile, user_id: int, UPLOAD_DIR: str) -> str:
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
