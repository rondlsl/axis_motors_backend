from math import floor, ceil
from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, status, Query
from pydantic import BaseModel, constr, Field, conint
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import httpx

from app.auth.dependencies.get_current_user import get_current_user
from app.auth.dependencies.save_documents import save_file, validate_photos
from app.dependencies.database.database import get_db
from app.models.history_model import RentalType, RentalStatus, RentalHistory, RentalReview
from app.models.promo_codes_model import PromoCode, UserPromoCode, UserPromoStatus
from app.models.user_model import User, UserRole
from app.models.application_model import Application, ApplicationStatus
from app.models.car_model import Car
from app.push.utils import send_notification_to_all_mechanics_async, send_push_to_user_by_id
from app.rent.exceptions import InsufficientBalanceException
from app.rent.utils.calculate_price import calculate_total_price, get_open_price
from app.gps_api.utils.route_data import get_gps_route_data
from app.owner.schemas import RouteData, RouteMapData
from app.rent.schemas import (
    AdvanceBookingRequest, 
    BookingResponse, 
    BookingListResponse, 
    CancelBookingRequest, 
    CancelBookingResponse
)

RentRouter = APIRouter(tags=["Rent"], prefix="/rent")

OFFSET_HOURS = 5


def apply_offset(dt: datetime) -> str | None:
    return (dt + timedelta(hours=OFFSET_HOURS)).isoformat() if dt else None


@RentRouter.get("/history")
def get_trip_history(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> dict:
    # Показываем поездки только после проверки механика:
    # признак — автомобиль уже возвращён в доступ (FREE) после механика
    histories = (
        db.query(RentalHistory, Car)
        .join(Car, Car.id == RentalHistory.car_id)
        .filter(
            RentalHistory.user_id == current_user.id,
            RentalHistory.rental_status == RentalStatus.COMPLETED,
            Car.status == "FREE"
        )
        .order_by(RentalHistory.end_time.desc())
        .all()
    )

    result = []
    for rental, car in histories:
        result.append({
            "history_id": rental.id,
            # Сдвиг +5 ч
            "date": apply_offset(rental.end_time),
            "car_name": car.name,
            "final_total_price": rental.total_price,
            # Фото механика: до/после
            "mechanic_photos_before": rental.photos_before or [],
            "mechanic_photos_after": rental.photos_after or [],
            # GPS координаты маршрута
            "start_latitude": rental.start_latitude,
            "start_longitude": rental.start_longitude,
            "end_latitude": rental.end_latitude,
            "end_longitude": rental.end_longitude
        })

    return {"trip_history": result}


@RentRouter.get("/history/{history_id}")
async def get_trip_history_detail(
        history_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> dict:
    rental = (
        db.query(RentalHistory)
        .filter(
            RentalHistory.id == history_id,
            RentalHistory.user_id == current_user.id
        )
        .first()
    )
    if not rental:
        raise HTTPException(status_code=404, detail="Rental history not found")

    car = db.query(Car).get(rental.car_id)

    rental_detail = {
        "history_id": rental.id,
        "user_id": rental.user_id,
        "car_id": rental.car_id,
        "rental_type": rental.rental_type.value,
        "duration": rental.duration,
        # Применяем смещение к каждому временному полю
        "start_time": apply_offset(rental.start_time),
        "end_time": apply_offset(rental.end_time),
        "reservation_time": apply_offset(rental.reservation_time),
        "photos_before": rental.photos_before,
        "photos_after": rental.photos_after,
        "already_payed": rental.already_payed,
        "total_price": rental.total_price,
        "rental_status": rental.rental_status.value,
        "base_price": rental.base_price,
        "open_fee": rental.open_fee,
        "delivery_fee": rental.delivery_fee,
        "waiting_fee": rental.waiting_fee,
        "overtime_fee": rental.overtime_fee,
        "distance_fee": rental.distance_fee,
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
            "transmission_type": car.transmission_type,
            "body_type": car.body_type,
            "auto_class": car.auto_class,
            "year": car.year,
            "status": car.status,
        }

    rental_detail["action_history"] = [
        {
            "action_type": action.action_type.value,
            "timestamp": apply_offset(action.timestamp)
        }
        for action in rental.actions
        if action.user_id == current_user.id
    ]

    # Добавляем данные маршрута с GPS координатами
    route_data = None
    if car and car.gps_id and rental.start_time and rental.end_time:
        try:
            print(f"DEBUG: Fetching GPS data for car {car.id}, gps_id: {car.gps_id}")
            print(f"DEBUG: Start time: {rental.start_time}, End time: {rental.end_time}")
            
            route_data = await get_gps_route_data(
                device_id=car.gps_id,
                start_date=apply_offset(rental.start_time),
                end_date=apply_offset(rental.end_time)
            )
            
            if route_data:
                print(f"DEBUG: GPS data received - {route_data.total_coordinates} coordinates")
            else:
                print("DEBUG: GPS data is None")
                
        except Exception as e:
            print(f"DEBUG: GPS fetch error: {e}")
            route_data = None
    else:
        print(f"DEBUG: Missing GPS data - car: {car is not None}, gps_id: {car.gps_id if car else 'N/A'}, times: {rental.start_time}, {rental.end_time}")

    # Добавляем данные маршрута в ответ
    rental_detail["route_map"] = {
        "start_latitude": rental.start_latitude,
        "start_longitude": rental.start_longitude,
        "end_latitude": rental.end_latitude,
        "end_longitude": rental.end_longitude,
        "route_data": route_data.dict() if route_data else None
    }

    return {"rental_history_detail": rental_detail}


@RentRouter.post("/add_money")
def add_money(amount: int,
              db: Session = Depends(get_db),
              current_user: User = Depends(get_current_user)):
    # 1) Ищем у юзера активный промокод
    up = db.query(UserPromoCode) \
        .filter_by(user_id=current_user.id, status=UserPromoStatus.ACTIVATED) \
        .join(PromoCode) \
        .first()

    bonus = 0
    promo_applied = False

    if up:
        # считать бонус
        bonus = int(amount * (float(up.promo.discount_percent) / 100))
        promo_applied = True

        # начисляем основную сумму + бонус
        current_user.wallet_balance += amount + bonus

        # меняем статус промокода
        up.status = UserPromoStatus.USED
        up.used_at = datetime.utcnow()

    else:
        # обычное пополнение
        current_user.wallet_balance += amount

    db.commit()

    return {
        "wallet_balance": float(current_user.wallet_balance),
        "bonus": bonus,
        "promo_applied": promo_applied
    }


class ApplyPromoRequest(BaseModel):
    code: str


@RentRouter.post("/promo_codes/apply")
def apply_promo(body: ApplyPromoRequest,
                db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    # 1) Проверяем, нет ли уже активного у юзера
    exist = db.query(UserPromoCode) \
        .filter_by(user_id=current_user.id, status=UserPromoStatus.ACTIVATED) \
        .first()
    if exist:
        raise HTTPException(400, "У вас уже есть неиспользованный промокод")

    # 2) Находим активный промокод
    promo = db.query(PromoCode) \
        .filter_by(code=body.code, is_active=True) \
        .first()
    if not promo:
        raise HTTPException(404, "Промокод не найден или неактивен")

    # 3) Создаём связь
    up = UserPromoCode(user_id=current_user.id, promo_code_id=promo.id)
    db.add(up)
    db.commit()
    return {
        "message": "Промокод активирован",
        "code": promo.code,
        "discount_percent": float(promo.discount_percent)
    }


@RentRouter.post("/reserve-car/{car_id}")
async def reserve_car(
        car_id: int,
        rental_type: RentalType,
        duration: Optional[int] = None,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    # 0) Узнаём владельца машины, чтобы корректно применить проверки
    car_meta = db.query(Car.id, Car.owner_id, Car.status).filter(Car.id == car_id).first()
    if not car_meta:
        raise HTTPException(status_code=404, detail="Car not found")

    # Запреты по ролям/верификации для НЕ владельцев
    if car_meta.owner_id != current_user.id:
        if current_user.role == UserRole.CLIENT:
            raise HTTPException(status_code=403, detail="Для аренды необходимо пройти верификацию документов")
        if current_user.role == UserRole.USER:
            if not bool(current_user.documents_verified):
                raise HTTPException(status_code=403, detail="Для аренды необходимо пройти верификацию документов")
            # Требуем одобрения финансиста и МВД
            application = (
                db.query(Application)
                .filter(Application.user_id == current_user.id)
                .first()
            )
            if not application or application.financier_status != ApplicationStatus.APPROVED or application.mvd_status != ApplicationStatus.APPROVED:
                raise HTTPException(status_code=403, detail="Для аренды требуется одобрение финансиста и МВД")

    # 1) Проверяем, нет ли у пользователя уже активной аренды
    active_rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status.in_([
            RentalStatus.RESERVED,
            RentalStatus.IN_USE
        ])
    ).first()
    if active_rental:
        raise HTTPException(
            status_code=400,
            detail="У вас уже есть активная аренда. Завершите текущую аренду, прежде чем бронировать новую машину."
        )

    # 2) Выбираем машину только если она доступна (status == "FREE")
    car = db.query(Car).filter(
        Car.id == car_id,
        Car.status == "FREE"
    ).first()
    if not car:
        raise HTTPException(status_code=404, detail="Car not found or not available")

    orig_open_fee = get_open_price(car)
    open_fee = orig_open_fee if rental_type in (RentalType.MINUTES, RentalType.HOURS) else 0

    # стоимость открытия
    price_per_hour = car.price_per_hour
    price_per_day = car.price_per_day

    if car.owner_id == current_user.id:
        # Перед тем как владелец «снимет с аренды» (берёт у себя),
        # проверяем, нет ли активных/запланированных аренд клиентов
        blocking_statuses = [
            RentalStatus.RESERVED,
            RentalStatus.IN_USE,
            RentalStatus.DELIVERY_RESERVED,
            RentalStatus.DELIVERING,
            RentalStatus.DELIVERING_IN_PROGRESS,
            RentalStatus.SCHEDULED,
        ]

        active_client_rental = (
            db.query(RentalHistory)
            .filter(
                RentalHistory.car_id == car.id,
                RentalHistory.rental_status.in_(blocking_statuses),
                RentalHistory.user_id != current_user.id,
            )
            .first()
        )

        if active_client_rental:
            raise HTTPException(
                status_code=400,
                detail="Нельзя снять с аренды: автомобиль забронирован/в доставке/в использовании клиентом",
            )

        # Владелец берёт свою машину бесплатно
        total_price = 0
        rental = RentalHistory(
            user_id=current_user.id,
            car_id=car.id,
            rental_type=rental_type,
            duration=duration,
            rental_status=RentalStatus.RESERVED,
            start_latitude=car.latitude,
            start_longitude=car.longitude,
            base_price=0,
            open_fee=0,
            delivery_fee=0,
            waiting_fee=0,
            overtime_fee=0,
            distance_fee=0,
            total_price=total_price,
            reservation_time=datetime.utcnow()
        )
        db.add(rental)
        db.commit()
        db.refresh(rental)

        # Обновляем статус машины
        car.current_renter_id = current_user.id
        car.status = "OWNER"
        db.commit()

        return {
            "message": "Car reserved successfully (owner rental)",
            "rental_id": rental.id,
            "reservation_time": rental.reservation_time.isoformat()
        }

    # НЕ владельцу – проверка баланса
    if rental_type == RentalType.MINUTES:
        # требуемая сумма: открытие + 2 часа
        required_balance = open_fee + price_per_hour * 2
        if current_user.wallet_balance < required_balance:
            raise InsufficientBalanceException(required_amount=required_balance)
        base = 0

    elif rental_type == RentalType.HOURS:
        if duration is None:
            raise HTTPException(status_code=400, detail="Duration обязателен для аренды по часам.")
        # требуемая сумма: (duration + 2) * price_per_hour + открытие
        required_balance = (duration + 2) * price_per_hour + open_fee
        if current_user.wallet_balance < required_balance:
            raise InsufficientBalanceException(required_amount=required_balance)

        base = calculate_total_price(rental_type, duration, price_per_hour, price_per_day)

    else:  # RentalType.DAYS
        if duration is None:
            raise HTTPException(status_code=400, detail="Duration обязателен для посуточной аренды.")
        # требуемая сумма: duration * price_per_day + 2 часа (без open_fee)
        two_hours_fee = price_per_hour * 2
        required_balance = duration * price_per_day + two_hours_fee
        if current_user.wallet_balance < required_balance:
            raise InsufficientBalanceException(required_amount=required_balance)

        base = calculate_total_price(rental_type, duration, price_per_hour, price_per_day)

    # Если всё ок, создаём бронь
    rental = RentalHistory(
        user_id=current_user.id,
        car_id=car.id,
        rental_type=rental_type,
        duration=duration,
        rental_status=RentalStatus.RESERVED,
        start_latitude=car.latitude,
        start_longitude=car.longitude,
        base_price=base,
        open_fee=open_fee,
        delivery_fee=0,
        waiting_fee=0,
        overtime_fee=0,
        distance_fee=0,
        total_price=base + open_fee,
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
    Резервирование машины с доставкой:
    - car_id, rental_type, delivery координаты, опционально duration.
    - Дополнительно списываем 10000₸ за услугу доставки, если арендатор не является владельцем.
    """
    # Запреты по ролям/верификации
    if current_user.role == UserRole.CLIENT:
        raise HTTPException(status_code=403, detail="Для оформления аренды с доставкой необходимо пройти верификацию документов")
    if current_user.role == UserRole.USER and not bool(current_user.documents_verified):
        raise HTTPException(status_code=403, detail="Для оформления аренды с доставкой необходимо пройти верификацию документов")

    # 1) Проверяем, нет ли у пользователя активной аренды (RESERVED, IN_USE или DELIVERING)
    active_rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status.in_([
            RentalStatus.RESERVED,
            RentalStatus.IN_USE,
            RentalStatus.DELIVERING
        ])
    ).first()
    if active_rental:
        raise HTTPException(
            status_code=400,
            detail="У вас уже есть активная аренда или заказ доставки."
        )

    # 2) Выбираем машину только если она доступна (status == "FREE")
    car = db.query(Car).filter(
        Car.id == car_id,
        Car.status == "FREE"
    ).first()
    if not car:
        raise HTTPException(status_code=404, detail="Машина не найдена или не доступна")

    orig_open_fee = get_open_price(car)
    open_fee = orig_open_fee if rental_type in (RentalType.MINUTES, RentalType.HOURS) else 0

    price_per_hour = car.price_per_hour
    price_per_day = car.price_per_day
    extra_fee = 10_000  # стоимость доставки

    base_price = 0
    delivery_fee = 0
    total_price = 0

    if car.owner_id == current_user.id:
        delivery_fee = 5_000  # только 5к берем с владельца
        open_fee = 0  # остальное бесплатно
        base_price = 0  # база бесплатна
        total_price = delivery_fee  # к оплате только доставка

        # ### Проверяем и списываем у владельца 5к
        if current_user.wallet_balance < delivery_fee:
            raise InsufficientBalanceException(required_amount=delivery_fee)
        current_user.wallet_balance -= delivery_fee

        db.commit()
    else:
        # НЕ владелец — сбор за доставку
        delivery_fee = extra_fee

        if rental_type == RentalType.MINUTES:
            # требуемая сумма: открытие + 2 часа + доставка
            required_balance = open_fee + price_per_hour * 2 + delivery_fee
            if current_user.wallet_balance < required_balance:
                raise InsufficientBalanceException(required_amount=required_balance)

            base_price = 0
            total_price = delivery_fee  # пока в total_price только плата за доставку

        elif rental_type == RentalType.HOURS:
            if duration is None:
                raise HTTPException(status_code=400, detail="Duration обязателен для аренды по часам.")
            # требуемая сумма: (duration + 2)×price_per_hour + открытие + доставка
            required_balance = (duration + 2) * price_per_hour + open_fee + delivery_fee
            if current_user.wallet_balance < required_balance:
                raise InsufficientBalanceException(required_amount=required_balance)

            base_price = calculate_total_price(rental_type, duration, price_per_hour, price_per_day)
            total_price = base_price + open_fee + delivery_fee

        else:  # RentalType.DAYS
            if duration is None:
                raise HTTPException(status_code=400, detail="Duration обязателен для посуточной аренды.")
            # требуемая сумма: duration×price_per_day + 2 часа + доставка (без open_fee)
            two_hours_fee = price_per_hour * 2
            required_balance = duration * price_per_day + two_hours_fee + delivery_fee
            if current_user.wallet_balance < required_balance:
                raise InsufficientBalanceException(required_amount=required_balance)
            base_price = calculate_total_price(rental_type, duration, price_per_hour, price_per_day)
            total_price = base_price + two_hours_fee + delivery_fee

        # Если не владелец, сразу списываем доставку
        current_user.wallet_balance -= delivery_fee
        db.commit()

    # Создаём запись о доставке
    rental = RentalHistory(
        user_id=current_user.id,
        car_id=car.id,
        rental_type=rental_type,
        duration=duration,
        rental_status=RentalStatus.DELIVERING,
        start_latitude=car.latitude,
        start_longitude=car.longitude,
        base_price=base_price,
        open_fee=open_fee if car.owner_id != current_user.id else 0,
        delivery_fee=delivery_fee,
        waiting_fee=0,
        overtime_fee=0,
        distance_fee=0,
        total_price=total_price,
        reservation_time=datetime.utcnow(),
        delivery_latitude=delivery_latitude,
        delivery_longitude=delivery_longitude
    )
    db.add(rental)
    db.commit()
    db.refresh(rental)

    # Обновляем статус машины
    car.current_renter_id = current_user.id
    car.status = "DELIVERING"
    db.commit()

    # Уведомляем всех механиков
    notification_title = "Доставка: новый заказ"
    notification_body = f"Нужно доставить клиенту {car.name} ({car.plate_number})."
    await send_notification_to_all_mechanics_async(db, notification_title, notification_body)

    return {
        "message": "Заказ доставки оформлен успешно",
        "rental_id": rental.id,
        "reservation_time": rental.reservation_time.isoformat(),
        "total_price": total_price
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
) -> Dict[str, Any]:
    """
    Отмена доставки (только если аренда в статусе DELIVERING).
    Деньги за доставку не возвращаем.
    Уведомляем назначенного механика, если он есть, и освобождаем автомобиль.
    """
    # Находим активный заказ доставки пользователя

    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status.in_([
            RentalStatus.DELIVERING,
            RentalStatus.DELIVERY_RESERVED,
            RentalStatus.DELIVERING_IN_PROGRESS
        ])
    ).first()
    if not rental:
        raise HTTPException(status_code=400, detail="Нет активного заказа доставки для отмены")

    # Получаем машину
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    # Сохраняем ID механика до его обнуления
    mech_id = rental.delivery_mechanic_id

    # Отменяем доставку
    rental.rental_status = RentalStatus.CANCELLED
    rental.end_time = datetime.utcnow()
    
    # Если доставка была в процессе, записываем время окончания
    if rental.delivery_start_time and not rental.delivery_end_time:
        rental.delivery_end_time = datetime.utcnow()
    
    rental.delivery_mechanic_id = None

    # Освобождаем машину
    car.current_renter_id = None
    car.status = "FREE"

    db.commit()
    db.refresh(rental)

    # Уведомляем механика, если был назначен
    if mech_id:
        title = "Доставка отменена"
        body = (
            f"Доставка автомобиля {car.name} ({car.plate_number}) по заказу #{rental.id} "
            "была отменена."
        )
        await send_push_to_user_by_id(db, mech_id, title, body)

    return {"message": "Доставка отменена успешно"}


@RentRouter.post("/start")
async def start_rental(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    # Запреты по ролям/верификации (на случай, если обошли резервацию)
    if current_user.role == UserRole.CLIENT:
        raise HTTPException(status_code=403, detail="Для начала аренды необходимо пройти верификацию документов")
    if current_user.role == UserRole.USER and not bool(current_user.documents_verified):
        raise HTTPException(status_code=403, detail="Для начала аренды необходимо пройти верификацию документов")

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

    rental.fuel_before = car.fuel_level
    rental.mileage_before = car.mileage

    if car.owner_id == current_user.id:
        # Логика для владельца: аренда бесплатная, пропускаем списание средств
        rental.rental_status = RentalStatus.IN_USE
        rental.start_time = datetime.utcnow()
        # новые поля расчётов при старте
        rental.open_fee = 0
        # waiting_fee, overtime_fee, distance_fee остаются прежними (nullable)
        db.commit()
        return {"message": "Rental started successfully (owner rental)", "rental_id": rental.id}
    else:
        # Если аренда минутная или часовая, списываем с баланса open_price, вычисленный через get_open_price
        if rental.rental_type in [RentalType.MINUTES, RentalType.HOURS]:
            open_price = get_open_price(car)
            rental.open_fee = open_price

        rental.rental_status = RentalStatus.IN_USE
        rental.start_time = datetime.utcnow()

        total_cost = rental.total_price

        if total_cost > 0:
            if current_user.wallet_balance < total_cost:
                raise HTTPException(
                    status_code=402,
                    detail=f"Нужно минимум {total_cost} ₸ для старта. Пополните кошелёк!"
                )
            current_user.wallet_balance -= total_cost
            rental.already_payed = total_cost

        # Обновляем машину: меняем статус на IN_USE
        car.status = "IN_USE"

        db.commit()

        return {"message": "Rental started successfully", "rental_id": rental.id}


@RentRouter.post("/upload-photos-before")
async def upload_photos_before(
        selfie: UploadFile = File(...),
        car_photos: list[UploadFile] = File(...),
        interior_photos: list[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    Загружает фотографии до начала аренды:
    - selfie: фото пользователя с машиной;
    - car_photos: внешние фото машины (1-10);
    - interior_photos: фото салона машины (1-10).
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="No active rental in IN_USE status found")

    validate_photos([selfie], 'selfie')
    validate_photos(car_photos, 'car_photos')
    validate_photos(interior_photos, 'interior_photos')

    try:
        urls = []
        # save selfie
        urls.append(await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/before/selfie/"))
        # save exterior
        for p in car_photos:
            urls.append(await save_file(p, rental.id, f"uploads/rents/{rental.id}/before/car/"))
        # save interior
        for p in interior_photos:
            urls.append(await save_file(p, rental.id, f"uploads/rents/{rental.id}/before/interior/"))

        rental.photos_before = urls
        db.commit()
        return {"message": "Photos before rental uploaded", "photo_count": len(urls)}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Error uploading photos before")


@RentRouter.post("/upload-photos-after")
async def upload_photos_after(
        selfie: UploadFile = File(...),
        car_photos: list[UploadFile] = File(...),
        interior_photos: list[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    Фотографии после завершения аренды:
    - selfie: фото пользователя;
    - car_photos: внешние фото (1-10);
    - interior_photos: фото салона (1-10).
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="No active rental in IN_USE status found")

    validate_photos([selfie], 'selfie')
    validate_photos(car_photos, 'car_photos')
    validate_photos(interior_photos, 'interior_photos')

    try:
        urls = []
        urls.append(await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/after/selfie/"))
        for p in car_photos:
            urls.append(await save_file(p, rental.id, f"uploads/rents/{rental.id}/after/car/"))
        for p in interior_photos:
            urls.append(await save_file(p, rental.id, f"uploads/rents/{rental.id}/after/interior/"))

        rental.photos_after = urls
        db.commit()
        return {"message": "Photos after rental uploaded", "photo_count": len(urls)}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Error uploading photos after")


# Owner endpoints (без селфи)
@RentRouter.post("/upload-photos-before-owner")
async def upload_photos_before_owner(
        car_photos: list[UploadFile] = File(...),
        interior_photos: list[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """Фотографии до аренды для владельца (1-10 внешних, 1-10 салона)."""
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="No active rental in IN_USE status found")
    car = db.query(Car).get(rental.car_id)
    if car.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your car")
    validate_photos(car_photos, 'car_photos')
    validate_photos(interior_photos, 'interior_photos')

    try:
        urls = []
        for p in car_photos:
            urls.append(await save_file(p, rental.id, f"uploads/rents/{rental.id}/before/car/"))
        for p in interior_photos:
            urls.append(await save_file(p, rental.id, f"uploads/rents/{rental.id}/before/interior/"))

        rental.photos_before = urls
        db.commit()
        return {"message": "Owner photos before uploaded", "photo_count": len(urls)}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Error uploading owner photos before")


@RentRouter.post("/upload-photos-after-owner")
async def upload_photos_after_owner(
        car_photos: list[UploadFile] = File(...),
        interior_photos: list[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """Фотографии после аренды для владельца (1-10 внешних, 1-10 салона)."""
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="No active rental in IN_USE status found")
    car = db.query(Car).get(rental.car_id)
    if car.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your car")
    validate_photos(car_photos, 'car_photos')
    validate_photos(interior_photos, 'interior_photos')

    try:
        urls = []
        for p in car_photos:
            urls.append(await save_file(p, rental.id, f"uploads/rents/{rental.id}/after/car/"))
        for p in interior_photos:
            urls.append(await save_file(p, rental.id, f"uploads/rents/{rental.id}/after/interior/"))

        rental.photos_after = urls
        db.commit()
        return {"message": "Owner photos after uploaded", "photo_count": len(urls)}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Error uploading owner photos after")


class RentalReviewInput(BaseModel):
    rating: conint(ge=1, le=5) = Field(..., description="Оценка от 1 до 5")
    comment: Optional[constr(max_length=255)] = Field(None, description="Комментарий к аренде (до 255 символов)")


async def check_vehicle_status_for_completion(vehicle_imei: str) -> Dict[str, Any]:
    """
    Проверяет состояние автомобиля для завершения аренды.
    Возвращает ошибки если автомобиль не готов к завершению аренды.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://195.93.152.69:8666/vehicles/?skip=0&limit=100")
            response.raise_for_status()
            vehicles = response.json()
            
            # Найти нужный автомобиль по IMEI
            vehicle = None
            for v in vehicles:
                if v.get("vehicle_imei") == vehicle_imei:
                    vehicle = v
                    break
            
            if not vehicle:
                return {"error": "Автомобиль не найден в системе мониторинга"}
            
            errors = []
            
            # Проверка капота (категорически запрещено открывать)
            if vehicle.get("is_hood_open", False):
                errors.append("Капот открыт! Категорически запрещено открывать капот. Штраф 1,000,000 тг")
            
            # Проверка багажника
            if vehicle.get("is_trunk_open", False):
                errors.append("Для завершения аренды пожалуйста закройте багажник")
            
            # Проверка дверей
            doors_open = []
            if vehicle.get("front_left_door_open", False):
                doors_open.append("передняя левая")
            if vehicle.get("front_right_door_open", False):
                doors_open.append("передняя правая")
            if vehicle.get("rear_left_door_open", False):
                doors_open.append("задняя левая")
            if vehicle.get("rear_right_door_open", False):
                doors_open.append("задняя правая")
            
            if doors_open:
                errors.append(f"Для завершения аренды пожалуйста закройте двери: {', '.join(doors_open)}")
            
            # Проверка окон (должны быть закрыты)
            windows_open = []
            if not vehicle.get("front_left_window_closed", True):
                windows_open.append("переднее левое")
            if not vehicle.get("front_right_window_closed", True):
                windows_open.append("переднее правое")
            if not vehicle.get("rear_left_window_closed", True):
                windows_open.append("заднее левое")
            if not vehicle.get("rear_right_window_closed", True):
                windows_open.append("заднее правое")
            
            if windows_open:
                errors.append(f"Для завершения аренды пожалуйста закройте окна: {', '.join(windows_open)}")
            
            # Проверка ручника (должен быть включен)
            if not vehicle.get("is_handbrake_on", True):
                errors.append("Для завершения аренды пожалуйста активируйте стояночный тормоз")
            
            # Проверка фар (должны быть выключены или в режиме AUTO)
            if vehicle.get("are_lights_on", False) and not vehicle.get("is_light_auto_mode_on", False):
                errors.append("Для завершения аренды пожалуйста выключите фары или переведите в режим AUTO")
            
            # Проверка двигателя (обороты должны быть 0)
            if vehicle.get("rpm", 0) > 0:
                errors.append("Для завершения аренды пожалуйста заглушите двигатель")
            
            return {"errors": errors, "vehicle": vehicle}
            
    except Exception as e:
        return {"error": f"Ошибка при проверке состояния автомобиля: {str(e)}"}


@RentRouter.post("/complete")
async def complete_rental(
        review_input: Optional[RentalReviewInput] = None,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    # 1) Найти активную аренду
    rental = (
        db.query(RentalHistory)
        .with_for_update()
        .filter(
            RentalHistory.user_id == current_user.id,
            RentalHistory.rental_status == RentalStatus.IN_USE
        )
        .first()
    )

    if not rental:
        raise HTTPException(status_code=404, detail="No active rental found")

    # 2) Загрузить машину
    car = db.query(Car).get(rental.car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    # 3) Проверить состояние автомобиля для завершения аренды
    vehicle_status = await check_vehicle_status_for_completion(car.gps_imei)
    
    if "error" in vehicle_status:
        raise HTTPException(status_code=400, detail=vehicle_status["error"])
    
    if vehicle_status.get("errors"):
        error_message = "Нельзя завершить аренду:\n" + "\n".join(vehicle_status["errors"])
        raise HTTPException(status_code=400, detail=error_message)

    # 4) Завершить аренду: время, координаты, состояние
    now = datetime.utcnow()
    rental.end_time = now
    rental.end_latitude = car.latitude
    rental.end_longitude = car.longitude
    rental.fuel_after = car.fuel_level
    rental.mileage_after = car.mileage
    rental.rental_status = RentalStatus.COMPLETED

    # Освободить машину
    car.current_renter_id = None
    car.status = "PENDING"

    # 5) Сохранить отзыв (если есть)
    if review_input:
        review = RentalReview(
            rental_id=rental.id,
            rating=review_input.rating,
            comment=review_input.comment
        )
        db.add(review)

    # 6) Рассчитать фактическую длительность в минутах
    total_seconds = (now - rental.start_time).total_seconds()
    actual_minutes = total_seconds / 60
    rounded_minutes = ceil(actual_minutes)

    # 7) Базовая плата по типу аренды
    if rental.rental_type == RentalType.MINUTES:
        rental.base_price = rounded_minutes * car.price_per_minute
    elif rental.rental_type == RentalType.HOURS:
        rental.base_price = rental.duration * car.price_per_hour
    else:  # DAYS
        rental.base_price = rental.duration * car.price_per_day

    # 8) Переработка для часов/дней
    if rental.rental_type in (RentalType.HOURS, RentalType.DAYS):
        planned_minutes = (
            rental.duration * 60
            if rental.rental_type == RentalType.HOURS
            else rental.duration * 24 * 60
        )
        overtime_mins = max(0, rounded_minutes - planned_minutes)
        rental.overtime_fee = overtime_mins * car.price_per_minute
    else:
        rental.overtime_fee = 0

    # 9) Убедиться, что все сборы не None
    rental.open_fee = rental.open_fee or 0
    rental.delivery_fee = rental.delivery_fee or 0
    rental.waiting_fee = rental.waiting_fee or 0
    rental.distance_fee = rental.distance_fee or 0

    # 10) Если арендатор — владелец, обнуляем все сборы
    if car.owner_id == current_user.id:
        rental.base_price = 0
        rental.open_fee = 0
        rental.delivery_fee = 0
        rental.waiting_fee = 0
        rental.overtime_fee = 0
        rental.distance_fee = 0

    # 11) Итоговая сумма и списание
    rental.total_price = (
            rental.base_price + rental.open_fee + rental.delivery_fee +
            rental.waiting_fee + rental.overtime_fee + rental.distance_fee
    )
    previous_paid = rental.already_payed or 0
    amount_to_charge = rental.total_price - previous_paid

    # Баланс может уходить в минус — это допустимо
    current_user.wallet_balance -= amount_to_charge
    rental.already_payed = rental.total_price

    # 12) Коммит и уведомление механиков
    db.commit()
    try:
        await send_notification_to_all_mechanics_async(
            db,
            "Новая машина для осмотра",
            f"Аренда автомобиля {car.name} ({car.plate_number}) завершена. Требуется осмотр."
        )
    except Exception as e:
        print(e)

    return {
        "message": "Rental completed successfully",
        "rental_details": {
            "total_duration_minutes": rounded_minutes,
            "total_price": rental.total_price,
            "amount_charged_now": amount_to_charge,
            "current_wallet_balance": float(current_user.wallet_balance)
        },
        "review": {
            "rating": review.rating,
            "comment": review.comment
        } if review_input else None
    }


# ============================================================================
# НОВЫЕ ENDPOINTS ДЛЯ БРОНИРОВАНИЯ ЗАРАНЕЕ
# ============================================================================

@RentRouter.post("/advance-booking", response_model=BookingResponse)
async def create_advance_booking(
    booking_request: AdvanceBookingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Создание бронирования заранее с указанием даты и времени
    """
    # 1) Проверяем, нет ли у пользователя уже активной аренды
    active_rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status.in_([
            RentalStatus.RESERVED,
            RentalStatus.IN_USE,
            RentalStatus.SCHEDULED
        ])
    ).first()
    if active_rental:
        raise HTTPException(
            status_code=400,
            detail="У вас уже есть активная аренда или бронирование. Завершите текущую аренду, прежде чем бронировать новую машину."
        )

    # 2) Проверяем, что запланированное время в будущем
    now = datetime.utcnow()
    if booking_request.scheduled_start_time <= now:
        raise HTTPException(
            status_code=400,
            detail="Запланированное время начала должно быть в будущем"
        )

    # 3) Выбираем машину только если она доступна
    car = db.query(Car).filter(
        Car.id == booking_request.car_id,
        Car.status == "FREE"
    ).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден или не доступен")

    # 4) Проверяем, что автомобиль не забронирован на это время
    conflicting_booking = db.query(RentalHistory).filter(
        RentalHistory.car_id == booking_request.car_id,
        RentalHistory.rental_status.in_([
            RentalStatus.RESERVED,
            RentalStatus.IN_USE,
            RentalStatus.SCHEDULED
        ]),
        RentalHistory.scheduled_start_time <= booking_request.scheduled_start_time,
        RentalHistory.scheduled_end_time >= booking_request.scheduled_start_time
    ).first()
    
    if conflicting_booking:
        raise HTTPException(
            status_code=400,
            detail="Автомобиль уже забронирован на это время"
        )

    # 5) Рассчитываем запланированное время окончания
    if booking_request.scheduled_end_time is None:
        if booking_request.rental_type == RentalType.MINUTES:
            # Для поминутной аренды используем 2 часа по умолчанию
            booking_request.scheduled_end_time = booking_request.scheduled_start_time + timedelta(hours=2)
        elif booking_request.rental_type == RentalType.HOURS:
            if booking_request.duration is None:
                raise HTTPException(status_code=400, detail="Duration обязателен для аренды по часам")
            booking_request.scheduled_end_time = booking_request.scheduled_start_time + timedelta(hours=booking_request.duration)
        else:  # DAYS
            if booking_request.duration is None:
                raise HTTPException(status_code=400, detail="Duration обязателен для посуточной аренды")
            booking_request.scheduled_end_time = booking_request.scheduled_start_time + timedelta(days=booking_request.duration)

    # 6) Рассчитываем стоимость
    orig_open_fee = get_open_price(car)
    open_fee = orig_open_fee if booking_request.rental_type in (RentalType.MINUTES, RentalType.HOURS) else 0
    
    price_per_hour = car.price_per_hour
    price_per_day = car.price_per_day
    
    if booking_request.rental_type == RentalType.MINUTES:
        base = 0  # Для поминутной аренды цена не считается заранее
    elif booking_request.rental_type == RentalType.HOURS:
        base = calculate_total_price(booking_request.rental_type, booking_request.duration, price_per_hour, price_per_day)
    else:  # DAYS
        base = calculate_total_price(booking_request.rental_type, booking_request.duration, price_per_hour, price_per_day)

    # 7) Создаем бронирование
    rental = RentalHistory(
        user_id=current_user.id,
        car_id=car.id,
        rental_type=booking_request.rental_type,
        duration=booking_request.duration,
        rental_status=RentalStatus.SCHEDULED,
        start_latitude=car.latitude,
        start_longitude=car.longitude,
        base_price=base,
        open_fee=open_fee,
        delivery_fee=0,
        waiting_fee=0,
        overtime_fee=0,
        distance_fee=0,
        total_price=base + open_fee,
        reservation_time=datetime.utcnow(),
        scheduled_start_time=booking_request.scheduled_start_time,
        scheduled_end_time=booking_request.scheduled_end_time,
        is_advance_booking="true",
        delivery_latitude=booking_request.delivery_latitude,
        delivery_longitude=booking_request.delivery_longitude
    )
    
    db.add(rental)
    db.commit()
    db.refresh(rental)

    # 8) Обновляем машину: устанавливаем текущего арендатора и меняем статус
    car.current_renter_id = current_user.id
    car.status = "SCHEDULED"
    db.commit()

    return BookingResponse(
        message="Автомобиль успешно забронирован заранее",
        rental_id=rental.id,
        reservation_time=rental.reservation_time.isoformat(),
        scheduled_start_time=rental.scheduled_start_time.isoformat() if rental.scheduled_start_time else None,
        scheduled_end_time=rental.scheduled_end_time.isoformat() if rental.scheduled_end_time else None,
        is_advance_booking=True
    )


@RentRouter.get("/my-bookings", response_model=List[BookingListResponse])
async def get_my_bookings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Получить список всех бронирований пользователя (включая забронированные заранее)
    """
    bookings = (
        db.query(RentalHistory, Car)
        .join(Car, Car.id == RentalHistory.car_id)
        .filter(
            RentalHistory.user_id == current_user.id,
            RentalHistory.rental_status.in_([
                RentalStatus.RESERVED,
                RentalStatus.IN_USE,
                RentalStatus.SCHEDULED,
                RentalStatus.DELIVERY_RESERVED,
                RentalStatus.DELIVERING
            ])
        )
        .order_by(RentalHistory.reservation_time.desc())
        .all()
    )

    result = []
    for rental, car in bookings:
        result.append(BookingListResponse(
            id=rental.id,
            car_id=rental.car_id,
            car_name=car.name,
            car_plate_number=car.plate_number,
            rental_type=rental.rental_type,
            duration=rental.duration,
            scheduled_start_time=rental.scheduled_start_time,
            scheduled_end_time=rental.scheduled_end_time,
            start_time=rental.start_time,
            end_time=rental.end_time,
            rental_status=rental.rental_status,
            total_price=rental.total_price,
            base_price=rental.base_price,
            open_fee=rental.open_fee,
            delivery_fee=rental.delivery_fee,
            reservation_time=rental.reservation_time,
            is_advance_booking=rental.is_advance_booking == "true",
            car_photos=car.photos
        ))

    return result


@RentRouter.post("/cancel-booking/{rental_id}", response_model=CancelBookingResponse)
async def cancel_booking(
    rental_id: int,
    cancel_request: CancelBookingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Отменить бронирование
    """
    # 1) Находим бронирование
    rental = db.query(RentalHistory).filter(
        RentalHistory.id == rental_id,
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status.in_([
            RentalStatus.RESERVED,
            RentalStatus.SCHEDULED,
            RentalStatus.DELIVERY_RESERVED
        ])
    ).first()
    
    if not rental:
        raise HTTPException(status_code=404, detail="Бронирование не найдено или уже отменено")

    # 2) Загружаем автомобиль
    car = db.query(Car).get(rental.car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    # 3) Рассчитываем возврат (если есть предоплата)
    refund_amount = 0
    if rental.already_payed and rental.already_payed > 0:
        # Возвращаем предоплату
        refund_amount = rental.already_payed
        current_user.wallet_balance += refund_amount
        rental.already_payed = 0

    # 4) Отменяем бронирование
    rental.rental_status = RentalStatus.CANCELLED
    
    # 5) Освобождаем автомобиль
    car.current_renter_id = None
    car.status = "FREE"
    
    db.commit()

    return CancelBookingResponse(
        message="Бронирование успешно отменено",
        rental_id=rental.id,
        refund_amount=refund_amount
    )


@RentRouter.get("/available-cars")
async def get_available_cars_for_booking(
    scheduled_start_time: datetime = Query(..., description="Запланированное время начала"),
    scheduled_end_time: datetime = Query(..., description="Запланированное время окончания"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Получить список доступных автомобилей для бронирования на указанное время
    """
    # 1) Находим все автомобили, которые забронированы на это время
    conflicting_rentals = db.query(RentalHistory.car_id).filter(
        RentalHistory.rental_status.in_([
            RentalStatus.RESERVED,
            RentalStatus.IN_USE,
            RentalStatus.SCHEDULED
        ]),
        RentalHistory.scheduled_start_time <= scheduled_end_time,
        RentalHistory.scheduled_end_time >= scheduled_start_time
    ).subquery()

    # 2) Находим доступные автомобили
    available_cars = db.query(Car).filter(
        Car.status == "FREE",
        ~Car.id.in_(conflicting_rentals)
    ).all()

    result = []
    for car in available_cars:
        result.append({
            "id": car.id,
            "name": car.name,
            "plate_number": car.plate_number,
            "price_per_minute": car.price_per_minute,
            "price_per_hour": car.price_per_hour,
            "price_per_day": car.price_per_day,
            "auto_class": car.auto_class,
            "body_type": car.body_type,
            "transmission_type": car.transmission_type,
            "photos": car.photos,
            "description": car.description
        })

    return {
        "available_cars": result,
        "scheduled_start_time": scheduled_start_time.isoformat(),
        "scheduled_end_time": scheduled_end_time.isoformat()
    }
