from fastapi import APIRouter, HTTPException, Depends, File, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import and_
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, constr
import uuid
import asyncio
from app.utils.short_id import safe_sid_to_uuid, uuid_to_sid

from app.auth.dependencies.get_current_user import get_current_mechanic
from app.auth.dependencies.save_documents import validate_photos, save_file
from app.services.face_verify import verify_user_upload_against_profile
from app.dependencies.database.database import get_db
from app.gps_api.router import AUTH_TOKEN
from app.gps_api.utils.car_data import send_command_to_terminal, send_open, send_close, send_give_key, send_take_key, auto_lock_vehicle_after_rental, execute_gps_sequence
from app.gps_api.utils.auth_api import get_auth_token
from app.core.config import GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD
from app.utils.atomic_operations import delete_uploaded_files
from app.utils.telegram_logger import log_error_to_telegram
from app.utils.time_utils import get_local_time
from app.models.history_model import RentalStatus, RentalHistory, RentalReview
from app.models.car_model import Car, CarStatus
from app.models.rental_actions_model import ActionType, RentalAction
from app.models.user_model import User
from app.push.utils import send_push_to_user_by_id, send_localized_notification_to_user, user_has_push_tokens
from app.wallet.utils import record_wallet_transaction
from app.models.wallet_transaction_model import WalletTransactionType
from app.guarantor.sms_utils import send_rental_start_sms, send_rental_complete_sms
from app.admin.cars.utils import sort_car_photos
from app.websocket.notifications import notify_vehicles_list_update, notify_user_status_update
import logging

logger = logging.getLogger(__name__)

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
        waiting_time_minutes = int((get_local_time() - rental.reservation_time).total_seconds() / 60)
        
        vehicles_data.append({
            "rental_id": uuid_to_sid(rental.id),
            "car_id": uuid_to_sid(car.id),
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
            "photos": sort_car_photos(car.photos or []),
            "status": car.status,
            "vin": car.vin,
            "color": car.color,
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
        rental_id: str,
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

    rental_uuid = safe_sid_to_uuid(rental_id)
    rental = db.query(RentalHistory).filter(
        RentalHistory.id == rental_uuid,
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
    db.refresh(car)

    user = db.query(User).filter(User.id == rental.user_id).first()
    if user and user_has_push_tokens(db, user.id):
        asyncio.create_task(
            send_localized_notification_to_user(
                db,
                user.id,
                "courier_found",
                "courier_found"
            )
        )
    
    # Отправляем WebSocket уведомления
    try:
        await notify_vehicles_list_update()
        if rental.user_id:
            await notify_user_status_update(str(rental.user_id))
        if car.owner_id:
            await notify_user_status_update(str(car.owner_id))
        logger.info(f"WebSocket notifications sent after mechanic accept-delivery for rental {rental.id}")
    except Exception as e:
        logger.error(f"Error sending WebSocket notifications: {e}")

    return {
        "message": "Заказ доставки успешно принят",
        "rental_id": uuid_to_sid(rental.id)
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

    before_photos = rental.delivery_photos_before or []
    has_selfie_before = any(("/before/selfie/" in p) or ("\\before\\selfie\\" in p) for p in before_photos)
    has_exterior_before = any(("/before/car/" in p) or ("\\before\\car\\" in p) for p in before_photos)
    has_interior_before = any(("/before/interior/" in p) or ("\\before\\interior\\" in p) for p in before_photos)
    if not (has_selfie_before and has_exterior_before and has_interior_before):
        missing = []
        if not has_selfie_before:
            missing.append("селфи")
        if not has_exterior_before:
            missing.append("внешний вид")
        if not has_interior_before:
            missing.append("салон")
        raise HTTPException(status_code=400, detail=f"Перед стартом доставки загрузите фото: {', '.join(missing)}")

    rental.rental_status = RentalStatus.DELIVERING_IN_PROGRESS
    rental.delivery_start_time = get_local_time()  # Записываем время начала доставки
    # Фиксируем стартовые координаты доставки по текущему положению автомобиля
    rental.delivery_start_latitude = car.latitude
    rental.delivery_start_longitude = car.longitude
    db.commit()
    
    # GPS команды при старте доставки
    try:
        if car and car.gps_imei:
            
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            # Универсальная последовательность: разблокировать двигатель → выдать ключ
            result = await execute_gps_sequence(car.gps_imei, auth_token, "interior")
            if not result["success"]:
                print(f"Ошибка GPS последовательности при старте доставки: {result.get('error', 'Unknown error')}")
    except Exception as e:
        print(f"Ошибка GPS команд при старте доставки: {e}")
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_mechanic,
                additional_context={
                    "action": "mechanic_delivery_start_gps",
                    "car_id": str(car.id) if car else None,
                    "car_name": car.name if car else None,
                    "gps_imei": car.gps_imei if car else None,
                    "rental_id": str(rental.id),
                    "mechanic_id": str(current_mechanic.id)
                }
            )
        except:
            pass
    
    # Обновляем все данные из БД для получения свежих данных (после всех операций)
    db.expire_all()
    db.refresh(rental)
    db.refresh(car)
    if rental.user_id:
        user = db.query(User).filter(User.id == rental.user_id).first()
        if user:
            db.refresh(user)
    if car.owner_id:
        owner = db.query(User).filter(User.id == car.owner_id).first()
        if owner:
            db.refresh(owner)

    # Отправляем WebSocket уведомления в самом конце, после всех операций
    try:
        await notify_vehicles_list_update()
        if rental.user_id:
            await notify_user_status_update(str(rental.user_id))
        if car.owner_id:
            await notify_user_status_update(str(car.owner_id))
        logger.info(f"WebSocket notifications sent after mechanic start-delivery for rental {rental.id}")
    except Exception as e:
        logger.error(f"Error sending WebSocket notifications: {e}")

    user = db.query(User).filter(User.id == rental.user_id).first()
    if user and user_has_push_tokens(db, user.id):
        await send_localized_notification_to_user(
            db,
            user.id,
            "delivery_started",
            "delivery_started"
        )

    # try:
    #     name_parts = []
    #     if current_mechanic.first_name:
    #         name_parts.append(current_mechanic.first_name)
    #     if current_mechanic.middle_name:
    #         name_parts.append(current_mechanic.middle_name)
    #     if current_mechanic.last_name:
    #         name_parts.append(current_mechanic.last_name)
    #     full_name = " ".join(name_parts) if name_parts else "Не указано"
    #     
    #     login = current_mechanic.phone_number or "Не указан"
    #     
    #     await send_rental_start_sms(
    #         client_phone=current_mechanic.phone_number,
    #         rent_id=str(rental.id),
    #         full_name=full_name,
    #         login=login,
    #         client_id=str(current_mechanic.id),
    #         digital_signature=current_mechanic.digital_signature or "Не указана",
    #         car_id=str(car.id),
    #         plate_number=car.plate_number,
    #         car_name=car.name
    #     )
    #     print(f"SMS отправлена доставщику {current_mechanic.phone_number} при начале доставки")
    # except Exception as e:
    #     print(f"Ошибка отправки SMS при начале доставки: {e}")

    return {"message": "Доставка запущена", "rental_id": uuid_to_sid(rental.id)}


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

    after_photos = rental.delivery_photos_after or []
    has_after_selfie = any(("/after/selfie/" in p) or ("\\after\\selfie\\" in p) for p in after_photos)
    has_after_interior = any(("/after/interior/" in p) or ("\\after\\interior\\" in p) for p in after_photos)
    has_after_exterior = any(("/after/car/" in p) or ("\\after\\car\\" in p) for p in after_photos)
    if not (has_after_selfie and has_after_interior and has_after_exterior):
        missing = []
        if not has_after_selfie:
            missing.append("селфи")
        if not has_after_interior:
            missing.append("салон")
        if not has_after_exterior:
            missing.append("внешний вид")
        raise HTTPException(status_code=400, detail=f"Для завершения доставки загрузите фото: {', '.join(missing)}")

    rental.fuel_after = car.fuel_level
    rental.mileage_after = car.mileage

    # Записываем время окончания доставки
    delivery_end_time = get_local_time()
    rental.delivery_end_time = delivery_end_time
    # Фиксируем конечные координаты доставки по текущему положению автомобиля
    rental.delivery_end_latitude = car.latitude
    rental.delivery_end_longitude = car.longitude
    
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
                db.flush()  # Фиксируем изменения механика перед commit

    # Сохраняем ID механика до того, как установим его в None
    mechanic_id_for_notification = rental.delivery_mechanic_id
    
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

    # Окончательная блокировка двигателя при завершении доставки
    try:
        if car and car.gps_imei:
            
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            # Универсальная последовательность: заблокировать двигатель
            result = await execute_gps_sequence(car.gps_imei, auth_token, "final_lock")
            if result["success"]:
                print(f"Двигатель автомобиля {car.name} окончательно заблокирован после завершения доставки")
            else:
                print(f"Ошибка GPS последовательности при окончательной блокировке доставки: {result.get('error', 'Unknown error')}")
    except Exception as e:
        print(f"Ошибка GPS команд при окончательной блокировке доставки: {e}")
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_mechanic,
                additional_context={
                    "action": "mechanic_delivery_complete_lock_gps",
                    "car_id": str(car.id) if car else None,
                    "car_name": car.name if car else None,
                    "gps_imei": car.gps_imei if car else None,
                    "rental_id": str(rental.id),
                    "mechanic_id": str(current_mechanic.id)
                }
            )
        except:
            pass

    # Фиксируем все изменения в БД
    db.flush()
    db.commit()
    
    # Обновляем все данные из БД для получения свежих данных (после всех операций)
    db.expire_all()
    db.refresh(rental)
    db.refresh(car)
    if rental.user_id:
        user = db.query(User).filter(User.id == rental.user_id).first()
        if user:
            db.refresh(user)
    if car.owner_id:
        owner = db.query(User).filter(User.id == car.owner_id).first()
        if owner:
            db.refresh(owner)
    # Обновляем механика, если он был изменен (например, при списании штрафа)
    if mechanic_id_for_notification:
        mechanic = db.query(User).filter(User.id == mechanic_id_for_notification).first()
        if mechanic:
            db.refresh(mechanic)
    
    # Отправляем WebSocket уведомления в самом конце, после всех операций
    try:
        await notify_vehicles_list_update()
        if rental.user_id:
            await notify_user_status_update(str(rental.user_id))
        if car.owner_id:
            await notify_user_status_update(str(car.owner_id))
        # Также обновляем статус механика, если он был затронут изменениями
        if mechanic_id_for_notification:
            await notify_user_status_update(str(mechanic_id_for_notification))
        logger.info(f"WebSocket notifications sent after mechanic complete-delivery for rental {rental.id}")
    except Exception as e:
        logger.error(f"Error sending WebSocket notifications: {e}")
    
    # Отправляем push-уведомление после WebSocket
    user = db.query(User).filter(User.id == rental.user_id).first()
    if user and user_has_push_tokens(db, user.id):
        # Уведомление о доставке курьером
        await send_localized_notification_to_user(
            db,
            user.id,
            "courier_delivered",
            "courier_delivered"
        )

    # try:
    #     name_parts = []
    #     if current_mechanic.first_name:
    #         name_parts.append(current_mechanic.first_name)
    #     if current_mechanic.middle_name:
    #         name_parts.append(current_mechanic.middle_name)
    #     if current_mechanic.last_name:
    #         name_parts.append(current_mechanic.last_name)
    #     full_name = " ".join(name_parts) if name_parts else "Не указано"
    #     
    #     login = current_mechanic.phone_number or "Не указан"
    #     
    #     await send_rental_complete_sms(
    #         client_phone=current_mechanic.phone_number,
    #         rent_id=str(rental.id),
    #         full_name=full_name,
    #         login=login,
    #         client_id=str(current_mechanic.id),
    #         digital_signature=current_mechanic.digital_signature or "Не указана",
    #         car_id=str(car.id),
    #         plate_number=car.plate_number,
    #         car_name=car.name
    #     )
    #     print(f"SMS отправлена доставщику {current_mechanic.phone_number} при завершении доставки")
    # except Exception as e:
    #     print(f"Ошибка отправки SMS при завершении доставки: {e}")

    return {
        "message": "Доставка успешно завершена, статус автомобиля — RESERVED.",
        "rental_id": uuid_to_sid(rental.id)
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
        delivery_duration_minutes = int((get_local_time() - rental.delivery_start_time).total_seconds() / 60)

    # Проверяем флаги загрузки фото ПЕРЕД доставкой
    photo_before_selfie_uploaded = False
    photo_before_car_uploaded = False
    photo_before_interior_uploaded = False
    
    if rental.delivery_photos_before:
        photos_before = rental.delivery_photos_before
        photo_before_selfie_uploaded = any(
            ("/before/selfie/" in photo) or ("\\before\\selfie\\" in photo) 
            for photo in photos_before
        )
        photo_before_car_uploaded = any(
            ("/before/car/" in photo) or ("\\before\\car\\" in photo) 
            for photo in photos_before
        )
        photo_before_interior_uploaded = any(
            ("/before/interior/" in photo) or ("\\before\\interior\\" in photo) 
            for photo in photos_before
        )

    # Проверяем флаги загрузки фото ПОСЛЕ доставки
    photo_after_selfie_uploaded = False
    photo_after_car_uploaded = False
    photo_after_interior_uploaded = False
    
    if rental.delivery_photos_after:
        photos_after = rental.delivery_photos_after
        photo_after_selfie_uploaded = any(
            ("/after/selfie/" in photo) or ("\\after\\selfie\\" in photo) 
            for photo in photos_after
        )
        photo_after_car_uploaded = any(
            ("/after/car/" in photo) or ("\\after\\car\\" in photo) 
            for photo in photos_after
        )
        photo_after_interior_uploaded = any(
            ("/after/interior/" in photo) or ("\\after\\interior\\" in photo) 
            for photo in photos_after
        )

    return {
        "rental_id": uuid_to_sid(rental.id),
        "car_id": uuid_to_sid(car.id),
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
        "photos": sort_car_photos(car.photos or []),
        "year": car.year,
        "delivery_coordinates": {
            "latitude": rental.delivery_latitude,
            "longitude": rental.delivery_longitude,
        },
        "reservation_time": rental.reservation_time.isoformat(),
        "delivery_start_time": rental.delivery_start_time.isoformat() if rental.delivery_start_time else None,
        "delivery_duration_minutes": delivery_duration_minutes,
        "delivery_penalty_fee": rental.delivery_penalty_fee or 0,
        "status": rental.rental_status.value,
        "photo_before_selfie_uploaded": photo_before_selfie_uploaded,
        "photo_before_car_uploaded": photo_before_car_uploaded,
        "photo_before_interior_uploaded": photo_before_interior_uploaded,
        "photo_after_selfie_uploaded": photo_after_selfie_uploaded,
        "photo_after_car_uploaded": photo_after_car_uploaded,
        "photo_after_interior_uploaded": photo_after_interior_uploaded
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
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Перед доставкой (часть 1): selfie + внешние фото.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.delivery_mechanic_id == current_mechanic.id,
        RentalHistory.rental_status.in_([RentalStatus.DELIVERY_RESERVED, RentalStatus.DELIVERING_IN_PROGRESS])
    ).first()
    if not rental:
        raise HTTPException(404, "Нет активной доставки для загрузки фотографий")

    validate_photos([selfie], "selfie")
    # try:
    #     # Сверяем селфи механика доставки с документом
    #     is_same, msg = await run_in_threadpool(verify_user_upload_against_profile, current_mechanic, selfie)
    #     if not is_same:
    #         raise HTTPException(status_code=400, detail=msg)
    # except HTTPException:
    #     raise
    # except Exception as e:
    #     raise HTTPException(status_code=400, detail="Ой! Похоже на фотографии не вы, но если это вы, то пожалуйста сделайте селфи как в профиле.")
    validate_photos(car_photos, "car_photos")

    uploaded_files = []
    try:
        urls: List[str] = list(rental.delivery_photos_before or [])
        
        selfie_url = await save_file(selfie, rental.id, f"uploads/delivery/{rental.id}/before/selfie/")
        urls.append(selfie_url)
        uploaded_files.append(selfie_url)
        
        for p in car_photos:
            car_url = await save_file(p, rental.id, f"uploads/delivery/{rental.id}/before/car/")
            urls.append(car_url)
            uploaded_files.append(car_url)
        
        rental.delivery_photos_before = urls
        
        # Универсальная GPS последовательность после загрузки селфи+кузов
        car = db.query(Car).get(rental.car_id)
        if car and car.gps_imei:
            
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            # Универсальная последовательность: открыть замки → выдать ключ → открыть замки → забрать ключ
            result = await execute_gps_sequence(car.gps_imei, auth_token, "selfie_exterior")
            if not result["success"]:
                error_msg = result.get('error', 'Unknown error')
                print(f"Ошибка GPS последовательности для селфи+кузов доставщика: {error_msg}")
                raise Exception(f"GPS sequence failed: {error_msg}")
        
        db.commit()
        
        # Обновляем все данные из БД для получения свежих данных (после всех операций)
        db.expire_all()
        db.refresh(rental)
        car = db.query(Car).filter(Car.id == rental.car_id).first()
        if car:
            db.refresh(car)
        if rental.user_id:
            user = db.query(User).filter(User.id == rental.user_id).first()
            if user:
                db.refresh(user)
        if car and car.owner_id:
            owner = db.query(User).filter(User.id == car.owner_id).first()
            if owner:
                db.refresh(owner)
        
        # Отправляем WebSocket уведомления в самом конце, после всех операций
        try:
            if rental.user_id:
                await notify_user_status_update(str(rental.user_id))
            if car and car.owner_id:
                await notify_user_status_update(str(car.owner_id))
            logger.info(f"WebSocket notifications sent after mechanic upload-delivery-photos-before for rental {rental.id}")
        except Exception as e:
            logger.error(f"Error sending WebSocket notifications: {e}")
        
        return {"message": "Фотографии перед доставкой (selfie+car) загружены", "photo_count": len(urls)}
    except HTTPException:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise HTTPException(500, f"Ошибка при загрузке фото перед доставкой: {e}")


@MechanicDeliveryRouter.post("/upload-delivery-photos-before-interior")
async def upload_delivery_photos_before_interior(
        interior_photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    Перед доставкой (часть 2): только салон.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.delivery_mechanic_id == current_mechanic.id,
        RentalHistory.rental_status.in_([RentalStatus.DELIVERY_RESERVED, RentalStatus.DELIVERING_IN_PROGRESS])
    ).first()
    if not rental:
        raise HTTPException(404, "Нет активной доставки для загрузки фотографий")

    # Требуем сначала внешние фото
    existing = rental.delivery_photos_before or []
    has_exterior = any(('/before/car/' in p) or ('\\before\\car\\' in p) for p in existing)
    if not has_exterior:
        raise HTTPException(status_code=400, detail="Сначала загрузите внешние фото")

    validate_photos(interior_photos, "interior_photos")

    uploaded_files = []
    try:
        urls: List[str] = list(rental.delivery_photos_before or [])
        for p in interior_photos:
            interior_url = await save_file(p, rental.id, f"uploads/delivery/{rental.id}/before/interior/")
            urls.append(interior_url)
            uploaded_files.append(interior_url)
        rental.delivery_photos_before = urls
        db.commit()
        
        # Обновляем все данные из БД для получения свежих данных (после всех операций)
        db.expire_all()
        db.refresh(rental)
        car = db.query(Car).filter(Car.id == rental.car_id).first()
        if car:
            db.refresh(car)
        if rental.user_id:
            user = db.query(User).filter(User.id == rental.user_id).first()
            if user:
                db.refresh(user)
        if car and car.owner_id:
            owner = db.query(User).filter(User.id == car.owner_id).first()
            if owner:
                db.refresh(owner)
        
        # Отправляем WebSocket уведомления в самом конце, после всех операций
        try:
            if rental.user_id:
                await notify_user_status_update(str(rental.user_id))
            if car and car.owner_id:
                await notify_user_status_update(str(car.owner_id))
            logger.info(f"WebSocket notifications sent after mechanic upload-delivery-photos-before-interior for rental {rental.id}")
        except Exception as e:
            logger.error(f"Error sending WebSocket notifications: {e}")
        
        return {"message": "Фотографии салона перед доставкой загружены", "photo_count": len(interior_photos)}
    except HTTPException:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise HTTPException(500, f"Ошибка при загрузке фото салона перед доставкой: {e}")


@MechanicDeliveryRouter.post("/upload-delivery-photos-after")
async def upload_delivery_photos_after(
        selfie: UploadFile = File(...),
        interior_photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    После доставки (часть 1): selfie + салон.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.delivery_mechanic_id == current_mechanic.id,
        RentalHistory.rental_status == RentalStatus.DELIVERING_IN_PROGRESS
    ).first()
    if not rental:
        raise HTTPException(404, "Нет активной доставки для загрузки фотографий")

    validate_photos([selfie], "selfie")
    # try:
    #     # Сверяем селфи механика доставки с документом
    #     is_same, msg = await run_in_threadpool(verify_user_upload_against_profile, current_mechanic, selfie)
    #     if not is_same:
    #         raise HTTPException(status_code=400, detail=msg)
    # except HTTPException:
    #     raise
    # except Exception as e:
    #     raise HTTPException(status_code=400, detail="Ой! Похоже на фотографии не вы, но если это вы, то пожалуйста сделайте селфи как в профиле.")
    validate_photos(interior_photos, "interior_photos")

    uploaded_files = []
    try:
        urls: List[str] = list(rental.delivery_photos_after or [])
        
        selfie_url = await save_file(selfie, rental.id, f"uploads/delivery/{rental.id}/after/selfie/")
        urls.append(selfie_url)
        uploaded_files.append(selfie_url)
        
        for p in interior_photos:
            interior_url = await save_file(p, rental.id, f"uploads/delivery/{rental.id}/after/interior/")
            urls.append(interior_url)
            uploaded_files.append(interior_url)
        
        rental.delivery_photos_after = urls
        
        # После загрузки селфи+салона доставщиком: заблокировать двигатель → забрать ключ → закрыть замки
        car = db.query(Car).get(rental.car_id)
        if car and car.gps_imei:
            
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            # Универсальная последовательность: заблокировать двигатель → забрать ключ → закрыть замки
            result = await execute_gps_sequence(car.gps_imei, auth_token, "complete_selfie_interior")
            if not result["success"]:
                error_msg = result.get('error', 'Unknown error')
                print(f"Ошибка GPS последовательности для завершения селфи+салон доставщиком: {error_msg}")
                raise Exception(f"GPS sequence failed: {error_msg}")
        
        db.commit()
        
        # Обновляем все данные из БД для получения свежих данных (после всех операций)
        db.expire_all()
        db.refresh(rental)
        if car:
            db.refresh(car)
        if rental.user_id:
            user = db.query(User).filter(User.id == rental.user_id).first()
            if user:
                db.refresh(user)
        if car and car.owner_id:
            owner = db.query(User).filter(User.id == car.owner_id).first()
            if owner:
                db.refresh(owner)
        
        # Отправляем WebSocket уведомления в самом конце, после всех операций
        try:
            if rental.user_id:
                await notify_user_status_update(str(rental.user_id))
            if car and car.owner_id:
                await notify_user_status_update(str(car.owner_id))
            logger.info(f"WebSocket notifications sent after mechanic upload-delivery-photos-after for rental {rental.id}")
        except Exception as e:
            logger.error(f"Error sending WebSocket notifications: {e}")
        
        return {"message": "Фотографии после доставки (selfie+interior) загружены", "photo_count": len(urls)}
    except HTTPException:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise HTTPException(500, f"Ошибка при загрузке фото после доставки (selfie+interior): {e}")

@MechanicDeliveryRouter.post("/upload-delivery-photos-after-car")
async def upload_delivery_photos_after_car(
        car_photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_mechanic: User = Depends(get_current_mechanic)
) -> Dict[str, Any]:
    """
    После доставки (часть 2): только внешние фото.
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.delivery_mechanic_id == current_mechanic.id,
        RentalHistory.rental_status == RentalStatus.DELIVERING_IN_PROGRESS
    ).first()
    if not rental:
        raise HTTPException(404, "Нет активной доставки для загрузки фотографий")

    # Требуем сначала салонные фото
    existing_after = rental.delivery_photos_after or []
    has_interior_after = any(('/after/interior/' in p) or ('\\after\\interior\\' in p) for p in existing_after)
    if not has_interior_after:
        raise HTTPException(status_code=400, detail="Сначала загрузите фото салона")

    # Проверяем закрытие дверей перед внешней съёмкой
    car = db.query(Car).get(rental.car_id)
    try:
        from app.rent.router import check_vehicle_status_for_completion
        vehicle_status = await check_vehicle_status_for_completion(car.gps_imei)
        if vehicle_status.get("errors"):
            doors_errors = [e for e in vehicle_status["errors"] if "двер" in e.lower() or "door" in e.lower()]
            if doors_errors:
                raise HTTPException(status_code=400, detail="Перед внешними фото закройте двери")
    except Exception:
        pass

    validate_photos(car_photos, "car_photos")

    uploaded_files = []
    try:
        urls: List[str] = list(rental.delivery_photos_after or [])
        for p in car_photos:
            car_url = await save_file(p, rental.id, f"uploads/delivery/{rental.id}/after/car/")
            urls.append(car_url)
            uploaded_files.append(car_url)
        
        rental.delivery_photos_after = urls
        
        # После загрузки кузова доставщиком: заблокировать двигатель → забрать ключ → закрыть замки
        if car and car.gps_imei:
            
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            # Универсальная последовательность: заблокировать двигатель → забрать ключ → закрыть замки
            result = await execute_gps_sequence(car.gps_imei, auth_token, "complete_exterior")
            if not result["success"]:
                error_msg = result.get('error', 'Unknown error')
                print(f"Ошибка GPS последовательности для завершения кузова доставщиком: {error_msg}")
                raise Exception(f"GPS sequence failed: {error_msg}")
        
        db.commit()
        
        # Обновляем все данные из БД для получения свежих данных (после всех операций)
        db.expire_all()
        db.refresh(rental)
        if car:
            db.refresh(car)
        if rental.user_id:
            user = db.query(User).filter(User.id == rental.user_id).first()
            if user:
                db.refresh(user)
        if car and car.owner_id:
            owner = db.query(User).filter(User.id == car.owner_id).first()
            if owner:
                db.refresh(owner)
        
        # Отправляем WebSocket уведомления в самом конце, после всех операций
        try:
            if rental.user_id:
                await notify_user_status_update(str(rental.user_id))
            if car and car.owner_id:
                await notify_user_status_update(str(car.owner_id))
            logger.info(f"WebSocket notifications sent after mechanic upload-delivery-photos-after-car for rental {rental.id}")
        except Exception as e:
            logger.error(f"Error sending WebSocket notifications: {e}")
        
        return {"message": "Внешние фото после доставки загружены", "photo_count": len(car_photos)}
    except HTTPException:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise HTTPException(500, f"Ошибка при загрузке внешних фото после доставки: {e}")
