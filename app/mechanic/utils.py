from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session

from app.models.history_model import RentalReview

if TYPE_CHECKING:
    from app.rent.router import RentalReviewInput


def isoformat_or_none(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def validate_photo_count(photos: List[UploadFile], min_count: int = 1, max_count: int = 10):
    if not (min_count <= len(photos) <= max_count):
        raise HTTPException(
            status_code=400,
            detail=f"Необходимо предоставить от {min_count} до {max_count} фотографий автомобиля"
        )


def validate_photo_types(files: List[UploadFile]):
    allowed_types = ["image/jpeg", "image/png"]
    for file in files:
        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"Файл {file.filename} не является изображением. Разрешены JPEG и PNG."
            )


async def process_upload_photos(
        photos: List[UploadFile],
        rental_id: int,
        subfolder: str
) -> List[str]:
    photo_urls = []
    for photo in photos:
        url = await save_file(photo, rental_id, f"uploads/rents/{rental_id}/{subfolder}/")
        photo_urls.append(url)
    return photo_urls


def add_review_if_exists(db: Session, rental_id: int, review_input: Optional["RentalReviewInput"]):
    if review_input:
        # Ищем существующий отзыв для этой аренды
        existing_review = db.query(RentalReview).filter(RentalReview.rental_id == rental_id).first()
        
        if existing_review:
            # Обновляем существующий отзыв, добавляя данные механика
            existing_review.mechanic_rating = review_input.rating
            existing_review.mechanic_comment = review_input.comment
        else:
            # Создаем новый отзыв с данными механика
            # Если поле rating имеет ограничение NOT NULL, устанавливаем значение по умолчанию
            review = RentalReview(
                rental_id=rental_id,
                rating=0,  # Значение по умолчанию для клиентского рейтинга
                comment=None,  # Клиентский комментарий пока отсутствует
                mechanic_rating=review_input.rating,
                mechanic_comment=review_input.comment
            )
            db.add(review)


# Импортируем функцию для сохранения файлов (аналогичная логике из RentRouter)
from app.auth.dependencies.save_documents import save_file, validate_photos


async def _handle_photos(
        selfie: UploadFile,
        car_photos: List[UploadFile],
        interior_photos: List[UploadFile],
        rental_id: int,
        when: str
) -> List[str]:
    # валидация
    validate_photos([selfie], "selfie")
    validate_photos(car_photos, "car_photos")
    validate_photos(interior_photos, "interior_photos")

    # Определяем базовую папку в зависимости от типа загрузки
    if when.startswith("mechanic_"):
        base_dir = f"uploads/rents/{rental_id}/mechanic/{when.replace('mechanic_', '')}"
    else:
        base_dir = f"uploads/rents/{rental_id}/{when}"
    
    urls: List[str] = []

    # сохраняем селфи
    urls.append(await save_file(selfie, rental_id, f"{base_dir}/selfie/"))

    # сохраняем внешние фото
    for p in car_photos:
        urls.append(await save_file(p, rental_id, f"{base_dir}/car/"))

    # сохраняем фото салона
    for p in interior_photos:
        urls.append(await save_file(p, rental_id, f"{base_dir}/interior/"))

    return urls
