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

MechanicRouter = APIRouter(tags=["Mechanic"], prefix="/mechanic")


# Вспомогательные функции
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
from app.auth.dependencies.save_documents import save_file


# ----------------------- GET эндпоинты -----------------------

@MechanicRouter.get("/get_pending_vehicles")
def get_pending_vehicles(
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Возвращает список машин, у которых статус PENDING
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
    Возвращает список машин со статусом IN USE
    """
    try:
        cars = db.query(Car).filter(Car.status == "IN_USE").all()
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
            "owned_car": False
        } for car in cars]
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
    Ищет автомобили по имени или номеру, но возвращает только машины со статусом IN USE или PENDING.
    """
    try:
        cars = db.query(Car).filter(
            or_(
                Car.name.ilike(f"%{query}%"),
                Car.plate_number.ilike(f"%{query}%")
            ),
            Car.status.in_(["IN_USE", "PENDING"])
        ).all()

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
            "owned_car": False  # Для механика информация о владении не имеет значения
        } for car in cars]

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
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_mechanic.id,
        RentalHistory.rental_status == RentalStatus.RESERVED
    ).first()
    if not rental:
        raise HTTPException(status_code=400, detail="Нет активной брони для отмены")
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    now = datetime.utcnow()
    if not rental.start_time:
        rental.start_time = rental.reservation_time or now
        db.commit()
    rental.rental_status = RentalStatus.COMPLETED
    rental.end_time = now
    rental.total_price = 0
    rental.already_payed = 0
    car.current_renter_id = None
    # При отмене статус автомобиля возвращается в PENDING
    car.status = "PENDING"
    try:
        db.commit()
        return {
            "message": "Проверка автомобиля отменена",
            "minutes_used": int((now - rental.start_time).total_seconds() / 60)
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка при отмене проверки: {str(e)}")


# ----------------------- Эндпоинты для загрузки фотографий -----------------------

@MechanicRouter.post("/upload-photos-before")
async def upload_photos_before(
        selfie: UploadFile = File(...),
        car_photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Загрузка фотографий до начала проверки автомобиля.
    Принимает selfie и от 1 до 10 фотографий машины.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_mechanic.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Нет активной проверки (IN USE)")
    validate_photo_count(car_photos)
    all_photos = [selfie] + car_photos
    validate_photo_types(all_photos)
    try:
        selfie_path = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/before/selfie/")
        car_paths = await process_upload_photos(car_photos, rental.id, "before/car")
        photo_urls = [selfie_path] + car_paths
        rental.photos_before = photo_urls
        db.commit()
        return {
            "message": "Фотографии до проверки загружены успешно",
            "photo_count": len(photo_urls)
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Ошибка при загрузке фотографий")


@MechanicRouter.post("/upload-photos-after")
async def upload_photos_after(
        selfie: UploadFile = File(...),
        car_photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_mechanic: Any = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Загрузка фотографий после завершения проверки автомобиля.
    Принимает selfie и от 1 до 10 фотографий машины.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_mechanic.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Нет активной проверки (IN USE)")
    validate_photo_count(car_photos)
    all_photos = [selfie] + car_photos
    validate_photo_types(all_photos)
    try:
        selfie_path = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/after/selfie/")
        car_paths = await process_upload_photos(car_photos, rental.id, "after/car")
        photo_urls = [selfie_path] + car_paths
        rental.photos_after = photo_urls
        db.commit()
        return {
            "message": "Фотографии после проверки загружены успешно",
            "photo_count": len(photo_urls)
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Ошибка при загрузке фотографий")


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
