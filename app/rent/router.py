from fastapi import APIRouter, HTTPException, Depends, File, UploadFile
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List

from app.auth.dependencies.get_current_user import get_current_user
from app.auth.dependencies.save_documents import save_file
from app.dependencies.database.database import get_db
from app.models.history_model import RentalType, RentalStatus, RentalHistory
from app.models.user_model import User
from app.models.car_model import Car

RentRouter = APIRouter()


@RentRouter.post("/reserve-car/{car_id}")
async def reserve_car(
        car_id: int,
        rental_type: RentalType,
        duration: int = None,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    # Получаем автомобиль
    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    # Проверяем баланс пользователя
    if current_user.wallet_balance < car.price_per_day:
        raise HTTPException(status_code=400, detail=f"У вас на кошельке должно быть минимум {car.price_per_day} для аренды данного авто.")

    # Создаем запись аренды
    rental = RentalHistory(
        user_id=current_user.id,
        car_id=car.id,
        rental_type=rental_type,
        duration=duration,
        rental_status=RentalStatus.RESERVED,
        start_latitude=car.latitude,
        start_longitude=car.longitude,
        total_price=(car.price_per_hour * duration if rental_type == RentalType.HOURS else car.price_per_day),
    )

    db.add(rental)
    db.commit()
    db.refresh(rental)

    # Обновляем текущего арендатора автомобиля
    car.current_renter_id = current_user.id
    db.commit()

    return {"message": "Car reserved successfully", "rental_id": rental.id}


@RentRouter.post("/start-rental")
async def start_rental(
        photos_before: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    # Получаем активную аренду пользователя
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status.in_([RentalStatus.RESERVED])
    ).first()

    if not rental:
        raise HTTPException(status_code=404, detail="No active rental found")

    if rental.rental_status != RentalStatus.RESERVED:
        raise HTTPException(status_code=400, detail="Rental is not in reserved status")

    # Проверяем и сохраняем фотографии
    allowed_types = ["image/jpeg", "image/png"]
    photo_urls = []
    for photo in photos_before:
        if photo.content_type not in allowed_types:
            raise HTTPException(status_code=400,
                                detail=f"File {photo.filename} is not an image. Only JPEG and PNG are allowed.")
        photo_path = await save_file(photo, rental.id, "uploads/rents")  # Реализуйте save_file
        photo_urls.append(photo_path)

    rental.photos_before = photo_urls
    rental.rental_status = RentalStatus.IN_USE
    rental.start_time = datetime.utcnow()

    # Рассчитываем стоимость поездки, если тип часов или дней
    if rental.rental_type == RentalType.HOURS:
        total_cost = rental.duration * rental.car.price_per_hour
    elif rental.rental_type == RentalType.DAYS:
        total_cost = rental.car.price_per_day
    else:
        total_cost = 0  # Для поминутного тарифа ничего не рассчитывается

    # Снимаем средства с кошелька
    if total_cost > 0:
        if current_user.wallet_balance < total_cost:
            raise HTTPException(status_code=400, detail="Insufficient wallet balance")
        current_user.wallet_balance -= total_cost

    db.commit()

    return {"message": "Rental started successfully", "rental_id": rental.id}


@RentRouter.post("/upload-photos")
async def upload_photos(
        photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    # Получаем активную аренду пользователя
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()

    if not rental:
        raise HTTPException(status_code=404, detail="No active rental found")

    # Проверяем и сохраняем фотографии
    allowed_types = ["image/jpeg", "image/png"]
    photo_urls = []
    for photo in photos:
        if photo.content_type not in allowed_types:
            raise HTTPException(status_code=400,
                                detail=f"File {photo.filename} is not an image. Only JPEG and PNG are allowed.")
        photo_path = await save_file(photo, rental.id, "uploads/rents")  # Реализуйте save_file
        photo_urls.append(photo_path)

    rental.photos_after = photo_urls
    db.commit()

    return {"message": "Photos uploaded successfully", "rental_id": rental.id}
