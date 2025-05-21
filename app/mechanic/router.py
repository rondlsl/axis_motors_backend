from math import floor
from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Query
from pydantic import BaseModel, constr, Field, conint
from sqlalchemy import or_
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Dict, Any, Optional

from app.auth.dependencies.get_current_user import get_current_mechanic
from app.dependencies.database.database import get_db
from app.gps_api.utils.get_active_rental import get_open_price
from app.models.history_model import RentalType, RentalStatus, RentalHistory, RentalReview
from app.models.car_model import Car
from app.models.user_model import User
from app.push.utils import send_push_notification_async

MechanicRouter = APIRouter(tags=["Mechanic"], prefix="/mechanic")


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
        review = RentalReview(
            rental_id=rental_id,
            rating=review_input.rating,
            comment=review_input.comment
        )
        db.add(review)


# Импортируем функцию для сохранения файлов (аналогичная логике из RentRouter)
from app.auth.dependencies.save_documents import save_file, validate_photos


# ----------------------- GET эндпоинты -----------------------

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
) -> Dict[str, Any]:
    """
    Возвращает список машин со статусом IN_USE.
    Если автомобиль в использовании, дополнительно возвращаются данные текущего арендатора:
      - full_name
      - phone_number
      - URL селфи
    """
    try:
        cars = db.query(Car).filter(Car.status == "IN_USE").all()
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
            # Добавляем данные текущего арендатора, если car.current_renter_id указан
            if car.current_renter_id:
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
        raise HTTPException(status_code=500, detail=f"Ошибка при получении данных об автомобилях: {str(e)}")


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


# 1. Получение всех заказов доставки
@MechanicRouter.get("/get-delivery-vehicles")
def get_delivery_vehicles(
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Возвращает список автомобилей, находящихся в аренде с доставкой (статус DELIVERING).
    В список попадают заказы, где доставка ещё не принята (delivery_mechanic_id == None)
    или уже принята текущим механиком.
    """
    deliveries = db.query(RentalHistory).filter(
        RentalHistory.rental_status == RentalStatus.DELIVERING,
        (RentalHistory.delivery_mechanic_id.is_(None)) | (RentalHistory.delivery_mechanic_id == current_mechanic.id)
    ).all()

    vehicles_data: List[Dict[str, Any]] = []
    for rental in deliveries:
        car = db.query(Car).filter(Car.id == rental.car_id).first()
        if not car:
            continue
        vehicles_data.append({
            "rental_id": rental.id,
            "car_id": car.id,
            "car_name": car.name,
            "plate_number": car.plate_number,
            "fuel_level": car.fuel_level,
            "latitude": car.latitude,
            "longitude": car.longitude,
            "course": car.course,
            "engine_volume": car.engine_volume,
            "drive_type": car.drive_type,
            "year": car.year,
            "status": car.status,
            "delivery_coordinates": {
                "latitude": rental.delivery_latitude,
                "longitude": rental.delivery_longitude,
            },
            "reservation_time": rental.reservation_time.isoformat(),
            "delivery_assigned": rental.delivery_mechanic_id is not None
        })

    return {"delivery_vehicles": vehicles_data}


@MechanicRouter.post("/accept-delivery/{rental_id}")
async def accept_delivery(
        rental_id: int,
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Позволяет механику взять заказ доставки.
    Проверяется, что заказ находится в статусе DELIVERING и что другой механик ещё не принял этот заказ.
    Также у механика не может быть более одного активного заказа доставки.
    После успешного приёма отправляет пуш пользователю, что механик в пути.
    """

    # Проверяем, что у механика нет другого активного заказа доставки
    existing_delivery = db.query(RentalHistory).filter(
        RentalHistory.delivery_mechanic_id == current_mechanic.id,
        RentalHistory.rental_status == RentalStatus.DELIVERING
    ).first()
    if existing_delivery:
        raise HTTPException(
            status_code=400,
            detail="У вас уже есть активный заказ доставки."
        )

    rental = db.query(RentalHistory).filter(
        RentalHistory.id == rental_id,
        RentalHistory.rental_status == RentalStatus.DELIVERING
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Заказ доставки не найден")

    if rental.delivery_mechanic_id is not None:
        raise HTTPException(
            status_code=400,
            detail="Заказ уже принят другим механиком."
        )

    # Назначаем механика и сохраняем
    rental.delivery_mechanic_id = current_mechanic.id
    db.commit()
    db.refresh(rental)

    # Отправляем пуш пользователю, который арендовал машину
    user = db.query(User).filter(User.id == rental.user_id).first()
    if user and user.fcm_token:
        title = "Механик в пути"
        body = (
            f"Механик принял заказ доставки и уже едет к вам."
        )
        # асинхронно шлём пуш (не блокируем основной поток)
        await send_push_notification_async(user.fcm_token, title, body)

    return {
        "message": "Заказ доставки успешно принят",
        "rental_id": rental.id
    }


@MechanicRouter.post("/complete-delivery")
async def complete_delivery(
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Механик завершает заказ доставки.
    Находит заказ доставки, принятый текущим механиком, и переводит его в статус RESERVED.
    Отправляет пуш пользователю, что автомобиль приехал и ждёт его.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.delivery_mechanic_id == current_mechanic.id,
        RentalHistory.rental_status == RentalStatus.DELIVERING
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Активный заказ доставки не найден")

    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    now = datetime.utcnow()
    rental.end_time = now
    rental.rental_status = RentalStatus.RESERVED
    car.status = "RESERVED"
    rental.delivery_mechanic_id = None

    db.commit()
    db.refresh(rental)

    # Отправляем пуш пользователю, которому доставили машину
    user = db.query(User).filter(User.id == rental.user_id).first()
    if user and user.fcm_token:
        title = "Машина доставлена"
        body = (
            f"Ваш автомобиль «{car.name}» ({car.plate_number}) "
            "приехал и уже ждёт вас."
        )
        await send_push_notification_async(user.fcm_token, title, body)

    return {
        "message": "Доставка успешно завершена. Автомобиль передан пользователю (статус RESERVED).",
        "rental_id": rental.id
    }


def get_current_delivery(db: Session, current_mechanic: User) -> RentalHistory:
    """
    Возвращает активную доставку для механика (status=DELIVERING и delivery_mechanic_id == current_mechanic.id).
    Если доставки нет – выбрасывает исключение.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.delivery_mechanic_id == current_mechanic.id,
        RentalHistory.rental_status == RentalStatus.DELIVERING
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Активная доставка не найдена")
    return rental


@MechanicRouter.get("/current-delivery", summary="Получить текущую доставку")
def current_delivery(
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Эндпоинт возвращает текущую доставку, назначенную механику,
    включая информацию об автомобиле и координаты доставки.
    """
    rental = get_current_delivery(db, current_mechanic)
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    return {
        "rental_id": rental.id,
        "car_id": car.id,
        "car_name": car.name,
        "plate_number": car.plate_number,
        "fuel_level": car.fuel_level,
        "latitude": car.latitude,
        "longitude": car.longitude,
        "course": car.course,
        "engine_volume": car.engine_volume,
        "drive_type": car.drive_type,
        "year": car.year,
        "delivery_coordinates": {
            "latitude": rental.delivery_latitude,
            "longitude": rental.delivery_longitude,
        },
        "reservation_time": rental.reservation_time.isoformat(),
        "status": rental.rental_status.value
    }


@MechanicRouter.post("/open", summary="Открыть автомобиль (доставка)")
async def open_vehicle_delivery(
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Отправляет команду для открытия автомобиля, связанного с активной доставкой.
    Проверяет, что у текущего механика есть активная доставка и у автомобиля присутствует gps_id.
    """
    rental = get_current_delivery(db, current_mechanic)
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car or not car.gps_id:
        raise HTTPException(status_code=404, detail="Автомобиль или GPS ID не найдены")

    # Пример вызова команды, здесь можно интегрировать реальную логику отправки команды
    # result = await send_command_to_terminal(car.gps_id, "*!CEVT 1", AUTH_TOKEN)
    result = {"status": "command sent"}  # заглушка для примера

    return {"message": "Команда для открытия автомобиля отправлена", "result": result}


@MechanicRouter.post("/close", summary="Закрыть автомобиль (доставка)")
async def close_vehicle_delivery(
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Отправляет команду для закрытия автомобиля в режиме доставки.
    Проверяет наличие активной доставки и корректность GPS ID.
    """
    rental = get_current_delivery(db, current_mechanic)
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car or not car.gps_id:
        raise HTTPException(status_code=404, detail="Автомобиль или GPS ID не найдены")

    # Пример отправки команды
    # result = await send_command_to_terminal(car.gps_id, "*!CEVT 2", AUTH_TOKEN)
    result = {"status": "command sent"}  # заглушка
    return {"message": "Команда для закрытия автомобиля отправлена", "result": result}


@MechanicRouter.post("/give-key", summary="Передать ключ (доставка)")
async def give_key_delivery(
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Отправляет команду на передачу ключа автомобиля в режиме доставки.
    """
    rental = get_current_delivery(db, current_mechanic)
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car or not car.gps_id:
        raise HTTPException(status_code=404, detail="Автомобиль или GPS ID не найдены")

    # Пример отправки команды
    # result = await send_command_to_terminal(car.gps_id, "*!2Y", AUTH_TOKEN)
    result = {"status": "command sent"}  # заглушка
    return {"message": "Команда передачи ключа отправлена", "result": result}


@MechanicRouter.post("/take-key", summary="Получить ключ (доставка)")
async def take_key_delivery(
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Отправляет команду на получение ключа автомобиля для доставки.
    """
    rental = get_current_delivery(db, current_mechanic)
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car or not car.gps_id:
        raise HTTPException(status_code=404, detail="Автомобиль или GPS ID не найдены")

    # Пример отправки команды
    # result = await send_command_to_terminal(car.gps_id, "*!2N", AUTH_TOKEN)
    result = {"status": "command sent"}  # заглушка
    return {"message": "Команда получения ключа отправлена", "result": result}
