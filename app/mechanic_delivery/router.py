from fastapi import APIRouter, HTTPException, Depends, File, UploadFile
from sqlalchemy import and_
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, constr

from app.auth.dependencies.get_current_user import get_current_mechanic
from app.auth.dependencies.save_documents import validate_photos, save_file
from app.dependencies.database.database import get_db
from app.gps_api.router import AUTH_TOKEN
from app.gps_api.utils.car_data import send_command_to_terminal, send_open, send_close, send_give_key, send_take_key
from app.gps_api.utils.auth_api import get_auth_token
from app.core.config import GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD
from app.models.history_model import RentalStatus, RentalHistory, RentalReview
from app.models.car_model import Car, CarStatus
from app.models.rental_actions_model import ActionType, RentalAction
from app.models.user_model import User
from app.push.utils import send_push_to_user_by_id, send_localized_notification_to_user
from app.wallet.utils import record_wallet_transaction
from app.models.wallet_transaction_model import WalletTransactionType

class DeliveryReviewInput(BaseModel):
    """Схема для отзыва механика доставки"""
    rating: int = Field(..., ge=1, le=5, description="Рейтинг от 1 до 5")
    comment: Optional[constr(max_length=255)] = Field(None, description="Комментарий к доставке (до 255 символов)")


MechanicDeliveryRouter = APIRouter(
    tags=["Mechanic Delivery"],
    prefix="/mechanic"
)


@MechanicDeliveryRouter.get("/get-delivery-vehicles")
def get_delivery_vehicles(
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Возвращает список автомобилей, находящихся в стадии DELIVERY_RESERVED или DELIVERING_IN_PROGRESS,
    где доставка ещё не принята другим механиком или уже принята текущим.
    """

    deliveries = (
        db.query(RentalHistory)
        .filter(RentalHistory.rental_status == RentalStatus.DELIVERING)
        .all()
    )

    vehicles_data: List[Dict[str, Any]] = []
    for rental in deliveries:
        car = db.query(Car).filter(Car.id == rental.car_id).first()
        if not car:
            continue
            
        # Рассчитываем время ожидания доставки
        from datetime import datetime
        waiting_time_minutes = int((datetime.utcnow() - rental.reservation_time).total_seconds() / 60)
        
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
            "body_type": car.body_type,
            "auto_class": car.auto_class,
            "year": car.year,
            "photos": car.photos,
            "status": car.status,
            "delivery_coordinates": {
                "latitude": rental.delivery_latitude,
                "longitude": rental.delivery_longitude,
            },
            "reservation_time": rental.reservation_time.isoformat(),
            "waiting_time_minutes": waiting_time_minutes,
            "delivery_assigned": rental.delivery_mechanic_id is not None
        })

    return {"delivery_vehicles": vehicles_data}


@MechanicDeliveryRouter.post("/accept-delivery/{rental_id}")
async def accept_delivery(
        rental_id: int,
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Механик принимает заказ доставки: назначаем себя и переводим в DELIVERY_RESERVED,
    сохраняем текущее состояние машины и пушим пользователю.
    """
    # 1) Проверяем, что механик не занят другой доставкой
    existing = db.query(RentalHistory).filter(
        RentalHistory.delivery_mechanic_id == current_mechanic.id,
        RentalHistory.rental_status.in_([
            RentalStatus.DELIVERY_RESERVED,
            RentalStatus.DELIVERING_IN_PROGRESS
        ])
    ).first()
    if existing:
        raise HTTPException(400, "У вас уже есть активный заказ доставки.")

    rental = db.query(RentalHistory).filter(
        RentalHistory.id == rental_id,
        RentalHistory.rental_status == RentalStatus.DELIVERING
    ).first()
    if not rental:
        raise HTTPException(404, "Заказ доставки не найден")
    if rental.delivery_mechanic_id is not None:
        raise HTTPException(400, "Заказ уже принят другим механиком.")

    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(404, "Автомобиль не найден")

    # Назначаем механика и переводим в DELIVERY_RESERVED
    rental.delivery_mechanic_id = current_mechanic.id
    rental.rental_status = RentalStatus.DELIVERY_RESERVED
    rental.fuel_before = car.fuel_level
    rental.mileage_before = car.mileage

    db.commit()
    db.refresh(rental)

    # Уведомляем пользователя
    user = db.query(User).filter(User.id == rental.user_id).first()
    if user and user.fcm_token:
        await send_localized_notification_to_user(
            db,
            user.id,
            "mechanic_assigned",
            "mechanic_assigned"
        )

    return {
        "message": "Заказ доставки успешно принят",
        "rental_id": rental.id
    }


@MechanicDeliveryRouter.post("/start-delivery", summary="Начать доставку")
async def start_delivery(
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Механик начинает фактическую доставку: переводим в DELIVERING_IN_PROGRESS и пушим пользователю.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.delivery_mechanic_id == current_mechanic.id,
        RentalHistory.rental_status == RentalStatus.DELIVERY_RESERVED
    ).first()
    if not rental:
        raise HTTPException(404, "Нет назначенной доставки для старта")

    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(404, "Автомобиль не найден")

    rental.rental_status = RentalStatus.DELIVERING_IN_PROGRESS
    rental.delivery_start_time = datetime.utcnow()  # Записываем время начала доставки
    db.commit()
    db.refresh(rental)

    user = db.query(User).filter(User.id == rental.user_id).first()
    if user and user.fcm_token:
        await send_localized_notification_to_user(
            db,
            user.id,
            "delivery_started",
            "delivery_started"
        )

    return {"message": "Доставка запущена", "rental_id": rental.id}


@MechanicDeliveryRouter.post("/complete-delivery")
async def complete_delivery(
        review_input: Optional[DeliveryReviewInput] = None,
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Завершение доставки: сохраняем после-показатели, переводим в обычный RESERVED
    и пушим пользователю, что машина готова к использованию.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.delivery_mechanic_id == current_mechanic.id,
        RentalHistory.rental_status == RentalStatus.DELIVERING_IN_PROGRESS
    ).first()
    if not rental:
        raise HTTPException(404, "Активная доставка не найдена")

    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(404, "Автомобиль не найден")

    rental.fuel_after = car.fuel_level
    rental.mileage_after = car.mileage

    # Записываем время окончания доставки
    delivery_end_time = datetime.utcnow()
    rental.delivery_end_time = delivery_end_time
    
    # Рассчитываем штраф за задержку доставки (если больше 1.5 часа = 90 минут)
    if rental.delivery_start_time:
        delivery_duration_minutes = (delivery_end_time - rental.delivery_start_time).total_seconds() / 60
        if delivery_duration_minutes > 90:  # 1.5 часа
            # Штраф: 1000 тенге за каждую минуту превышения
            penalty_minutes = delivery_duration_minutes - 90
            penalty_fee = int(penalty_minutes * 1000)
            rental.delivery_penalty_fee = penalty_fee
            
            # Списываем штраф с механика
            mechanic = db.query(User).filter(User.id == rental.delivery_mechanic_id).first()
            if mechanic:
                record_wallet_transaction(db, user=mechanic, amount=-penalty_fee, ttype=WalletTransactionType.DELIVERY_PENALTY, description=f"Штраф за задержку доставки {penalty_minutes:.1f} мин", related_rental=rental)
                mechanic.wallet_balance -= penalty_fee
                print(f"Штраф за задержку доставки: {penalty_fee}₸ с механика {mechanic.phone_number}")

    rental.end_time = delivery_end_time
    rental.rental_status = RentalStatus.RESERVED
    car.status = CarStatus.RESERVED
    rental.delivery_mechanic_id = None

    # Сохраняем отзыв механика доставки (если есть)
    if review_input:
        # Ищем существующий отзыв для этой аренды
        existing_review = db.query(RentalReview).filter(RentalReview.rental_id == rental.id).first()
        
        if existing_review:
            # Обновляем существующий отзыв, добавляя данные механика доставки
            existing_review.delivery_mechanic_rating = review_input.rating
            existing_review.delivery_mechanic_comment = review_input.comment
        else:
            # Создаем новый отзыв только с данными механика доставки
            review = RentalReview(
                rental_id=rental.id,
                delivery_mechanic_rating=review_input.rating,
                delivery_mechanic_comment=review_input.comment
            )
            db.add(review)

    db.commit()
    db.refresh(rental)

    user = db.query(User).filter(User.id == rental.user_id).first()
    if user and user.fcm_token:
        await send_localized_notification_to_user(
            db,
            user.id,
            "delivery_completed",
            "car_delivered"
        )

    return {
        "message": "Доставка успешно завершена, статус автомобиля — RESERVED.",
        "rental_id": rental.id
    }


def get_current_delivery(db: Session, current_mechanic: User) -> RentalHistory:
    """
    Возвращает доставку, назначенную механику,
    в статусах DELIVERY_RESERVED или DELIVERING_IN_PROGRESS.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.delivery_mechanic_id == current_mechanic.id,
        RentalHistory.rental_status.in_([
            RentalStatus.DELIVERY_RESERVED,
            RentalStatus.DELIVERING_IN_PROGRESS
        ])
    ).first()
    if not rental:
        raise HTTPException(404, "Активная доставка не найдена")
    return rental


@MechanicDeliveryRouter.get("/current-delivery", summary="Получить текущую доставку")
def current_delivery(
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    rental = get_current_delivery(db, current_mechanic)
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(404, "Автомобиль не найден")

    # Рассчитываем продолжительность доставки если она началась
    delivery_duration_minutes = None
    if rental.delivery_start_time:
        from datetime import datetime
        delivery_duration_minutes = int((datetime.utcnow() - rental.delivery_start_time).total_seconds() / 60)

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
        "body_type": car.body_type,
        "auto_class": car.auto_class,
        "photos": car.photos,
        "year": car.year,
        "delivery_coordinates": {
            "latitude": rental.delivery_latitude,
            "longitude": rental.delivery_longitude,
        },
        "reservation_time": rental.reservation_time.isoformat(),
        "delivery_start_time": rental.delivery_start_time.isoformat() if rental.delivery_start_time else None,
        "delivery_duration_minutes": delivery_duration_minutes,
        "delivery_penalty_fee": rental.delivery_penalty_fee or 0,
        "status": rental.rental_status.value
    }


@MechanicDeliveryRouter.post("/open", summary="Открыть автомобиль (доставка)")
async def open_vehicle_delivery(
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    rental = get_current_delivery(db, current_mechanic)
    car = db.query(Car).get(rental.car_id)
    if not car or not car.gps_imei:
        raise HTTPException(404, "Автомобиль или GPS IMEI не найдены")

    # логируем действие механика
    action = RentalAction(
        rental_id=rental.id,
        user_id=current_mechanic.id,
        action_type=ActionType.OPEN_VEHICLE
    )
    db.add(action)
    db.commit()

    # Проверяем и обновляем токен если необходимо
    token = AUTH_TOKEN
    if not token:
        try:
            token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    # отправка команды
    result = await send_open(car.gps_imei, token)
    return {"message": "Команда для открытия автомобиля отправлена", "result": result}


@MechanicDeliveryRouter.post("/close", summary="Закрыть автомобиль (доставка)")
async def close_vehicle_delivery(
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    rental = get_current_delivery(db, current_mechanic)
    car = db.query(Car).get(rental.car_id)
    if not car or not car.gps_imei:
        raise HTTPException(404, "Автомобиль или GPS IMEI не найдены")

    action = RentalAction(
        rental_id=rental.id,
        user_id=current_mechanic.id,
        action_type=ActionType.CLOSE_VEHICLE
    )
    db.add(action)
    db.commit()

    # Проверяем и обновляем токен если необходимо
    token = AUTH_TOKEN
    if not token:
        try:
            token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    result = await send_close(car.gps_imei, token)
    return {"message": "Команда для закрытия автомобиля отправлена", "result": result}


@MechanicDeliveryRouter.post("/give-key", summary="Передать ключ (доставка)")
async def give_key_delivery(
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    rental = get_current_delivery(db, current_mechanic)
    car = db.query(Car).get(rental.car_id)
    if not car or not car.gps_imei:
        raise HTTPException(404, "Автомобиль или GPS IMEI не найдены")

    action = RentalAction(
        rental_id=rental.id,
        user_id=current_mechanic.id,
        action_type=ActionType.GIVE_KEY
    )
    db.add(action)
    db.commit()

    # Проверяем и обновляем токен если необходимо
    token = AUTH_TOKEN
    if not token:
        try:
            token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    result = await send_give_key(car.gps_imei, token)
    return {"message": "Команда передачи ключа отправлена", "result": result}


@MechanicDeliveryRouter.post("/take-key", summary="Получить ключ (доставка)")
async def take_key_delivery(
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    rental = get_current_delivery(db, current_mechanic)
    car = db.query(Car).get(rental.car_id)
    if not car or not car.gps_imei:
        raise HTTPException(404, "Автомобиль или GPS IMEI не найдены")

    action = RentalAction(
        rental_id=rental.id,
        user_id=current_mechanic.id,
        action_type=ActionType.TAKE_KEY
    )
    db.add(action)
    db.commit()

    result = await send_take_key(car.gps_imei, AUTH_TOKEN)
    return {"message": "Команда получения ключа отправлена", "result": result}


@MechanicDeliveryRouter.post("/upload-delivery-photos-before")
async def upload_delivery_photos_before(
        selfie: UploadFile = File(...),
        car_photos: List[UploadFile] = File(...),
        interior_photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Загрузка фото перед доставкой — доступно только в статусе DELIVERING_IN_PROGRESS.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.delivery_mechanic_id == current_mechanic.id,
        RentalHistory.rental_status == RentalStatus.DELIVERING_IN_PROGRESS
    ).first()
    if not rental:
        raise HTTPException(404, "Нет активной доставки для загрузки фотографий")

    validate_photos([selfie], "selfie")
    validate_photos(car_photos, "car_photos")
    validate_photos(interior_photos, "interior_photos")

    try:
        urls: List[str] = []
        urls.append(await save_file(selfie, rental.id, f"uploads/delivery/{rental.id}/before/selfie/"))
        for p in car_photos:
            urls.append(await save_file(p, rental.id, f"uploads/delivery/{rental.id}/before/car/"))
        for p in interior_photos:
            urls.append(await save_file(p, rental.id, f"uploads/delivery/{rental.id}/before/interior/"))
        rental.delivery_photos_before = urls
        db.commit()
        return {"message": "Фотографии перед доставкой загружены", "photo_count": len(urls)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Ошибка при загрузке фото перед доставкой: {e}")


@MechanicDeliveryRouter.post("/upload-delivery-photos-after")
async def upload_delivery_photos_after(
        selfie: UploadFile = File(...),
        car_photos: List[UploadFile] = File(...),
        interior_photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Загрузка фото после доставки — доступно только в статусе DELIVERING_IN_PROGRESS.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.delivery_mechanic_id == current_mechanic.id,
        RentalHistory.rental_status == RentalStatus.DELIVERING_IN_PROGRESS
    ).first()
    if not rental:
        raise HTTPException(404, "Нет активной доставки для загрузки фотографий")

    validate_photos([selfie], "selfie")
    validate_photos(car_photos, "car_photos")
    validate_photos(interior_photos, "interior_photos")

    try:
        urls: List[str] = []
        urls.append(await save_file(selfie, rental.id, f"uploads/delivery/{rental.id}/after/selfie/"))
        for p in car_photos:
            urls.append(await save_file(p, rental.id, f"uploads/delivery/{rental.id}/after/car/"))
        for p in interior_photos:
            urls.append(await save_file(p, rental.id, f"uploads/delivery/{rental.id}/after/interior/"))
        rental.delivery_photos_after = urls
        db.commit()
        return {"message": "Фотографии после доставки загружены", "photo_count": len(urls)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Ошибка при загрузке фото после доставки: {e}")
