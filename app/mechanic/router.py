from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Query
from pydantic import BaseModel, constr, Field, conint
from sqlalchemy import or_
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Dict, Any, Optional

from app.auth.dependencies.get_current_user import get_current_mechanic
from app.dependencies.database.database import get_db
from app.mechanic.utils import isoformat_or_none, _handle_photos, add_review_if_exists
from app.models.history_model import RentalType, RentalStatus, RentalHistory, RentalReview
from app.models.car_model import Car
from app.models.user_model import User
from app.push.utils import send_push_notification_async
from app.rent.utils.calculate_price import get_open_price

MechanicRouter = APIRouter(tags=["Mechanic"], prefix="/mechanic")


@MechanicRouter.get(
    "/all_vehicles",
    summary="Список всех автомобилей со всеми статусами (без схем)"
)
def get_all_vehicles_plain(
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic),
) -> Dict[str, Any]:
    try:
        cars: List[Car] = db.query(Car).all()
        vehicles_data: List[Dict[str, Any]] = []

        for car in cars:
            # по умолчанию нет активной аренды
            car_dict: Dict[str, Any] = {
                "id": car.id,
                "name": car.name,
                "plate_number": car.plate_number,
                "latitude": car.latitude,
                "longitude": car.longitude,
                "course": car.course,
                "fuel_level": car.fuel_level,
                "price_per_minute": car.price_per_minute,
                "price_per_hour": car.price_per_hour,
                "price_per_day": car.price_per_day,
                "engine_volume": car.engine_volume,
                "year": car.year,
                "drive_type": car.drive_type,
                "photos": car.photos,
                "description": car.description,
                "owner_id": car.owner_id,
                "current_renter_id": car.current_renter_id,
                "status": car.status,
                "open_price": get_open_price(car),
                "owned_car": False,
                "current_renter_details": None,
                "rental_id": None,  # поле всегда есть
            }

            # ищем последнюю активную аренду (IN_USE или DELIVERING)
            if car.status.lower() in (
                    "in_use",
                    "delivering"
            ):
                active = (
                    db.query(RentalHistory)
                    .filter(
                        RentalHistory.car_id == car.id,
                        RentalHistory.rental_status.in_([
                            RentalStatus.IN_USE,
                            RentalStatus.DELIVERING
                        ])
                    )
                    .order_by(RentalHistory.start_time.desc())
                    .first()
                )
                if active:
                    car_dict["rental_id"] = active.id

            # если машина в использовании — добавляем детали арендатора
            if car.status.lower() == "in_use" and car.current_renter_id:
                renter: Optional[User] = db.query(User).get(car.current_renter_id)
                if renter:
                    last_rent = (
                        db.query(RentalHistory)
                        .filter(
                            RentalHistory.car_id == car.id,
                            RentalHistory.user_id == renter.id,
                            RentalHistory.rental_status == RentalStatus.IN_USE,
                        )
                        .order_by(RentalHistory.start_time.desc())
                        .first()
                    )
                    rent_selfie_url: Optional[str] = None
                    if last_rent and last_rent.photos_before:
                        rent_selfie_url = next(
                            (p for p in last_rent.photos_before if "/selfie/" in p or "\\selfie\\" in p),
                            last_rent.photos_before[0],
                        )

                    car_dict["current_renter_details"] = {
                        "full_name": renter.full_name,
                        "phone_number": renter.phone_number,
                        "selfie_url": renter.selfie_with_license_url,
                        "rent_selfie_url": rent_selfie_url,
                    }

            vehicles_data.append(car_dict)

        return {"vehicles": vehicles_data}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при получении всех автомобилей: {e}"
        )


@MechanicRouter.get("/get_pending_vehicles")
def get_pending_vehicles(
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Возвращает список машин со статусом PENDING.
    """
    try:
        cars = db.query(Car).filter(Car.status == "PENDING").all()
        vehicles_data = [{
            "id": car.id,
            "name": car.name,
            "plate_number": car.plate_number,
            "latitude": car.latitude,
            "longitude": car.longitude,
            "course": car.course,
            "fuel_level": car.fuel_level,
            "price_per_minute": car.price_per_minute,
            "price_per_hour": car.price_per_hour,
            "price_per_day": car.price_per_day,
            "engine_volume": car.engine_volume,
            "year": car.year,
            "drive_type": car.drive_type,
            "photos": car.photos,
            "owner_id": car.owner_id,
            "current_renter_id": car.current_renter_id,
            "status": car.status,
            "open_price": get_open_price(car),
            "owned_car": False  # для механика это не имеет значения
        } for car in cars]
        return {"vehicles": vehicles_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при получении данных об автомобилях: {str(e)}")


@MechanicRouter.get("/get_in_use_vehicles")
def get_in_use_vehicles(
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Список машин со статусом IN_USE.
    Дополнительно:
      • current_renter_details:
          - full_name
          - phone_number
          - selfie_url              (профильное селфи пользователя)
          - rent_selfie_url         (селфи, снятое перед арендой - из photos_before)
    """
    try:
        cars = db.query(Car).filter(Car.status == "IN_USE").all()
        vehicles_data: list[dict[str, Any]] = []

        for car in cars:
            car_data = {
                "id": car.id,
                "name": car.name,
                "plate_number": car.plate_number,
                "latitude": car.latitude,
                "longitude": car.longitude,
                "course": car.course,
                "fuel_level": car.fuel_level,
                "price_per_minute": car.price_per_minute,
                "price_per_hour": car.price_per_hour,
                "price_per_day": car.price_per_day,
                "engine_volume": car.engine_volume,
                "year": car.year,
                "drive_type": car.drive_type,
                "photos": car.photos,
                "owner_id": car.owner_id,
                "current_renter_id": car.current_renter_id,
                "status": car.status,
                "open_price": get_open_price(car),
                "owned_car": False
            }

            # --- данные арендатора + селфи перед арендой -------------------
            renter_info = None
            if car.current_renter_id:
                current_renter: User | None = (
                    db.query(User).filter(User.id == car.current_renter_id).first()
                )

                if current_renter:
                    # ищем последнюю активную аренду этого авто
                    last_rental = (
                        db.query(RentalHistory)
                        .filter(
                            RentalHistory.car_id == car.id,
                            RentalHistory.user_id == current_renter.id,
                            RentalHistory.rental_status == RentalStatus.IN_USE,
                        )
                        .order_by(RentalHistory.start_time.desc())  # на случай нескольких аренд подряд
                        .first()
                    )

                    rent_selfie_url: str | None = None
                    if last_rental and last_rental.photos_before:
                        rent_selfie_url = next(
                            (
                                p
                                for p in last_rental.photos_before
                                if "/selfie/" in p or "\\selfie\\" in p
                            ),
                            last_rental.photos_before[0],
                        )

                    renter_info = {
                        "full_name": current_renter.full_name,
                        "phone_number": current_renter.phone_number,
                        "selfie_url": current_renter.selfie_with_license_url,
                        "rent_selfie_url": rent_selfie_url,
                    }

            car_data["current_renter_details"] = renter_info
            vehicles_data.append(car_data)

        return {"vehicles": vehicles_data}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при получении данных об автомобилях: {e}",
        )


@MechanicRouter.get("/search")
def search_vehicles(
        query: str = Query(..., description="Поисковый запрос по названию авто или номеру"),
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Ищет автомобили по имени или номеру, но возвращает только машины со статусом IN_USE или PENDING.
    Для автомобилей со статусом IN_USE дополнительно возвращаются данные текущего арендатора (full_name, phone_number, URL селфи).
    """
    try:
        cars = db.query(Car).filter(
            or_(
                Car.name.ilike(f"%{query}%"),
                Car.plate_number.ilike(f"%{query}%")
            ),
            Car.status.in_(["IN_USE", "PENDING"])
        ).all()

        vehicles_data = []
        for car in cars:
            car_data = {
                "id": car.id,
                "name": car.name,
                "plate_number": car.plate_number,
                "latitude": car.latitude,
                "longitude": car.longitude,
                "course": car.course,
                "fuel_level": car.fuel_level,
                "price_per_minute": car.price_per_minute,
                "price_per_hour": car.price_per_hour,
                "price_per_day": car.price_per_day,
                "engine_volume": car.engine_volume,
                "year": car.year,
                "drive_type": car.drive_type,
                "photos": car.photos,
                "owner_id": car.owner_id,
                "current_renter_id": car.current_renter_id,
                "status": car.status,
                "open_price": get_open_price(car),
                "owned_car": False
            }
            if car.status == "IN_USE" and car.current_renter_id:
                current_renter = db.query(User).filter(User.id == car.current_renter_id).first()
                if current_renter:
                    car_data["current_renter_details"] = {
                        "full_name": current_renter.full_name,
                        "phone_number": current_renter.phone_number,
                        "selfie_url": current_renter.selfie_with_license_url
                    }
                else:
                    car_data["current_renter_details"] = None
            else:
                car_data["current_renter_details"] = None

            vehicles_data.append(car_data)

        return {"vehicles": vehicles_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка поиска авто: {str(e)}")


# ----------------------- ENDPOINTS для аренды (проверки автомобиля механиком) -----------------------

@MechanicRouter.post("/check-car/{car_id}")
async def check_car(
        car_id: int,
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Инициация проверки автомобиля механиком.
    Аналогично резервированию, но без оплаты – всё бесплатно.
    При проверке статус машины меняется на SERVICE.
    """
    # Проверяем, нет ли у механика активной проверки (резервированной или в работе)
    active_rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_mechanic.id,
        RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
    ).first()
    if active_rental:
        raise HTTPException(
            status_code=400,
            detail="У вас уже есть активная проверка автомобиля. Завершите её, прежде чем начать новую."
        )
    # Выбираем автомобиль только если его статус PENDING
    car = db.query(Car).filter(Car.id == car_id, Car.status == "PENDING").first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден или недоступен для проверки")
    # Создаём запись проверки (аренды) – всё бесплатно
    rental = RentalHistory(
        user_id=current_mechanic.id,
        car_id=car.id,
        rental_type=RentalType.MINUTES,  # тип аренды может быть любым, платежей нет
        duration=None,
        rental_status=RentalStatus.RESERVED,
        start_latitude=car.latitude,
        start_longitude=car.longitude,
        total_price=0,
        reservation_time=datetime.utcnow()
    )
    db.add(rental)
    db.commit()
    db.refresh(rental)
    # Обновляем автомобиль: закрепляем проверяющего механика и меняем статус на SERVICE
    car.current_renter_id = current_mechanic.id
    car.status = "SERVICE"
    db.commit()
    return {
        "message": "Проверка автомобиля начата успешно",
        "rental_id": rental.id,
        "reservation_time": isoformat_or_none(rental.reservation_time)
    }


@MechanicRouter.post("/start")
async def start_rental(
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Старт проверки автомобиля (смена статуса аренды с RESERVED на IN USE).
    Всё бесплатно – списания не производится.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_mechanic.id,
        RentalHistory.rental_status == RentalStatus.RESERVED
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Нет активной проверки для старта")
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    rental.fuel_before = car.fuel_level
    rental.mileage_before = car.mileage

    rental.start_time = datetime.utcnow()
    rental.rental_status = RentalStatus.IN_USE
    # Для механика переводим автомобиль в состояние IN USE (или оставляем SERVICE, если требуется)
    car.status = "IN_USE"
    db.commit()
    return {"message": "Проверка автомобиля запущена", "rental_id": rental.id}


@MechanicRouter.post("/cancel")
async def cancel_reservation(
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Отмена проверки автомобиля.
    Для механика всё бесплатно, и при отмене статус автомобиля сбрасывается в PENDING.
    Работает только для аренды в статусе RESERVED.
    """
    try:
        # Блокируем запись аренды для обновления, чтобы избежать гонок при конкурентных запросах.
        rental = db.query(RentalHistory).filter(
            RentalHistory.user_id == current_mechanic.id,
            RentalHistory.rental_status == RentalStatus.RESERVED
        ).with_for_update().first()
        if not rental:
            raise HTTPException(status_code=400, detail="Нет активной брони для отмены")

        # Получаем автомобиль и блокируем его запись
        car = db.query(Car).filter(Car.id == rental.car_id).with_for_update().first()
        if not car:
            raise HTTPException(status_code=404, detail="Автомобиль не найден")

        now = datetime.utcnow()
        # Если время старта ещё не установлено, устанавливаем его, но не коммитим отдельно
        if not rental.start_time:
            rental.start_time = rental.reservation_time or now

        # Обновляем статус аренды и автомобиля, а также вычисляем итоговую стоимость
        rental.rental_status = RentalStatus.COMPLETED
        rental.end_time = now
        rental.total_price = 0
        rental.already_payed = 0
        car.current_renter_id = None
        car.status = "PENDING"  # Возвращаем статус автомобиля в PENDING

        # Пытаемся зафиксировать все изменения одним commit
        db.commit()

        minutes_used = int((now - rental.start_time).total_seconds() / 60)
        return {
            "message": "Проверка автомобиля отменена",
            "minutes_used": minutes_used
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка при отмене проверки: {str(e)}")


# ----------------------- Эндпоинты для загрузки фотографий -----------------------


@MechanicRouter.post("/upload-photos-before")
async def upload_photos_before(
        selfie: UploadFile = File(...),
        car_photos: List[UploadFile] = File(...),
        interior_photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Загрузка фотографий до начала проверки автомобиля:
    - selfie: фото механика с машиной;
    - car_photos: 1–10 внешних фото;
    - interior_photos: 1–10 фото салона.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_mechanic.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Нет активной проверки (IN_USE)")

    try:
        urls = await _handle_photos(selfie, car_photos, interior_photos, rental.id, "before")
        rental.photos_before = urls
        db.commit()
        return {"message": "Фотографии до проверки загружены", "photo_count": len(urls)}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Ошибка при загрузке фотографий до проверки")


@MechanicRouter.post("/upload-photos-after")
async def upload_photos_after(
        selfie: UploadFile = File(...),
        car_photos: List[UploadFile] = File(...),
        interior_photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Загрузка фотографий после завершения проверки автомобиля:
    - selfie: фото механика с машиной;
    - car_photos: 1–10 внешних фото;
    - interior_photos: 1–10 фото салона.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_mechanic.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Нет активной проверки (IN_USE)")

    try:
        urls = await _handle_photos(selfie, car_photos, interior_photos, rental.id, "after")
        rental.photos_after = urls
        db.commit()
        return {"message": "Фотографии после проверки загружены", "photo_count": len(urls)}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Ошибка при загрузке фотографий после проверки")


# ----------------------- Завершение проверки (complete) -----------------------

class RentalReviewInput(BaseModel):
    rating: conint(ge=1, le=5) = Field(..., description="Оценка от 1 до 5")
    comment: Optional[constr(max_length=255)] = Field(None, description="Комментарий к проверке (до 255 символов)")


@MechanicRouter.post("/complete")
async def complete_rental(
        review_input: RentalReviewInput,
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Завершает проверку автомобиля.
    Снимается текущая проверка, статус аренды меняется на COMPLETED, а статус автомобиля – на FREE.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_mechanic.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Нет активной проверки для завершения")
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    rental.fuel_after = car.fuel_level
    rental.mileage_after = car.mileage

    now = datetime.utcnow()
    rental.end_time = now
    rental.end_latitude = car.latitude
    rental.end_longitude = car.longitude
    # Для механика всё бесплатно
    rental.total_price = 0
    rental.already_payed = 0
    rental.rental_status = RentalStatus.COMPLETED
    car.current_renter_id = None
    # При успешном завершении проверки автомобиль снова становится доступным (FREE)
    car.status = "FREE"
    add_review_if_exists(db, rental.id, review_input)
    try:
        db.commit()
        return {
            "message": "Проверка автомобиля успешно завершена",
            "rental_details": {
                "total_duration_minutes": int((now - rental.start_time).total_seconds() / 60),
                "final_total_price": rental.total_price
            },
            "review": {
                "rating": review_input.rating,
                "comment": review_input.comment
            }
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка при завершении проверки: {str(e)}")
