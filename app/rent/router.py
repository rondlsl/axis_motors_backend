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
from app.rent.utils.calculate_price import calculate_total_price

RentRouter = APIRouter(tags=["Rent"], prefix="/rent")


def calculate_total_price(rental_type: RentalType, duration: int, price_per_hour: float, price_per_day: float) -> float:
    if rental_type == RentalType.MINUTES:
        return None  # For minutes, total price is not calculated initially
    elif rental_type == RentalType.HOURS:
        return price_per_hour * duration
    else:  # RentalType.DAYS
        return price_per_day * duration


@RentRouter.post("/add_money")
def add_money(amount: int, db: Session = Depends(get_db),
              current_user: User = Depends(get_current_user), ):
    current_user.wallet_balance += amount
    db.commit()
    print(current_user.wallet_balance)
    return {"wallet_balance": current_user.wallet_balance}


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
    if current_user.wallet_balance < car.price_per_hour * 2 and rental_type == RentalType.MINUTES:
        raise HTTPException(status_code=400,
                            detail=f"У вас на кошельке должно быть минимум {car.price_per_hour * 2} тенге для аренды данного авто.")

    if current_user.wallet_balance < car.price_per_day and rental_type != RentalType.MINUTES:
        raise HTTPException(status_code=400,
                            detail=f"У вас на кошельке должно быть минимум {car.price_per_day} тенге для аренды данного авто.")

    # Рассчитываем общую стоимость
    total_price = calculate_total_price(rental_type, duration, car.price_per_hour, car.price_per_day)

    if current_user.wallet_balance < total_price:
        raise HTTPException(status_code=400,
                            detail=f"У вас недостаточно средств для аренды авто на такой период времени.")

    if rental_type in [RentalType.HOURS, RentalType.DAYS]:
        if total_price > current_user.wallet_balance:
            raise HTTPException(status_code=400,
                                detail=f"Недостаточно средств. Необходимо: {total_price} тенге")

    # Создаем запись аренды
    rental = RentalHistory(
        user_id=current_user.id,
        car_id=car.id,
        rental_type=rental_type,
        duration=duration,
        rental_status=RentalStatus.RESERVED,
        start_latitude=car.latitude,
        start_longitude=car.longitude,
        total_price=total_price,
    )

    db.add(rental)
    db.commit()
    db.refresh(rental)

    # Обновляем текущего арендатора автомобиля
    car.current_renter_id = current_user.id
    db.commit()

    return {"message": "Car reserved successfully", "rental_id": rental.id}


@RentRouter.post("/start")
async def start_rental(
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

    if rental.rental_type == RentalType.MINUTES:
        current_user.wallet_balance -= 5000

    rental.rental_status = RentalStatus.IN_USE
    rental.start_time = datetime.utcnow()

    total_cost = rental.total_price

    if total_cost > 0:
        if current_user.wallet_balance < total_cost:
            raise HTTPException(status_code=400, detail="Insufficient wallet balance")
        current_user.wallet_balance -= total_cost
        rental.already_payed = total_cost

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
    Upload photos before starting the rental.
    Requires:
    - selfie: A selfie photo of the user with the car
    - car_photos: 1-10 photos of the car before rental
    """
    # Check if user has an active rental in RESERVED status
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.RESERVED
    ).first()

    if not rental:
        raise HTTPException(status_code=404, detail="No active rental in RESERVED status found")

    # Validate number of car photos
    if len(car_photos) < 1 or len(car_photos) > 10:
        raise HTTPException(
            status_code=400,
            detail="You must provide between 1 and 10 car photos"
        )

    # Check file types
    allowed_types = ["image/jpeg", "image/png"]
    all_photos = [selfie] + car_photos
    for photo in all_photos:
        if photo.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"File {photo.filename} is not an image. Only JPEG and PNG are allowed."
            )

    try:
        # Create list to store photo URLs
        photo_urls = []

        # Save selfie
        selfie_path = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/before/selfie/")
        photo_urls.append(selfie_path)

        # Save car photos
        for photo in car_photos:
            photo_path = await save_file(photo, rental.id, f"uploads/rents/{rental.id}/before/car/")
            photo_urls.append(photo_path)

        # Update rental record
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
    Upload photos after finishing the rental.
    Requires:
    - selfie: A selfie photo of the user with the car
    - car_photos: 1-10 photos of the car after rental
    """
    # Check if user has an active rental in IN_USE status
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()

    if not rental:
        raise HTTPException(status_code=404, detail="No active rental in IN_USE status found")

    # Validate number of car photos
    if len(car_photos) < 1 or len(car_photos) > 10:
        raise HTTPException(
            status_code=400,
            detail="You must provide between 1 and 10 car photos"
        )

    # Check file types
    allowed_types = ["image/jpeg", "image/png"]
    all_photos = [selfie] + car_photos
    for photo in all_photos:
        if photo.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"File {photo.filename} is not an image. Only JPEG and PNG are allowed."
            )

    try:
        # Create list to store photo URLs
        photo_urls = []

        # Save selfie
        selfie_path = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/after/selfie/")
        photo_urls.append(selfie_path)

        # Save car photos
        for photo in car_photos:
            photo_path = await save_file(photo, rental.id, f"uploads/rents/{rental.id}/after/car/")
            photo_urls.append(photo_path)

        # Update rental record
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


@RentRouter.post("/complete")
async def complete_rental(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Complete the rental and calculate final price based on actual usage time.
    Handles different rental types (minutes, hours, days) and calculates overtime charges.
    """
    # Get active rental
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()

    if not rental:
        raise HTTPException(status_code=404, detail="No active rental found")

    # Get car details
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    # Set end time
    rental.end_time = datetime.utcnow()
    actual_duration = rental.end_time - rental.start_time
    actual_minutes = actual_duration.total_seconds() / 60

    additional_charge = 0

    # Calculate charges based on rental type
    if rental.rental_type == RentalType.MINUTES:
        # For minute-based rentals, calculate total price based on actual duration
        rental.total_price = int(actual_minutes * (car.price_per_minute))
        remaining_to_pay = rental.total_price - (rental.already_payed or 0)

    else:
        # For hours and days, calculate overtime charges
        planned_duration = 0
        if rental.rental_type == RentalType.HOURS:
            planned_duration = rental.duration * 60  # convert hours to minutes
            overtime_price = car.price_per_minute
        else:  # DAYS
            planned_duration = rental.duration * 24 * 60  # convert days to minutes
            overtime_price = car.price_per_minute

        # Calculate overtime
        overtime_minutes = max(0, actual_minutes - planned_duration)
        if overtime_minutes > 0:
            additional_charge = int(overtime_minutes * overtime_price)
            rental.total_price = (rental.total_price or 0) + additional_charge

    # Update user's wallet balance
    amount_to_charge = rental.total_price - (rental.already_payed or 0)
    if amount_to_charge > 0:
        current_user.wallet_balance -= amount_to_charge
        rental.already_payed = (rental.already_payed or 0) + amount_to_charge

    # Update rental status and car
    rental.rental_status = RentalStatus.COMPLETED
    car.current_renter_id = None

    try:
        db.commit()
        return {
            "message": "Rental completed successfully",
            "rental_details": {
                "total_duration_minutes": int(actual_minutes),
                "planned_price": rental.total_price - additional_charge if rental.rental_type != RentalType.MINUTES else None,
                "overtime_charge": additional_charge if rental.rental_type != RentalType.MINUTES else None,
                "final_total_price": rental.total_price,
                "amount_charged_now": amount_to_charge,
                "current_wallet_balance": float(current_user.wallet_balance)
            }
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="An error occurred while completing the rental"
        )
