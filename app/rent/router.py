from math import floor
from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, status, Query
from pydantic import BaseModel, constr, Field, conint
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional

from app.auth.dependencies.get_current_user import get_current_user
from app.auth.dependencies.save_documents import save_file
from app.dependencies.database.database import get_db
from app.gps_api.utils.get_active_rental import get_open_price
from app.models.history_model import RentalType, RentalStatus, RentalHistory, RentalReview
from app.models.user_model import User, UserRole
from app.models.car_model import Car
from app.rent.utils.calculate_price import calculate_total_price

RentRouter = APIRouter(tags=["Rent"], prefix="/rent")


@RentRouter.get("/history")
def get_trip_history(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> dict:
    """
    Возвращает историю поездок (только завершённые) для текущего пользователя.
    Для каждой поездки возвращаются:
      - history_id: идентификатор истории
      - date: дата завершения поездки (end_time)
      - car_name: название машины
      - final_total_price: итоговая стоимость поездки
    """
    histories = (
        db.query(RentalHistory, Car)
        .join(Car, Car.id == RentalHistory.car_id)
        .filter(
            RentalHistory.user_id == current_user.id,
            RentalHistory.rental_status == RentalStatus.COMPLETED
        )
        .order_by(RentalHistory.end_time.desc())
        .all()
    )

    result = []
    for rental, car in histories:
        result.append({
            "history_id": rental.id,
            "date": rental.end_time.isoformat() if rental.end_time else None,
            "car_name": car.name,
            "final_total_price": rental.total_price
        })

    return {"trip_history": result}


@RentRouter.get("/history/{history_id}")
def get_trip_history_detail(
        history_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> dict:
    """
    Возвращает подробности истории поездки по её идентификатору.
    Выводятся все поля истории, а также данные машины.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.id == history_id,
        RentalHistory.user_id == current_user.id
    ).first()

    if not rental:
        raise HTTPException(status_code=404, detail="Rental history not found")

    car = db.query(Car).filter(Car.id == rental.car_id).first()

    rental_detail = {
        "history_id": rental.id,
        "user_id": rental.user_id,
        "car_id": rental.car_id,
        "rental_type": rental.rental_type.value if hasattr(rental.rental_type, "value") else rental.rental_type,
        "duration": rental.duration,
        "start_latitude": rental.start_latitude,
        "start_longitude": rental.start_longitude,
        "end_latitude": rental.end_latitude,
        "end_longitude": rental.end_longitude,
        "start_time": rental.start_time.isoformat() if rental.start_time else None,
        "end_time": rental.end_time.isoformat() if rental.end_time else None,
        "reservation_time": rental.reservation_time.isoformat() if rental.reservation_time else None,
        "photos_before": rental.photos_before,
        "photos_after": rental.photos_after,
        "already_payed": rental.already_payed,
        "total_price": rental.total_price,
        "rental_status": rental.rental_status.value if hasattr(rental.rental_status, "value") else rental.rental_status,
    }

    if car:
        rental_detail["car_details"] = {
            "name": car.name,
            "plate_number": car.plate_number,
            "fuel_level": car.fuel_level,
            "latitude": car.latitude,
            "longitude": car.longitude,
            "course": car.course,
            "engine_volume": car.engine_volume,
            "drive_type": car.drive_type,
            "year": car.year,
            "status": car.status
        }

    return {"rental_history_detail": rental_detail}


@RentRouter.post("/add_money")
def add_money(amount: int, db: Session = Depends(get_db),
              current_user: User = Depends(get_current_user)):
    current_user.wallet_balance += amount
    db.commit()
    print(current_user.wallet_balance)
    return {"wallet_balance": current_user.wallet_balance}
    # raise HTTPException(status_code=403,
    #                     detail="В настоящее время проводится закрытое бета-тестирование приложения. Пополнение кошелька будет доступно после боевого запуска приложения.")


@RentRouter.post("/reserve-car/{car_id}")
async def reserve_car(
        car_id: int,
        rental_type: RentalType,
        duration: int = None,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    # Проверяем, нет ли у пользователя уже активной аренды
    active_rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
    ).first()
    if active_rental:
        raise HTTPException(
            status_code=400,
            detail="У вас уже есть активная аренда. Завершите текущую аренду, прежде чем бронировать новую машину."
        )

    # Выбираем машину только если она доступна (status == "FREE")
    car = db.query(Car).filter(Car.id == car_id, Car.status == "FREE").first()
    if not car:
        raise HTTPException(status_code=404, detail="Car not found or not available")

    if car.owner_id == current_user.id:
        # Логика для аренды владельцем
        total_price = 0
        rental = RentalHistory(
            user_id=current_user.id,
            car_id=car.id,
            rental_type=rental_type,
            duration=duration,
            rental_status=RentalStatus.RESERVED,
            start_latitude=car.latitude,
            start_longitude=car.longitude,
            total_price=total_price,
            reservation_time=datetime.utcnow()
        )
        db.add(rental)
        db.commit()
        db.refresh(rental)

        # Обновляем машину: устанавливаем текущего арендатора и меняем статус на OWNER
        car.current_renter_id = current_user.id
        car.status = "OWNER"
        db.commit()

        return {
            "message": "Car reserved successfully (owner rental)",
            "rental_id": rental.id,
            "reservation_time": rental.reservation_time.isoformat()
        }
    else:
        # Логика для обычного пользователя
        if rental_type == RentalType.MINUTES:
            if current_user.wallet_balance < car.price_per_hour * 2:
                raise HTTPException(
                    status_code=400,
                    detail=f"У вас на кошельке должно быть минимум {car.price_per_hour * 2} тенге для аренды данного авто."
                )
            total_price = 0
        else:
            if duration is None:
                raise HTTPException(status_code=400, detail="Duration обязателен для аренды по часам или дням.")

            if current_user.wallet_balance < car.price_per_day:
                raise HTTPException(
                    status_code=400,
                    detail=f"У вас на кошельке должно быть минимум {car.price_per_day} тенге для аренды данного авто."
                )

            total_price = calculate_total_price(
                rental_type, duration, car.price_per_hour, car.price_per_day
            )

            if current_user.wallet_balance < total_price:
                raise HTTPException(
                    status_code=400,
                    detail=f"Недостаточно средств. Необходимо: {total_price} тенге"
                )

        rental = RentalHistory(
            user_id=current_user.id,
            car_id=car.id,
            rental_type=rental_type,
            duration=duration,
            rental_status=RentalStatus.RESERVED,
            start_latitude=car.latitude,
            start_longitude=car.longitude,
            total_price=total_price,
            reservation_time=datetime.utcnow()
        )
        db.add(rental)
        db.commit()
        db.refresh(rental)

        # Обновляем машину: устанавливаем текущего арендатора и меняем статус на RESERVED
        car.current_renter_id = current_user.id
        car.status = "RESERVED"
        db.commit()

        return {
            "message": "Car reserved successfully",
            "rental_id": rental.id,
            "reservation_time": rental.reservation_time.isoformat()
        }


# Эндпоинт для резервирования доставки
@RentRouter.post("/reserve-delivery/{car_id}")
async def reserve_delivery(
        car_id: int,
        rental_type: RentalType,
        delivery_latitude: float = Query(..., description="Координата широты доставки"),
        delivery_longitude: float = Query(..., description="Координата долготы доставки"),
        duration: Optional[int] = None,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> dict:
    """
    Резервирование машины с доставкой.
    Принимает car_id, rental_type, координаты доставки и опционально duration.
    Дополнительно списывает 10000 за услугу доставки, если арендатор не является владельцем автомобиля.
    """
    # Проверяем, нет ли у пользователя активной аренды (RESERVED, IN_USE или DELIVERING)
    active_rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE, RentalStatus.DELIVERING])
    ).first()
    if active_rental:
        raise HTTPException(
            status_code=400,
            detail="У вас уже есть активная аренда или заказ доставки."
        )

    # Выбираем машину только если она доступна (status == "FREE")
    car = db.query(Car).filter(Car.id == car_id, Car.status == "FREE").first()
    if not car:
        raise HTTPException(status_code=404, detail="Машина не найдена или не доступна")

    extra_fee = 10000
    total_price = 0

    if car.owner_id == current_user.id:
        # Для владельца доставка бесплатная
        total_price = 0
    else:
        if rental_type == RentalType.MINUTES:
            # Здесь можно установить минимальную проверку баланса (примерно, как в reserve_car)
            if current_user.wallet_balance < car.price_per_hour * 2 + extra_fee:
                raise HTTPException(
                    status_code=400,
                    detail=f"На кошельке должно быть минимум {car.price_per_hour * 2 + extra_fee} тенге для аренды с доставкой."
                )
            total_price = extra_fee  # При минутной аренде только доплата за доставку
        else:
            if duration is None:
                raise HTTPException(status_code=400, detail="Duration обязателен для аренды по часам или дням.")
            base_price = calculate_total_price(rental_type, duration, car.price_per_hour, car.price_per_day)
            total_price = base_price + extra_fee

            if current_user.wallet_balance < total_price:
                raise HTTPException(
                    status_code=400,
                    detail=f"Недостаточно средств. Необходимо: {total_price} тенге"
                )

    # Если пользователь не владелец, списываем доплату за доставку сразу
    if car.owner_id != current_user.id:
        if current_user.wallet_balance < extra_fee:
            raise HTTPException(
                status_code=400,
                detail="Недостаточно средств для доплаты за доставку"
            )
        current_user.wallet_balance -= extra_fee

    rental = RentalHistory(
        user_id=current_user.id,
        car_id=car.id,
        rental_type=rental_type,
        duration=duration,
        rental_status=RentalStatus.DELIVERING,
        start_latitude=car.latitude,
        start_longitude=car.longitude,
        total_price=total_price,
        reservation_time=datetime.utcnow(),
        delivery_latitude=delivery_latitude,
        delivery_longitude=delivery_longitude
    )
    db.add(rental)
    db.commit()
    db.refresh(rental)

    # Обновляем машину: устанавливаем текущего арендатора и меняем статус на "DELIVERING"
    car.current_renter_id = current_user.id
    car.status = "DELIVERING"
    db.commit()

    return {
        "message": "Заказ доставки оформлен успешно",
        "rental_id": rental.id,
        "reservation_time": rental.reservation_time.isoformat(),
        "total_price": rental.total_price
    }


@RentRouter.post("/cancel")
async def cancel_reservation(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Отмена брони (только если аренда в статусе RESERVED).
    Если прошло более 15 минут от начала брони, применяется комиссия за каждую лишнюю минуту – 0.5 * price_per_minute.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.RESERVED
    ).first()

    if not rental:
        raise HTTPException(status_code=400, detail="Нет активной брони для отмены")

    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Машина не найдена")

    now = datetime.utcnow()
    # Если start_time ещё не установлен, используем время бронирования
    if not rental.start_time:
        rental.start_time = rental.reservation_time or datetime.utcnow()
        db.commit()

    if car.owner_id == current_user.id:
        # Логика для владельца: аренда бесплатная, пропускаем комиссии
        rental.rental_status = RentalStatus.COMPLETED
        rental.end_time = now
        rental.total_price = 0
        rental.already_payed = 0
        rental.end_latitude = car.latitude
        rental.end_longitude = car.longitude
        car.current_renter_id = None
        car.status = "FREE"
        db.commit()
        return {
            "message": "Аренда отменена (owner rental)",
            "minutes_used": int((now - rental.start_time).total_seconds() / 60),
            "cancellation_fee": 0,
            "current_wallet_balance": float(current_user.wallet_balance)
        }
    else:
        time_passed = (now - rental.start_time).total_seconds() / 60

        fee = 0
        if time_passed > 15:
            extra_minutes = floor(time_passed - 15)
            fee = int(extra_minutes * car.price_per_minute * 0.5)

            if current_user.wallet_balance < fee:
                raise HTTPException(
                    status_code=400,
                    detail=f"Недостаточно средств для отмены аренды с комиссией: {fee} тг"
                )

            current_user.wallet_balance -= fee

        # Завершаем аренду
        rental.rental_status = RentalStatus.COMPLETED
        rental.end_time = now
        rental.total_price = fee
        rental.already_payed = fee

        # Освобождаем машину и возвращаем статус "FREE"
        car.current_renter_id = None
        car.status = "FREE"

        try:
            db.commit()
            return {
                "message": "Аренда отменена",
                "minutes_used": int(time_passed),
                "cancellation_fee": fee,
                "current_wallet_balance": float(current_user.wallet_balance)
            }
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка при отмене брони: {str(e)}"
            )


@RentRouter.post("/cancel-delivery")
async def cancel_delivery(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Отмена доставки (только если аренда в статусе DELIVERING).
    Деньги за доставку не возвращаем.
    Уведомляем назначенного механика, если он есть.
    """
    # Находим единственную активную доставку пользователя
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.DELIVERING
    ).first()

    if not rental:
        raise HTTPException(status_code=400, detail="Нет активного заказа доставки для отмены")

    # Меняем статус на CANCELLED
    rental.rental_status = RentalStatus.CANCELLED
    # фиксируем время отмены
    rental.end_time = datetime.utcnow()
    db.commit()

    return {"message": "Доставка отменена успешно"}


@RentRouter.post("/start")
async def start_rental(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    # Получаем активную аренду пользователя со статусом RESERVED
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.RESERVED
    ).first()

    if not rental:
        raise HTTPException(status_code=404, detail="No active rental found")

    if rental.rental_status != RentalStatus.RESERVED:
        raise HTTPException(status_code=400, detail="Rental is not in reserved status")

    # Получаем машину по аренде
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    if car.owner_id == current_user.id:
        # Логика для владельца: аренда бесплатная, пропускаем списание средств
        rental.rental_status = RentalStatus.IN_USE
        rental.start_time = datetime.utcnow()
        db.commit()
        return {"message": "Rental started successfully (owner rental)", "rental_id": rental.id}
    else:
        # Если аренда минутная или часовая, списываем с баланса open_price, вычисленный через get_open_price
        if rental.rental_type in [RentalType.MINUTES, RentalType.HOURS]:
            open_price = get_open_price(car)
            current_user.wallet_balance -= open_price

        rental.rental_status = RentalStatus.IN_USE
        rental.start_time = datetime.utcnow()

        total_cost = rental.total_price

        if total_cost > 0:
            if current_user.wallet_balance < total_cost:
                raise HTTPException(status_code=400, detail="Insufficient wallet balance")
            current_user.wallet_balance -= total_cost
            rental.already_payed = total_cost

        # Обновляем машину: меняем статус на IN_USE
        car.status = "IN_USE"

        db.commit()

        return {"message": "Rental started successfully", "rental_id": rental.id}


@RentRouter.post("/upload-photos-before")
async def upload_photos_before(
        selfie: UploadFile = File(...),
        car_photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Загружает фотографии до начала аренды:
    - selfie: фотография пользователя с машиной;
    - car_photos: от 1 до 10 фотографий машины.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()

    if not rental:
        raise HTTPException(status_code=404, detail="No active rental in IN_USE status found")

    if len(car_photos) < 1 or len(car_photos) > 10:
        raise HTTPException(
            status_code=400,
            detail="You must provide between 1 and 10 car photos"
        )

    allowed_types = ["image/jpeg", "image/png"]
    all_photos = [selfie] + car_photos
    for photo in all_photos:
        if photo.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"File {photo.filename} is not an image. Only JPEG and PNG are allowed."
            )

    try:
        photo_urls = []
        selfie_path = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/before/selfie/")
        photo_urls.append(selfie_path)
        for photo in car_photos:
            photo_path = await save_file(photo, rental.id, f"uploads/rents/{rental.id}/before/car/")
            photo_urls.append(photo_path)

        rental.photos_before = photo_urls
        db.commit()

        return {
            "message": "Photos before rental uploaded successfully",
            "photo_count": len(photo_urls)
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="An error occurred while uploading photos"
        )


@RentRouter.post("/upload-photos-after")
async def upload_photos_after(
        selfie: UploadFile = File(...),
        car_photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Загружает фотографии после завершения аренды:
    - selfie: фотография пользователя с машиной;
    - car_photos: от 1 до 10 фотографий машины.
    """
    # Проверяем наличие активной аренды в статусе IN_USE
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()

    if not rental:
        raise HTTPException(status_code=404, detail="No active rental in IN_USE status found")

    if len(car_photos) < 1 or len(car_photos) > 10:
        raise HTTPException(
            status_code=400,
            detail="You must provide between 1 and 10 car photos"
        )

    allowed_types = ["image/jpeg", "image/png"]
    all_photos = [selfie] + car_photos
    for photo in all_photos:
        if photo.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"File {photo.filename} is not an image. Only JPEG and PNG are allowed."
            )

    try:
        photo_urls = []
        selfie_path = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/after/selfie/")
        photo_urls.append(selfie_path)
        for photo in car_photos:
            photo_path = await save_file(photo, rental.id, f"uploads/rents/{rental.id}/after/car/")
            photo_urls.append(photo_path)

        rental.photos_after = photo_urls
        db.commit()

        return {
            "message": "Photos after rental uploaded successfully",
            "photo_count": len(photo_urls)
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="An error occurred while uploading photos"
        )


# Новые эндпоинты для загрузки фотографий без селфи (для владельца)

@RentRouter.post("/upload-photos-before-owner")
async def upload_photos_before_owner(
        car_photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Загружает фотографии до начала аренды для владельца машины (без селфи).
    Принимает только car_photos (от 1 до 10 фотографий машины).
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()

    if not rental:
        raise HTTPException(status_code=404, detail="No active rental in IN_USE status found")

    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car or car.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Это не ваша машина")

    if len(car_photos) < 1 or len(car_photos) > 10:
        raise HTTPException(
            status_code=400,
            detail="You must provide between 1 and 10 car photos"
        )

    allowed_types = ["image/jpeg", "image/png"]
    for photo in car_photos:
        if photo.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"File {photo.filename} is not an image. Only JPEG and PNG are allowed."
            )

    try:
        photo_urls = []
        for photo in car_photos:
            photo_path = await save_file(photo, rental.id, f"uploads/rents/{rental.id}/before/car/")
            photo_urls.append(photo_path)

        rental.photos_before = photo_urls
        db.commit()

        return {
            "message": "Photos before rental uploaded successfully (owner)",
            "photo_count": len(photo_urls)
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="An error occurred while uploading photos"
        )


@RentRouter.post("/upload-photos-after-owner")
async def upload_photos_after_owner(
        car_photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Загружает фотографии после завершения аренды для владельца машины (без селфи).
    Принимает только car_photos (от 1 до 10 фотографий машины).
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()

    if not rental:
        raise HTTPException(status_code=404, detail="No active rental in IN_USE status found")

    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car or car.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Это не ваша машина")

    if len(car_photos) < 1 or len(car_photos) > 10:
        raise HTTPException(
            status_code=400,
            detail="You must provide between 1 and 10 car photos"
        )

    allowed_types = ["image/jpeg", "image/png"]
    for photo in car_photos:
        if photo.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"File {photo.filename} is not an image. Only JPEG and PNG are allowed."
            )

    try:
        photo_urls = []
        for photo in car_photos:
            photo_path = await save_file(photo, rental.id, f"uploads/rents/{rental.id}/after/car/")
            photo_urls.append(photo_path)

        rental.photos_after = photo_urls
        db.commit()

        return {
            "message": "Photos after rental uploaded successfully (owner)",
            "photo_count": len(photo_urls)
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="An error occurred while uploading photos"
        )


class RentalReviewInput(BaseModel):
    rating: conint(ge=1, le=5) = Field(..., description="Оценка от 1 до 5")
    comment: Optional[constr(max_length=255)] = Field(None, description="Комментарий к аренде (до 255 символов)")


@RentRouter.post("/complete")
async def complete_rental(
        review_input: RentalReviewInput,  # если отзыв не обязателен, можно оставить None
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()

    if not rental:
        raise HTTPException(status_code=404, detail="No active rental found")

    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    # общая часть: устанавливаем время, координаты, сбрасываем статус машины
    rental.end_time = datetime.utcnow()
    rental.end_latitude = car.latitude
    rental.end_longitude = car.longitude
    car.current_renter_id = None
    car.status = "PENDING"
    rental.rental_status = RentalStatus.COMPLETED

    # добавляем отзыв, если есть
    if review_input:
        review = RentalReview(
            rental_id=rental.id,
            rating=getattr(review_input, "rating", None),
            comment=getattr(review_input, "comment", None)
        )
        db.add(review)

    if car.owner_id == current_user.id:
        # для владельца аренда бесплатна
        rental.total_price = 0
        rental.already_payed = 0

        try:
            db.commit()
            return {
                "message": "Rental completed successfully (owner rental)",
                "rental_details": {
                    "total_duration_minutes": int((rental.end_time - rental.start_time).total_seconds() / 60),
                    "final_total_price": 0,
                    "amount_charged_now": 0,
                    "current_wallet_balance": float(current_user.wallet_balance)
                },
                "review": {
                    "rating": getattr(review_input, "rating", None),
                    "comment": getattr(review_input, "comment", None)
                } if review_input else None
            }
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while completing the rental: {e}"
            )

    # для обычного пользователя
    actual_duration = rental.end_time - rental.start_time
    actual_minutes = actual_duration.total_seconds() / 60
    additional_charge = 0

    if rental.rental_type == RentalType.MINUTES:
        rental.total_price = int(actual_minutes * car.price_per_minute)
    else:
        if rental.rental_type == RentalType.HOURS:
            planned_duration = rental.duration * 60
            overtime_price = car.price_per_minute
        else:
            planned_duration = rental.duration * 24 * 60
            overtime_price = car.price_per_minute

        overtime_minutes = max(0, actual_minutes - planned_duration)
        if overtime_minutes > 0:
            additional_charge = int(overtime_minutes * overtime_price)
            rental.total_price = (rental.total_price or 0) + additional_charge

    # Считаем сумму, которую нужно списать сейчас
    amount_to_charge = rental.total_price - (rental.already_payed or 0)

    if amount_to_charge > 0:
        # списываем, даже если баланса не хватает — уйдёт в минус
        current_user.wallet_balance -= amount_to_charge
        rental.already_payed = (rental.already_payed or 0) + amount_to_charge

    try:
        db.commit()
        response = {
            "message": "Rental completed successfully",
            "rental_details": {
                "total_duration_minutes": int(actual_minutes),
                "planned_price": (rental.total_price - additional_charge)
                if rental.rental_type != RentalType.MINUTES else None,
                "overtime_charge": additional_charge
                if rental.rental_type != RentalType.MINUTES else None,
                "final_total_price": rental.total_price,
                "amount_charged_now": amount_to_charge,
                "current_wallet_balance": float(current_user.wallet_balance)
            },
            "review": {
                "rating": review.rating,
                "comment": review.comment
            } if review_input else None
        }
        return response
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while completing the rental: {e}"
        )
