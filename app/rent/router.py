from math import floor, ceil
import asyncio
from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, status, Query
from pydantic import BaseModel, constr, Field, conint
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import httpx
import uuid

from app.utils.short_id import safe_sid_to_uuid, uuid_to_sid
from app.utils.sid_converter import convert_uuid_response_to_sid

from app.auth.dependencies.get_current_user import get_current_user
from app.auth.dependencies.save_documents import save_file, validate_photos
from app.dependencies.database.database import get_db
from app.models.history_model import RentalType, RentalStatus, RentalHistory, RentalReview
from app.models.promo_codes_model import PromoCode, UserPromoCode, UserPromoStatus
from app.models.user_model import User, UserRole
from app.models.application_model import Application, ApplicationStatus
from app.models.car_model import Car, CarStatus, CarAutoClass
from app.models.contract_model import UserContractSignature, ContractFile, ContractType
from app.models.guarantor_model import Guarantor
from app.push.utils import send_notification_to_all_mechanics_async, send_push_to_user_by_id, send_localized_notification_to_user, send_localized_notification_to_all_mechanics
from app.rent.exceptions import InsufficientBalanceException
from app.wallet.utils import record_wallet_transaction
from app.models.wallet_transaction_model import WalletTransactionType, WalletTransaction
from app.rent.utils.calculate_price import calculate_total_price, get_open_price, calc_required_balance
from app.gps_api.utils.route_data import get_gps_route_data
from app.gps_api.utils.auth_api import get_auth_token
from app.gps_api.utils.car_data import auto_lock_vehicle_after_rental, execute_gps_sequence, send_open, send_unlock_engine
from app.core.config import GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD
from app.utils.atomic_operations import delete_uploaded_files
from app.guarantor.sms_utils import send_rental_start_sms, send_rental_complete_sms
from app.owner.schemas import RouteData, RouteMapData
from app.admin.cars.utils import sort_car_photos
from app.rent.schemas import (
    AdvanceBookingRequest, 
    BookingResponse, 
    BookingListResponse, 
    CancelBookingRequest, 
    CancelBookingResponse
)
from pathlib import Path
from tempfile import NamedTemporaryFile
import shutil
from fastapi.concurrency import run_in_threadpool
from app.services.face_verify import verify_user_upload_against_profile

def _write_upload_to_temp(upload: UploadFile) -> str:
    tmp = NamedTemporaryFile(delete=False, suffix=Path(upload.filename or 'upload').suffix)
    with tmp as f:
        shutil.copyfileobj(upload.file, f)
    # вернуть курсор файла к началу, чтобы возможные повторные чтения не сломались
    try:
        upload.file.seek(0)
    except Exception:
        pass
    return tmp.name

RentRouter = APIRouter(tags=["Rent"], prefix="/rent")

OFFSET_HOURS = 5

# Цена за литр бензина (тг)
FUEL_PRICE_PER_LITER = 350
ELECTRIC_FUEL_PRICE_PER_LITER = 100


def get_user_available_auto_classes(user: User, db: Session) -> List[str]:
    if user.auto_class and len(user.auto_class) > 0:
        return user.auto_class
    
    if user.role == UserRole.REJECTFIRST:
        active_guarantor = db.query(Guarantor).join(User, Guarantor.guarantor_id == User.id).filter(
            Guarantor.client_id == user.id,
            Guarantor.is_active == True
        ).first()
        
        if active_guarantor and active_guarantor.guarantor_user.auto_class:
            return active_guarantor.guarantor_user.auto_class
    
    return []


def validate_user_can_rent(current_user: User, db: Session) -> None:
    """
    Валидация прав пользователя на аренду автомобилей.
    Проверяет роль и статус заявки пользователя.
    """
    # Владельцы могут арендовать свои машины всегда
    if current_user.role == UserRole.ADMIN:
        return  # Админы могут всё
    
    # Блокированные пользователи не могут арендовать
    if current_user.role in [UserRole.REJECTSECOND]:
        raise HTTPException(
            status_code=403, 
            detail="Доступ к аренде заблокирован. Обратитесь в поддержку."
        )
    
    # Пользователи без документов не могут арендовать
    if current_user.role == UserRole.CLIENT:
        raise HTTPException(
            status_code=403, 
            detail="Для аренды необходимо загрузить и верифицировать документы"
        )
    
    # Пользователи с неправильными документами не могут арендовать
    if current_user.role == UserRole.REJECTFIRSTDOC:
        raise HTTPException(
            status_code=403, 
            detail="Необходимо загрузить документы заново"
        )
    
    # Пользователи без сертификатов не могут арендовать
    if current_user.role == UserRole.REJECTFIRSTCERT:
        raise HTTPException(
            status_code=403, 
            detail="Необходимо прикрепить недостающие сертификаты"
        )
    
    # Пользователи с финансовыми проблемами не могут арендовать
    if current_user.role == UserRole.REJECTFIRST:
        active_guarantor = db.query(Guarantor).join(User, Guarantor.guarantor_id == User.id).filter(
            Guarantor.client_id == current_user.id,
            Guarantor.is_active == True
        ).first()
        
        if not active_guarantor or not active_guarantor.guarantor_user.auto_class:
            raise HTTPException(
                status_code=403, 
                detail="Аренда недоступна по финансовым причинам. Обратитесь к гаранту"
            )
    
    # Пользователи в процессе верификации не могут арендовать
    if current_user.role in [UserRole.PENDINGTOFIRST, UserRole.PENDINGTOSECOND]:
        raise HTTPException(
            status_code=403, 
            detail="Ваша заявка на рассмотрении. Дождитесь одобрения"
        )
    
    # Для роли USER проверяем полную верификацию
    if current_user.role == UserRole.USER:
        if not bool(current_user.documents_verified):
            raise HTTPException(
                status_code=403, 
                detail="Для аренды необходимо пройти верификацию документов"
            )
        
        # Проверяем одобрение финансиста и МВД
        application = (
            db.query(Application)
            .filter(Application.user_id == current_user.id)
            .first()
        )
        if not application or application.financier_status != ApplicationStatus.APPROVED or application.mvd_status != ApplicationStatus.APPROVED:
            raise HTTPException(
                status_code=403, 
                detail="Для аренды требуется одобрение заявки"
            )


def apply_offset(dt: datetime) -> str | None:
    return (dt + timedelta(hours=OFFSET_HOURS)).isoformat() if dt else None


@RentRouter.get("/history")
def get_trip_history(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> dict:
    # Получаем все завершенные поездки пользователя
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
        # Получаем отзыв для этой аренды
        review = db.query(RentalReview).filter(RentalReview.rental_id == rental.id).first()
        # Расчёт топливного сбора для отображения
        fuel_fee_display = 0
        if rental.fuel_before is not None and rental.fuel_after is not None:
            # Проверяем, что топливо реально уменьшилось
            if rental.fuel_after < rental.fuel_before:
                # Округляем в пользу платформы: fuel_before вверх, fuel_after вниз
                fuel_before_rounded = ceil(rental.fuel_before)
                fuel_after_rounded = floor(rental.fuel_after)
                fuel_consumed = fuel_before_rounded - fuel_after_rounded
                if fuel_consumed > 0:
                    is_owner = car.owner_id == rental.user_id
                    # Определяем цену за литр в зависимости от типа автомобиля
                    if car.body_type == "ELECTRIC":
                        price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
                    else:
                        price_per_liter = FUEL_PRICE_PER_LITER
                    
                    if is_owner:
                        # Владелец платит полную стоимость топлива
                        fuel_fee_display = int(fuel_consumed * price_per_liter)
                    elif rental.rental_type in (RentalType.HOURS, RentalType.DAYS):
                        # Для клиентов топливо включено в стоимость только для часов/дней
                        fuel_fee_display = int(fuel_consumed * price_per_liter)
        
        # Вычисляем сумму без топлива для отображения
        total_price_without_fuel = (
            (rental.base_price or 0)
            + rental.open_fee
            + rental.delivery_fee
            + rental.waiting_fee
            + rental.overtime_fee
            + rental.distance_fee
        )
        
        result.append({
            "history_id": rental.sid,
            # Сдвиг +5 ч
            "date": apply_offset(rental.end_time),
            "car_name": car.name,
            "final_total_price": rental.total_price,
            "total_price_without_fuel": total_price_without_fuel,
            # Детализация
            "base_price": rental.base_price or 0,
            "open_fee": rental.open_fee or 0,
            "delivery_fee": rental.delivery_fee or 0,
            "fuel_fee": fuel_fee_display,
            "waiting_fee": rental.waiting_fee or 0,
            "overtime_fee": rental.overtime_fee or 0,
            "distance_fee": rental.distance_fee or 0,
            # Топливо уровни
            "fuel_before": rental.fuel_before,
            "fuel_after": rental.fuel_after,
            # Фото клиента: до/после
            "client_photos_before": rental.photos_before or [],
            "client_photos_after": rental.photos_after or [],
            # Данные автомобиля
            "car_vin": car.vin,
            "car_color": car.color,
            # Фото механика при осмотре: до/после
            "mechanic_photos_before": rental.mechanic_photos_before or [],
            "mechanic_photos_after": rental.mechanic_photos_after or [],
            # GPS координаты маршрута
            "start_latitude": rental.start_latitude,
            "start_longitude": rental.start_longitude,
            "end_latitude": rental.end_latitude,
            "end_longitude": rental.end_longitude,
            # Отзывы
            "client_rating": review.rating if review else None,
            "client_comment": review.comment if review else None,
            "mechanic_rating": review.mechanic_rating if review else None,
            "mechanic_comment": review.mechanic_comment if review else None,
            "delivery_mechanic_rating": review.delivery_mechanic_rating if review else None,
            "delivery_mechanic_comment": review.delivery_mechanic_comment if review else None
        })

    return {"trip_history": result}


@RentRouter.get("/history/{history_id}")
async def get_trip_history_detail(
        history_id: str,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> dict:
    try:
        history_uuid = safe_sid_to_uuid(history_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат ID")
    
    rental = (
        db.query(RentalHistory)
        .filter(
            RentalHistory.id == history_uuid,
            RentalHistory.user_id == current_user.id
        )
        .first()
    )
    if not rental:
        raise HTTPException(status_code=404, detail="Rental history not found")

    car = db.query(Car).get(rental.car_id)

    # Вычисляем сумму без топлива для отображения
    total_price_without_fuel = (
        (rental.base_price or 0)
        + rental.open_fee
        + rental.delivery_fee
        + rental.waiting_fee
        + rental.overtime_fee
        + rental.distance_fee
    )

    rental_detail = {
        "history_id": uuid_to_sid(rental.id),
        "user_id": uuid_to_sid(rental.user_id),
        "car_id": uuid_to_sid(rental.car_id),
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
        "total_price_without_fuel": total_price_without_fuel,
        "rental_status": rental.rental_status.value,
        "base_price": rental.base_price,
        "open_fee": rental.open_fee,
        "delivery_fee": rental.delivery_fee,
        # Топливо: суммы и уровни
        "fuel_fee": (lambda: (
            int((ceil(rental.fuel_before) - floor(rental.fuel_after)) * (ELECTRIC_FUEL_PRICE_PER_LITER if car.body_type == "ELECTRIC" else FUEL_PRICE_PER_LITER))
            if rental.fuel_before is not None and rental.fuel_after is not None and
               rental.fuel_after < rental.fuel_before and
               (ceil(rental.fuel_before) - floor(rental.fuel_after)) > 0 and
               (car.owner_id == rental.user_id or rental.rental_type in (RentalType.HOURS, RentalType.DAYS)) else 0
        ))(),
        "fuel_before": rental.fuel_before,
        "fuel_after": rental.fuel_after,
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
            "vin": car.vin,
            "color": car.color,
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
            
            route_data = await get_gps_route_data(
                device_id=car.gps_id,
                start_date=apply_offset(rental.start_time),
                end_date=apply_offset(rental.end_time)
            )
            
            if route_data:
                pass
        except Exception as e:
            route_data = None
    else:
        pass

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
              tracking_id: Optional[str] = None,
              db: Session = Depends(get_db),
              current_user: User = Depends(get_current_user)):
    # Проверяем, не была ли уже обработана транзакция с таким tracking_id
    if tracking_id:
        existing_transaction = db.query(WalletTransaction).filter(
            WalletTransaction.tracking_id == tracking_id,
            WalletTransaction.user_id == current_user.id
        ).first()
        
        if existing_transaction:
            return {
                "wallet_balance": float(current_user.wallet_balance),
                "bonus": 0,
                "promo_applied": False,
                "message": "Транзакция уже была обработана"
            }
    
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

        # фиксируем баланс до депозита, чтобы корректно отразить 2 транзакции подряд
        before = float(current_user.wallet_balance or 0)
        # депозит
        record_wallet_transaction(db, user=current_user, amount=amount, ttype=WalletTransactionType.DEPOSIT, description="Пополнение кошелька", balance_before_override=before, tracking_id=tracking_id)
        # бонус
        record_wallet_transaction(db, user=current_user, amount=bonus, ttype=WalletTransactionType.PROMO_BONUS, description=f"Бонус по промокоду {up.promo.code if up and up.promo else ''}", balance_before_override=before + amount)
        # начисляем основную сумму + бонус
        current_user.wallet_balance += amount + bonus

        # меняем статус промокода
        up.status = UserPromoStatus.USED
        up.used_at = datetime.utcnow()

    else:
        # обычное пополнение
        record_wallet_transaction(db, user=current_user, amount=amount, ttype=WalletTransactionType.DEPOSIT, description="Пополнение кошелька", tracking_id=tracking_id)
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
        car_id: str,
        rental_type: RentalType,
        duration: Optional[int] = None,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    car_uuid = safe_sid_to_uuid(car_id)
    car_meta = db.query(Car.id, Car.owner_id, Car.status).filter(Car.id == car_uuid).first()
    if not car_meta:
        raise HTTPException(status_code=404, detail="Car not found")

    # Запреты по ролям/верификации для НЕ владельцев
    if car_meta.owner_id != current_user.id:
        validate_user_can_rent(current_user, db)
        
        # Проверяем подписание договора о присоединении (MAIN_CONTRACT)
        main_contract_signed = db.query(UserContractSignature).join(ContractFile).filter(
            UserContractSignature.user_id == current_user.id,
            ContractFile.contract_type == ContractType.MAIN_CONTRACT
        ).first() is not None
        
        if not main_contract_signed:
            raise HTTPException(
                status_code=403,
                detail="Необходимо подписать договор о присоединении перед бронированием автомобиля"
            )

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
        Car.id == car_uuid,
        Car.status == CarStatus.FREE
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
        car.status = CarStatus.OWNER  # Машина у владельца
        
        # Обновляем время последней активности пользователя
        current_user.last_activity_at = datetime.utcnow()
        
        db.commit()

        return {
            "message": "Car reserved successfully (owner rental)",
            "rental_id": uuid_to_sid(rental.id),
            "reservation_time": rental.reservation_time.isoformat()
        }

    # НЕ владельцу – проверка баланса
    required_balance = calc_required_balance(
        rental_type=rental_type,
        duration=duration,
        car=car,
        include_delivery=False,
        is_owner=False
    )
    
    if current_user.wallet_balance < required_balance:
        raise InsufficientBalanceException(required_amount=required_balance)

    if rental_type == RentalType.MINUTES:
        base = 0
    elif rental_type == RentalType.HOURS:
        if duration is None:
            raise HTTPException(status_code=400, detail="Duration обязателен для аренды по часам.")
        base = calculate_total_price(rental_type, duration, price_per_hour, price_per_day)
    else:  # RentalType.DAYS
        if duration is None:
            raise HTTPException(status_code=400, detail="Duration обязателен для посуточной аренды.")
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
    car.status = CarStatus.RESERVED
    
    # Обновляем время последней активности пользователя
    current_user.last_activity_at = datetime.utcnow()
    
    db.commit()

    return {
        "message": "Car reserved successfully",
        "rental_id": uuid_to_sid(rental.id),
        "reservation_time": rental.reservation_time.isoformat()
    }


@RentRouter.post("/reserve-delivery/{car_id}")
async def reserve_delivery(
        car_id: str,
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
    car_uuid = safe_sid_to_uuid(car_id)
    # Запреты по ролям/верификации
    validate_user_can_rent(current_user, db)
    
    # Получаем информацию о машине для проверки владельца
    car_check = db.query(Car).filter(Car.id == car_uuid).first()
    if car_check and car_check.owner_id != current_user.id:
        # Проверяем подписание договора о присоединении (MAIN_CONTRACT) для не-владельцев
        main_contract_signed = db.query(UserContractSignature).join(ContractFile).filter(
            UserContractSignature.user_id == current_user.id,
            ContractFile.contract_type == ContractType.MAIN_CONTRACT
        ).first() is not None
        
        if not main_contract_signed:
            raise HTTPException(
                status_code=403,
                detail="Необходимо подписать договор о присоединении перед бронированием автомобиля с доставкой"
            )

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
        Car.id == car_uuid,
        Car.status == CarStatus.FREE
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
        # Проверим баланс сейчас, само списание сделаем после создания rental (чтобы связать транзакцию)
        if current_user.wallet_balance < delivery_fee:
            raise InsufficientBalanceException(required_amount=delivery_fee)
    else:
        # НЕ владелец — сбор за доставку
        delivery_fee = extra_fee

        # Проверка минимального баланса
        required_balance = calc_required_balance(
            rental_type=rental_type,
            duration=duration,
            car=car,
            include_delivery=True,
            is_owner=False
        )
        
        if current_user.wallet_balance < required_balance:
            raise InsufficientBalanceException(required_amount=required_balance)

        if rental_type == RentalType.MINUTES:
            base_price = 0
            total_price = delivery_fee  # пока в total_price только плата за доставку

        elif rental_type == RentalType.HOURS:
            if duration is None:
                raise HTTPException(status_code=400, detail="Duration обязателен для аренды по часам.")
            base_price = calculate_total_price(rental_type, duration, price_per_hour, price_per_day)
            total_price = base_price + open_fee + delivery_fee

        else:  # RentalType.DAYS
            if duration is None:
                raise HTTPException(status_code=400, detail="Duration обязателен для посуточной аренды.")
            base_price = calculate_total_price(rental_type, duration, price_per_hour, price_per_day)
            total_price = base_price + delivery_fee

        # Если не владелец — проверим баланс сейчас, само списание сделаем после создания rental
        # (чтобы связать транзакцию с related_rental)
        pass

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

    # Теперь фиксируем списание доставки и связываем транзакцию с арендой
    if delivery_fee and delivery_fee > 0:
        record_wallet_transaction(
            db,
            user=current_user,
            amount=-delivery_fee,
            ttype=WalletTransactionType.DELIVERY_FEE,
            description="Оплата доставки",
            related_rental=rental,
        )
        current_user.wallet_balance -= delivery_fee
        db.commit()

    # Обновляем статус машины
    car.current_renter_id = current_user.id
    car.status = CarStatus.DELIVERING
    
    # Обновляем время последней активности пользователя
    current_user.last_activity_at = datetime.utcnow()
    
    db.commit()

    # Уведомляем всех механиков
    await send_localized_notification_to_all_mechanics(
        db, 
        "delivery_new_order", 
        "delivery_new_order",
        car_name=car.name,
        plate_number=car.plate_number
    )

    return {
        "message": "Заказ доставки оформлен успешно",
        "rental_id": uuid_to_sid(rental.id),
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
        
        # Рассчитываем продолжительность поездки в минутах
        if rental.start_time:
            duration_seconds = (now - rental.start_time).total_seconds()
            rental.duration = int(duration_seconds / 60)
        
        car.current_renter_id = None
        car.status = CarStatus.FREE
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

            # комиссия за ожидание при отмене
            record_wallet_transaction(db, user=current_user, amount=-fee, ttype=WalletTransactionType.RENT_WAITING_FEE, description="Комиссия за ожидание при отмене")
            current_user.wallet_balance -= fee

        # Завершаем аренду
        rental.rental_status = RentalStatus.COMPLETED
        rental.end_time = now
        rental.total_price = fee
        rental.already_payed = fee
        
        # Рассчитываем продолжительность поездки в минутах
        if rental.start_time:
            duration_seconds = (now - rental.start_time).total_seconds()
            rental.duration = int(duration_seconds / 60)

        # Освобождаем машину и возвращаем статус "FREE"
        car.current_renter_id = None
        car.status = CarStatus.FREE

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
    
    # Рассчитываем продолжительность поездки в минутах
    if rental.start_time:
        duration_seconds = (datetime.utcnow() - rental.start_time).total_seconds()
        rental.duration = int(duration_seconds / 60)
    
    rental.delivery_mechanic_id = None

    # Освобождаем машину
    car.current_renter_id = None
    car.status = CarStatus.FREE

    db.commit()
    db.refresh(rental)

    # Уведомляем механика, если был назначен
    if mech_id:
        await send_localized_notification_to_user(
            db, 
            mech_id, 
            "delivery_cancelled", 
            "delivery_cancelled",
            car_name=car.name,
            plate_number=car.plate_number,
            rental_id=rental.id
        )

    return {"message": "Доставка отменена успешно"}


@RentRouter.post("/start/{car_id}")
async def start_rental(
        car_id: str,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    car_uuid = safe_sid_to_uuid(car_id)
    # Запреты по ролям/верификации (на случай, если обошли резервацию)
    validate_user_can_rent(current_user, db)

    # Получаем активную аренду пользователя по ID авто со статусом RESERVED
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.car_id == car_uuid,
        RentalHistory.rental_status == RentalStatus.RESERVED
    ).first()

    if not rental:
        raise HTTPException(status_code=404, detail="No active rental found")

    if rental.rental_status != RentalStatus.RESERVED:
        raise HTTPException(status_code=400, detail="Rental is not in reserved status")
    
    # Проверяем, что основной договор аренды подписан
    from app.models.contract_model import UserContractSignature, ContractFile, ContractType
    
    rental_main_contract_signed = db.query(UserContractSignature).join(ContractFile).filter(
        UserContractSignature.user_id == current_user.id,
        UserContractSignature.rental_id == rental.id,
        ContractFile.contract_type == ContractType.RENTAL_MAIN_CONTRACT
    ).first() is not None
    
    if not rental_main_contract_signed:
        raise HTTPException(
            status_code=400, 
            detail="Необходимо подписать основной договор аренды перед началом аренды"
        )

    # Получаем машину по аренде
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    # Проверяем, является ли пользователь владельцем автомобиля
    is_owner = car.owner_id == current_user.id

    # Проверяем подписание обязательных договоров (только для не-владельцев)
    if not is_owner:
        # 1. Проверяем договор о присоединении (MAIN_CONTRACT)
        main_contract_signed = db.query(UserContractSignature).join(ContractFile).filter(
            UserContractSignature.user_id == current_user.id,
            ContractFile.contract_type == ContractType.MAIN_CONTRACT
        ).first() is not None
        
        if not main_contract_signed:
            raise HTTPException(
                status_code=403,
                detail="Необходимо подписать договор о присоединении перед началом аренды"
            )
        
        # 2. Проверяем акт приема (APPENDIX_7_1) для текущей аренды
        appendix_7_1_signed = db.query(UserContractSignature).join(ContractFile).filter(
            UserContractSignature.user_id == current_user.id,
            UserContractSignature.rental_id == rental.id,
            ContractFile.contract_type == ContractType.APPENDIX_7_1
        ).first() is not None
        
        if not appendix_7_1_signed:
            raise HTTPException(
                status_code=403,
                detail="Необходимо подписать акт приема автомобиля перед началом аренды"
            )
    
    existing_before = rental.photos_before or []
    has_selfie_before = any(("/before/selfie/" in p) or ("\\before\\selfie\\" in p) for p in existing_before)
    has_exterior_before = any(("/before/car/" in p) or ("\\before\\car\\" in p) for p in existing_before)
    has_interior_before = any(("/before/interior/" in p) or ("\\before\\interior\\" in p) for p in existing_before)
    
    # Для владельца автомобиля пропускаем проверку селфи
    if is_owner:
        # Владелец должен загрузить только внешний вид и салон
        if not (has_exterior_before and has_interior_before):
            missing = []
            if not has_exterior_before:
                missing.append("внешний вид")
            if not has_interior_before:
                missing.append("салон")
            raise HTTPException(
                status_code=400,
                detail=f"Перед стартом аренды загрузите фото: {', '.join(missing)}"
            )
    else:
        # Для обычных пользователей требуем все фото: селфи, внешний вид, салон
        if not (has_selfie_before and has_exterior_before and has_interior_before):
            missing = []
            if not has_selfie_before:
                missing.append("селфи")
            if not has_exterior_before:
                missing.append("внешний вид")
            if not has_interior_before:
                missing.append("салон")
            raise HTTPException(
                status_code=400,
                detail=f"Перед стартом аренды загрузите фото: {', '.join(missing)}"
            )

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
        
        # Автоматическая разблокировка двигателя при начале аренды (для владельца)
        try:
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            
            # Универсальная последовательность: разблокировать двигатель
            result = await execute_gps_sequence(car.gps_imei, auth_token, "start")
            if result["success"]:
                print(f"Двигатель автомобиля {car.name} разблокирован при начале аренды (владелец)")
            else:
                print(f"Ошибка GPS последовательности для владельца: {result.get('error', 'Unknown error')}")
        except Exception as e:
            print(f"Ошибка разблокировки двигателя при начале аренды (владелец): {e}")
        
        is_owner_rental = True
    else:
        # Если аренда минутная или часовая, списываем с баланса open_price, вычисленный через get_open_price
        if rental.rental_type in [RentalType.MINUTES, RentalType.HOURS]:
            open_price = get_open_price(car)
            rental.open_fee = open_price

        rental.rental_status = RentalStatus.IN_USE
        rental.start_time = datetime.utcnow()
        
        # Обновляем время последней активности пользователя
        current_user.last_activity_at = datetime.utcnow()

        # Для суточного и часового тарифа списываем полную стоимость сразу
        # Для минутного тарифа списываем только open_fee (поминутный тариф списывается во время поездки)
        if rental.rental_type in [RentalType.HOURS, RentalType.DAYS]:
            # Списываем полную стоимость за выбранный период (base_price + open_fee + delivery_fee)
            total_cost = (rental.base_price or 0) + (rental.open_fee or 0) + (rental.delivery_fee or 0)

        if total_cost > 0:
            if current_user.wallet_balance < total_cost:
                raise HTTPException(
                    status_code=402,
                    detail=f"Нужно минимум {total_cost} ₸ для старта. Пополните кошелёк!"
                )
                record_wallet_transaction(db, user=current_user, amount=-total_cost, ttype=WalletTransactionType.RENT_BASE_CHARGE, description=f"Оплата за аренду: {rental.duration} {'час(ов)' if rental.rental_type == RentalType.HOURS else 'день(дней)'}")
                current_user.wallet_balance -= total_cost
                rental.already_payed = total_cost
        elif rental.rental_type == RentalType.MINUTES:
            # Для минутного тарифа списываем только open_fee
            open_fee = rental.open_fee or 0
            delivery_fee = rental.delivery_fee or 0
            total_cost = open_fee + delivery_fee
            
            if total_cost > 0:
                if current_user.wallet_balance < total_cost:
                    raise HTTPException(
                        status_code=402,
                        detail=f"Нужно минимум {total_cost} ₸ для старта. Пополните кошелёк!"
                    )
                record_wallet_transaction(db, user=current_user, amount=-total_cost, ttype=WalletTransactionType.RENT_BASE_CHARGE, description="Оплата открытия и доставки")
            current_user.wallet_balance -= total_cost
            rental.already_payed = total_cost

        # Обновляем машину: меняем статус на IN_USE
        car.status = CarStatus.IN_USE

        db.commit()

        # Автоматическая разблокировка двигателя при начале аренды (универсально для всех автомобилей)
        try:
            car = db.query(Car).get(rental.car_id)
            if car and car.gps_imei:
                auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
                # Универсальная последовательность: разблокировать двигатель → выдать ключ
                result = await execute_gps_sequence(car.gps_imei, auth_token, "interior")
                if not result["success"]:
                    print(f"Ошибка GPS последовательности при старте: {result.get('error', 'Unknown error')}")
        except Exception as e:
            print(f"Ошибка GPS команд при старте аренды: {e}")

        is_owner_rental = False

    # try:
    #     name_parts = []
    #     if current_user.first_name:
    #         name_parts.append(current_user.first_name)
    #     if current_user.middle_name:
    #         name_parts.append(current_user.middle_name)
    #     if current_user.last_name:
    #         name_parts.append(current_user.last_name)
    #     full_name = " ".join(name_parts) if name_parts else "Не указано"
    #     
    #     login = current_user.phone_number or "Не указан"
    #     
    #     await send_rental_start_sms(
    #         client_phone=current_user.phone_number,
    #         rent_id=str(rental.id),
    #         full_name=full_name,
    #         login=login,
    #         client_id=str(current_user.id),
    #         digital_signature=current_user.digital_signature or "Не указана",
    #         car_id=str(car.id),
    #         plate_number=car.plate_number,
    #         car_name=car.name
    #     )
    #     print(f"SMS отправлена клиенту {current_user.phone_number} при начале аренды")
    # except Exception as e:
    #     print(f"Ошибка отправки SMS при начале аренды: {e}")

    if is_owner_rental:
        return {"message": "Rental started successfully (owner rental)", "rental_id": uuid_to_sid(rental.id)}
    else:
        return {"message": "Rental started successfully", "rental_id": uuid_to_sid(rental.id)}


@RentRouter.post("/upload-photos-before")
async def upload_photos_before(
        selfie: UploadFile = File(...),
        car_photos: list[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    До начала аренды (часть 1):
    - selfie: фото пользователя с машиной
    - car_photos: внешние фото машины (1-10)

    Interior загружается отдельным запросом /upload-photos-before-interior
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="No active rental found")

    validate_photos([selfie], 'selfie')
    validate_photos(car_photos, 'car_photos')

    uploaded_files = []
    
    try:
        # 1) Сверяем селфи клиента с документом из профиля
        try:
            is_same, msg = await run_in_threadpool(verify_user_upload_against_profile, current_user, selfie)
            if not is_same:
                raise HTTPException(status_code=400, detail=msg)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail="Ой! Похоже на фотографии не вы, но если это вы, то пожалуйста сделайте селфи как в профиле.")

        # 2) Если верификация успешна — сохраняем фото
        urls = list(rental.photos_before or [])
        # save selfie
        selfie_url = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/before/selfie/")
        urls.append(selfie_url)
        uploaded_files.append(selfie_url)
        # save exterior
        for p in car_photos:
            car_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/before/car/")
            urls.append(car_url)
            uploaded_files.append(car_url)

        rental.photos_before = urls
        
        car = db.query(Car).get(rental.car_id)
        if car and car.gps_imei:
            
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            
            # Универсальная последовательность: открыть замки → выдать ключ → открыть замки → забрать ключ
            result = await execute_gps_sequence(car.gps_imei, auth_token, "selfie_exterior")
            if not result["success"]:
                error_msg = result.get('error', 'Unknown error')
                print(f"Ошибка GPS последовательности для селфи+кузов: {error_msg}")
                raise Exception(f"GPS sequence failed: {error_msg}")
            else:
                print(f"GPS последовательность выполнена успешно: {result.get('executed_commands', [])}")
        
        db.commit()
        
        return {"message": "Photos before (selfie+car) uploaded", "photo_count": len(urls)}
    except HTTPException:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files) 
        raise HTTPException(status_code=500, detail=f"Error uploading before photos: {str(e)}")


@RentRouter.post("/upload-photos-before-interior")
async def upload_photos_before_interior(
        interior_photos: list[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    До начала аренды (часть 2):
    - interior_photos: фото салона (1-10)
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="No active rental found")

    # Требуем, чтобы перед салоном были загружены внешние фото
    existing = rental.photos_before or []
    has_exterior = any(('/before/car/' in p) or ('\\before\\car\\' in p) for p in existing)
    if not has_exterior:
        raise HTTPException(status_code=400, detail="Сначала загрузите внешние фото")

    validate_photos(interior_photos, 'interior_photos')

    uploaded_files = []
    
    try:
        urls = list(rental.photos_before or [])
        for p in interior_photos:
            interior_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/before/interior/")
            urls.append(interior_url)
            uploaded_files.append(interior_url)
        rental.photos_before = urls
        db.commit()
        return {"message": "Photos before (interior) uploaded", "photo_count": len(interior_photos)}
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise HTTPException(status_code=500, detail=f"Error uploading before interior photos: {str(e)}")


@RentRouter.post("/upload-photos-after")
async def upload_photos_after(
        selfie: UploadFile = File(...),
        interior_photos: list[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    После завершения аренды (часть 1):
    - selfie: фото пользователя
    - interior_photos: фото салона (1-10)
    
    После успешной загрузки:
    - Проверяется статус авто (заглушен ли двигатель, закрыты ли окна/двери и т.д.)
    - Блокируются замки
    - Блокируется двигатель
    - Забирается ключ
    
    Внешние фото отправляются отдельным запросом /upload-photos-after-car
    После загрузки внешних фото аренда автоматически завершается
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="No active rental in IN_USE status found")

    validate_photos([selfie], 'selfie')
    validate_photos(interior_photos, 'interior_photos')
    
    # Проверяем селфи на идентичность с документом
    try:
        is_same, msg = await run_in_threadpool(verify_user_upload_against_profile, current_user, selfie)
        if not is_same:
            raise HTTPException(status_code=400, detail=msg)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail="Ой! Похоже на фотографии не вы, но если это вы, то пожалуйста сделайте селфи как в профиле.")
    
    # Получаем автомобиль
    car = db.query(Car).get(rental.car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    # Проверяем состояние автомобиля перед блокировкой
    vehicle_status = await check_vehicle_status_for_completion(car.gps_imei)
    
    if "error" in vehicle_status:
        raise HTTPException(status_code=400, detail=vehicle_status["error"])
    
    if vehicle_status.get("errors"):
        error_message = "Перед завершением аренды:\n" + "\n".join(vehicle_status["errors"])
        raise HTTPException(status_code=400, detail=error_message)
    
    # Доп. проверка для MERCEDES: зажигание должно быть выключено
    try:
        if car and car.plate_number == '666AZV02':
            vehicle = vehicle_status.get("vehicle") or {}
            if vehicle.get("is_ignition_on", False):
                raise HTTPException(status_code=400, detail="Для завершения аренды пожалуйста выключите зажигание")
    except HTTPException:
        raise
    except Exception:
        pass

    uploaded_files = []
    
    try:
        # Сохраняем фотографии
        urls = list(rental.photos_after or [])
        selfie_url = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/after/selfie/")
        urls.append(selfie_url)
        uploaded_files.append(selfie_url)
        
        for p in interior_photos:
            interior_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/after/interior/")
            urls.append(interior_url)
            uploaded_files.append(interior_url)

        rental.photos_after = urls
        
        # После загрузки селфи+салона: заблокировать двигатель → забрать ключ → закрыть замки
        car = db.query(Car).get(rental.car_id)
        if car and car.gps_imei:
            
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            # Универсальная последовательность: заблокировать двигатель → забрать ключ → закрыть замки
            result = await execute_gps_sequence(car.gps_imei, auth_token, "complete_selfie_interior")
            if not result["success"]:
                error_msg = result.get('error', 'Unknown error')
                print(f"Ошибка GPS последовательности для завершения селфи+салон: {error_msg}")
                raise Exception(f"GPS sequence failed: {error_msg}")
        
        db.commit()
        
        return {"message": "Photos after (selfie+interior) uploaded", "photo_count": len(interior_photos) + 1}
    except HTTPException:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise HTTPException(status_code=500, detail=f"Error uploading after photos: {str(e)}")


@RentRouter.post("/upload-photos-after-car")
async def upload_photos_after_car(
        car_photos: list[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    После завершения аренды (часть 2):
    - car_photos: внешние фото (1-10)
    
    После успешной загрузки:
    - Аренда автоматически завершается
    - Статус аренды меняется на COMPLETED
    - Машина освобождается (статус PENDING)
    - Деньги перестают списываться
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="No active rental in IN_USE status found")

    # Получаем машину для проверки владельца
    car = db.query(Car).get(rental.car_id)
    is_owner = car.owner_id == current_user.id if car else False
    
    # Требуем, чтобы перед внешними фото были загружены салонные (after)
    existing_after = rental.photos_after or []
    has_interior_after = any(('/after/interior/' in p) or ('\\after\\interior\\' in p) for p in existing_after)
    
    # Для владельца автомобиля проверяем наличие фото салона (без селфи)
    # Для обычных пользователей проверяем наличие селфи + салона
    if is_owner:
        # Владелец должен загрузить только салон (через /upload-photos-after-owner)
        if not has_interior_after:
            raise HTTPException(status_code=400, detail="Сначала загрузите фото салона")
    else:
        # Обычный пользователь должен загрузить селфи + салон (через /upload-photos-after)
        has_selfie_after = any(('/after/selfie/' in p) or ('\\after\\selfie\\' in p) for p in existing_after)
        if not (has_selfie_after and has_interior_after):
            missing = []
            if not has_selfie_after:
                missing.append("селфи")
            if not has_interior_after:
                missing.append("салон")
            raise HTTPException(
                status_code=400, 
                detail=f"Сначала загрузите фото: {', '.join(missing)}"
            )

    # Проверяем закрытие дверей перед внешней съёмкой
    try:
        vehicle_status = await check_vehicle_status_for_completion(car.gps_imei)
        if vehicle_status.get("errors"):
            doors_errors = [e for e in vehicle_status["errors"] if "двер" in e.lower() or "door" in e.lower()]
            if doors_errors:
                raise HTTPException(status_code=400, detail="Перед внешними фото закройте двери")
    except Exception:
        # Если мониторинг недоступен — не блокируем, чтобы не ломать флоу
        pass

    validate_photos(car_photos, 'car_photos')

    uploaded_files = []
    
    try:
        urls = list(rental.photos_after or [])
        for p in car_photos:
            car_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/after/car/")
            urls.append(car_url)
            uploaded_files.append(car_url)
        
        rental.photos_after = urls
        
        # После загрузки кузова: заблокировать двигатель → забрать ключ → закрыть замки
        if car and car.gps_imei:
            
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            # Универсальная последовательность: заблокировать двигатель → забрать ключ → закрыть замки
            result = await execute_gps_sequence(car.gps_imei, auth_token, "complete_exterior")
            if not result["success"]:
                error_msg = result.get('error', 'Unknown error')
                print(f"Ошибка GPS последовательности для завершения кузова: {error_msg}")
                raise Exception(f"GPS sequence failed: {error_msg}")
        
        db.commit()
        
        return {
            "message": "Photos after (car) uploaded successfully", 
            "photo_count": len(car_photos),
            "rental_completed": False
        }
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise HTTPException(status_code=500, detail=f"Error uploading after car photos: {str(e)}")


# Owner endpoints (без селфи)
@RentRouter.post("/upload-photos-before-owner")
async def upload_photos_before_owner(
        car_photos: list[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """До аренды для владельца (часть 1): только внешние фото (1-10)."""
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="No active rental found")
    car = db.query(Car).get(rental.car_id)
    if car.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your car")
    validate_photos(car_photos, 'car_photos')

    uploaded_files = []
    
    try:
        urls = list(rental.photos_before or [])
        for p in car_photos:
            car_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/before/car/")
            urls.append(car_url)
            uploaded_files.append(car_url)

        rental.photos_before = urls
        
        # Открываем замки после успешной загрузки фото
        if car and car.gps_imei:
            
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            open_result = await send_open(car.gps_imei, auth_token)
            if not open_result.get("success"):
                error_msg = open_result.get('error', 'Unknown error')
                print(f"Ошибка открытия замков после загрузки фото владельцем: {error_msg}")
                raise Exception(f"GPS open command failed: {error_msg}")
        
        db.commit()
        
        return {"message": "Owner photos before (car) uploaded", "photo_count": len(car_photos)}
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise HTTPException(status_code=500, detail=f"Error uploading owner photos before: {str(e)}")


@RentRouter.post("/upload-photos-before-owner-interior")
async def upload_photos_before_owner_interior(
        interior_photos: list[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """До аренды для владельца (часть 2): только салон (1-10)."""
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="No active rental found")
    car = db.query(Car).get(rental.car_id)
    if car.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your car")
    # Требуем сначала внешние фото
    existing = rental.photos_before or []
    has_exterior = any(('/before/car/' in p) or ('\\before\\car\\' in p) for p in existing)
    if not has_exterior:
        raise HTTPException(status_code=400, detail="Сначала загрузите внешние фото")
    validate_photos(interior_photos, 'interior_photos')

    uploaded_files = []
    
    try:
        urls = list(rental.photos_before or [])
        for p in interior_photos:
            interior_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/before/interior/")
            urls.append(interior_url)
            uploaded_files.append(interior_url)

        rental.photos_before = urls
        db.commit()
        return {"message": "Owner photos before (interior) uploaded", "photo_count": len(interior_photos)}
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise HTTPException(status_code=500, detail=f"Error uploading owner photos before (interior): {str(e)}")


@RentRouter.post("/upload-photos-after-owner")
async def upload_photos_after_owner(
        interior_photos: list[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    После аренды для владельца (часть 1): только салон (1-10).
    
    После успешной загрузки:
    - Проверяется статус авто (заглушен ли двигатель, закрыты ли окна/двери и т.д.)
    - Блокируются замки
    - Блокируется двигатель  
    - Забирается ключ
    """
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="No active rental in IN_USE status found")
    car = db.query(Car).get(rental.car_id)
    if car.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your car")
    
    validate_photos(interior_photos, 'interior_photos')
    
    # Проверяем состояние автомобиля перед блокировкой
    vehicle_status = await check_vehicle_status_for_completion(car.gps_imei)
    
    if "error" in vehicle_status:
        raise HTTPException(status_code=400, detail=vehicle_status["error"])
    
    if vehicle_status.get("errors"):
        error_message = "Перед завершением аренды:\n" + "\n".join(vehicle_status["errors"])
        raise HTTPException(status_code=400, detail=error_message)

    uploaded_files = []
    
    try:
        # Сохраняем фотографии
        urls = list(rental.photos_after or [])
        for p in interior_photos:
            interior_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/after/interior/")
            urls.append(interior_url)
            uploaded_files.append(interior_url)
        
        rental.photos_after = urls
        
        # После загрузки салона владельцем: заблокировать двигатель → забрать ключ → закрыть замки
        car = db.query(Car).get(rental.car_id)
        if car and car.gps_imei:
            
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            # Универсальная последовательность: заблокировать двигатель → забрать ключ → закрыть замки
            result = await execute_gps_sequence(car.gps_imei, auth_token, "complete_selfie_interior")
            if not result["success"]:
                error_msg = result.get('error', 'Unknown error')
                print(f"Ошибка GPS последовательности для завершения салона владельцем: {error_msg}")
                raise Exception(f"GPS sequence failed: {error_msg}")
        
        db.commit()
        
        return {"message": "Owner photos after (interior) uploaded", "photo_count": len(interior_photos)}
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise HTTPException(status_code=500, detail=f"Error uploading owner photos after (interior): {str(e)}")


@RentRouter.post("/upload-photos-after-owner-car")
async def upload_photos_after_owner_car(
        car_photos: list[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """После аренды для владельца (часть 2): только внешние фото (1-10)."""
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()
    if not rental:
        raise HTTPException(status_code=404, detail="No active rental in IN_USE status found")
    car = db.query(Car).get(rental.car_id)
    if car.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your car")
    # Требуем сначала салонные фото
    existing_after = rental.photos_after or []
    has_interior_after = any(('/after/interior/' in p) or ('\\after\\interior\\' in p) for p in existing_after)
    if not has_interior_after:
        raise HTTPException(status_code=400, detail="Сначала загрузите фото салона")
    validate_photos(car_photos, 'car_photos')

    uploaded_files = []
    
    try:
        urls = list(rental.photos_after or [])
        for p in car_photos:
            car_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/after/car/")
            urls.append(car_url)
            uploaded_files.append(car_url)
        
        rental.photos_after = urls
        db.commit()
        return {"message": "Owner photos after (car) uploaded", "photo_count": len(car_photos)}
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise HTTPException(status_code=500, detail=f"Error uploading owner photos after (car): {str(e)}")


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
            response = await client.get(f"http://195.93.152.69:8667/vehicles/?skip=0&limit=100")
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
        # Проверяем, не завершена ли аренда автоматически
        completed_rental = db.query(RentalHistory).filter(
            RentalHistory.user_id == current_user.id,
            RentalHistory.rental_status == RentalStatus.COMPLETED
        ).order_by(RentalHistory.end_time.desc()).first()
        
        if completed_rental:
            raise HTTPException(
                status_code=400, 
                detail="Аренда уже завершена автоматически после загрузки фото кузова"
            )
        else:
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

    # Проверяем, является ли пользователь владельцем автомобиля
    is_owner = car.owner_id == current_user.id
    
    after_photos = rental.photos_after or []
    has_after_selfie = any(("/after/selfie/" in p) or ("\\after\\selfie\\" in p) for p in after_photos)
    has_after_interior = any(("/after/interior/" in p) or ("\\after\\interior\\" in p) for p in after_photos)
    has_after_exterior = any(("/after/car/" in p) or ("\\after\\car\\" in p) for p in after_photos)
    
    # Для владельца автомобиля пропускаем проверку селфи
    if is_owner:
        # Владелец должен загрузить только салон и внешний вид
        if not (has_after_interior and has_after_exterior):
            missing_after = []
            if not has_after_interior:
                missing_after.append("салон")
            if not has_after_exterior:
                missing_after.append("внешний вид")
            raise HTTPException(
                status_code=400,
                detail=f"Для завершения аренды загрузите фото: {', '.join(missing_after)}"
            )
    else:
        # Для обычных пользователей требуем все фото: селфи, салон, внешний вид
        if not (has_after_selfie and has_after_interior and has_after_exterior):
            missing_after = []
            if not has_after_selfie:
                missing_after.append("селфи")
            if not has_after_interior:
                missing_after.append("салон")
            if not has_after_exterior:
                missing_after.append("внешний вид")
            raise HTTPException(
                status_code=400,
                detail=f"Для завершения аренды загрузите фото: {', '.join(missing_after)}"
            )

    # 4) Завершить аренду: время, координаты, состояние
    now = datetime.utcnow()
    rental.end_time = now
    rental.end_latitude = car.latitude
    rental.end_longitude = car.longitude
    rental.fuel_after = car.fuel_level
    rental.mileage_after = car.mileage
    rental.rental_status = RentalStatus.COMPLETED
    
    # Обновляем время последней активности пользователя
    current_user.last_activity_at = now

    # Освободить машину
    car.current_renter_id = None
    car.status = CarStatus.PENDING

    # 5) Сохранить отзыв (если есть)
    if review_input:
        # Ищем существующий отзыв для этой аренды
        existing_review = db.query(RentalReview).filter(RentalReview.rental_id == rental.id).first()
        
        if existing_review:
            # Обновляем существующий отзыв, добавляя данные клиента
            existing_review.rating = review_input.rating
            existing_review.comment = review_input.comment
        else:
            # Создаем новый отзыв только с данными клиента
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

    # 10) Рассчитать топливный сбор (включать только при необходимости)
    fuel_fee = 0
    fuel_consumed = 0
    if rental.fuel_before is not None and rental.fuel_after is not None:
        # Проверяем, что топливо реально уменьшилось
        if rental.fuel_after < rental.fuel_before:
            # Округляем в пользу платформы: fuel_before вверх, fuel_after вниз
            fuel_before_rounded = ceil(rental.fuel_before)
            fuel_after_rounded = floor(rental.fuel_after)
            fuel_consumed = fuel_before_rounded - fuel_after_rounded
            if fuel_consumed > 0:
                # Определяем цену за литр в зависимости от типа автомобиля
                if car.body_type == "ELECTRIC":
                    price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
                else:
                    price_per_liter = FUEL_PRICE_PER_LITER
                fuel_fee = int(fuel_consumed * price_per_liter)

    if car.owner_id == current_user.id:
        # Владелец платит только за топливо
        rental.base_price = 0
        rental.open_fee = 0
        rental.waiting_fee = 0
        rental.overtime_fee = 0
        rental.distance_fee = 0

        # Рассчитываем итоговую сумму (топливо уже списано во время поездки)
        rental.total_price = fuel_fee
        # Обновляем already_payed (все списания уже произошли во время поездки)
        rental.already_payed = rental.already_payed or 0
    else:
        # Итоговая сумма БЕЗ топлива (для отдельного отображения)
        total_price_without_fuel = (
            (rental.base_price or 0)
            + rental.open_fee
            + rental.delivery_fee
            + rental.waiting_fee
            + rental.overtime_fee
            + rental.distance_fee
        )
        # Итоговая сумма ВКЛЮЧАЯ топливо
        rental.total_price = total_price_without_fuel + fuel_fee
        
        # Все списания уже произошли во время поездки
        # Обновляем already_payed (все списания уже произошли во время поездки)
        rental.already_payed = rental.already_payed or 0

    # 12) Рассчитываем и сохраняем фактическую продолжительность поездки в минутах для истории
    rental.duration = rounded_minutes
    
    # 13) Окончательная блокировка двигателя при завершении аренды
    try:
        auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        
        # Универсальная последовательность: заблокировать двигатель
        result = await execute_gps_sequence(car.gps_imei, auth_token, "final_lock")
        if result["success"]:
            print(f"Двигатель автомобиля {car.name} окончательно заблокирован после завершения аренды")
        else:
            print(f"Ошибка GPS последовательности при окончательной блокировке: {result.get('error', 'Unknown error')}")
    except Exception as e:
        print(f"Ошибка блокировки двигателя: {e}")

    # 14) Коммит и уведомление механиков
    db.commit()
    try:
        await send_localized_notification_to_all_mechanics(
            db,
            "new_car_for_inspection",
            "new_car_for_inspection",
            car_name=car.name,
            plate_number=car.plate_number
        )
    except Exception as e:
        print(e)

    # try:
    #     name_parts = []
    #     if current_user.first_name:
    #         name_parts.append(current_user.first_name)
    #     if current_user.middle_name:
    #         name_parts.append(current_user.middle_name)
    #     if current_user.last_name:
    #         name_parts.append(current_user.last_name)
    #     full_name = " ".join(name_parts) if name_parts else "Не указано"
    #     
    #     login = current_user.phone_number or "Не указан"
    #     
    #     await send_rental_complete_sms(
    #         client_phone=current_user.phone_number,
    #         rent_id=str(rental.id),
    #         full_name=full_name,
    #         login=login,
    #         client_id=str(current_user.id),
    #         digital_signature=current_user.digital_signature or "Не указана",
    #         car_id=str(car.id),
    #         plate_number=car.plate_number,
    #         car_name=car.name
    #     )
    #     print(f"SMS отправлена клиенту {current_user.phone_number} при завершении аренды")
    # except Exception as e:
    #     print(f"Ошибка отправки SMS при завершении аренды: {e}")

    return {
        "message": "Rental completed successfully",
        "rental_id": uuid_to_sid(rental.id),
        "rental_details": {
            "total_duration_minutes": rounded_minutes,
            "total_price": rental.total_price,
            "amount_already_paid": rental.already_payed or 0,
            "current_wallet_balance": float(current_user.wallet_balance)
        },
        "review": {
            "rating": review.rating,
            "comment": review.comment
        } if review_input else None
    }

@RentRouter.post("/advance-booking", response_model=BookingResponse)
async def create_advance_booking(
    booking_request: AdvanceBookingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Создание бронирования заранее с указанием даты и времени
    """
    # Проверяем права на аренду
    validate_user_can_rent(current_user, db)
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
        Car.status == CarStatus.FREE
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
    car.status = CarStatus.SCHEDULED  # Для запланированных аренд машина получает статус SCHEDULED
    
    # Обновляем время последней активности пользователя
    current_user.last_activity_at = datetime.utcnow()
    
    db.commit()

    response_data = {
        "message": "Автомобиль успешно забронирован заранее",
        "rental_id": uuid_to_sid(rental.id),
        "reservation_time": rental.reservation_time.isoformat(),
        "scheduled_start_time": rental.scheduled_start_time.isoformat() if rental.scheduled_start_time else None,
        "scheduled_end_time": rental.scheduled_end_time.isoformat() if rental.scheduled_end_time else None,
        "is_advance_booking": True
    }
    
    converted_data = convert_uuid_response_to_sid(response_data, ["rental_id"])
    return BookingResponse(**converted_data)


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
        booking_data = {
            "id": uuid_to_sid(rental.id),
            "car_id": uuid_to_sid(rental.car_id),
            "car_name": car.name,
            "car_plate_number": car.plate_number,
            "rental_type": rental.rental_type,
            "duration": rental.duration,
            "scheduled_start_time": rental.scheduled_start_time,
            "scheduled_end_time": rental.scheduled_end_time,
            "start_time": rental.start_time,
            "end_time": rental.end_time,
            "rental_status": rental.rental_status,
            "total_price": rental.total_price,
            "base_price": rental.base_price,
            "open_fee": rental.open_fee,
            "delivery_fee": rental.delivery_fee,
            "reservation_time": rental.reservation_time,
            "is_advance_booking": rental.is_advance_booking == "true",
            "car_photos": sort_car_photos(car.photos or []),
            "car_vin": car.vin,
            "car_color": car.color
        }
        
        converted_data = convert_uuid_response_to_sid(booking_data, ["id"])
        result.append(BookingListResponse(**converted_data))

    return result


@RentRouter.post("/cancel-booking/{rental_id}", response_model=CancelBookingResponse)
async def cancel_booking(
    rental_id: str,
    cancel_request: CancelBookingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Отменить бронирование
    """
    # 1) Находим бронирование
    rental_uuid = safe_sid_to_uuid(rental_id)
    rental = db.query(RentalHistory).filter(
        RentalHistory.id == rental_uuid,
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
        record_wallet_transaction(db, user=current_user, amount=refund_amount, ttype=WalletTransactionType.REFUND, description="Возврат предоплаты при отмене бронирования")
        current_user.wallet_balance += refund_amount
        rental.already_payed = 0

    # 4) Отменяем бронирование
    rental.rental_status = RentalStatus.CANCELLED
    
    # 5) Освобождаем автомобиль
    car.current_renter_id = None
    car.status = CarStatus.FREE
    
    db.commit()

    response_data = {
        "message": "Бронирование успешно отменено",
        "rental_id": uuid_to_sid(rental.id),
        "refund_amount": refund_amount
    }
    
    converted_data = convert_uuid_response_to_sid(response_data, ["rental_id"])
    return CancelBookingResponse(**converted_data)


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

    query = db.query(Car).filter(
        Car.status == CarStatus.FREE,
        ~Car.id.in_(conflicting_rentals)
    )
    
    if current_user.role == UserRole.USER and bool(current_user.documents_verified):
        available_classes = get_user_available_auto_classes(current_user, db)
        
        if not available_classes:
            allowed_classes: list[str] = []

            if isinstance(current_user.auto_class, list):
                allowed_classes = [str(c).strip().upper() for c in current_user.auto_class if c]
            elif isinstance(current_user.auto_class, str):
                raw = current_user.auto_class.strip()
                if raw.startswith("{") and raw.endswith("}"):
                    raw = raw[1:-1]
                raw = raw.replace('""', '').replace('"', '').replace("'", "")
                allowed_classes = [part.strip().upper() for part in raw.split(",") if part.strip()]
            
            available_classes = allowed_classes
        
        allowed_enum: list[CarAutoClass] = []
        for cls in available_classes:
            try:
                allowed_enum.append(CarAutoClass(cls))
            except Exception:
                pass

        if allowed_enum:
            query = query.filter(Car.auto_class.in_(allowed_enum))
        else:
            return {
                "available_cars": [],
                "scheduled_start_time": scheduled_start_time.isoformat(),
                "scheduled_end_time": scheduled_end_time.isoformat()
            }
    elif current_user.role == UserRole.REJECTFIRST:
        available_classes = get_user_available_auto_classes(current_user, db)
        
        if available_classes:
            allowed_enum: list[CarAutoClass] = []
            for cls in available_classes:
                try:
                    allowed_enum.append(CarAutoClass(cls))
                except Exception:
                    pass
            
            if allowed_enum:
                query = query.filter(Car.auto_class.in_(allowed_enum))
            else:
                return {
                    "available_cars": [],
                    "scheduled_start_time": scheduled_start_time.isoformat(),
                    "scheduled_end_time": scheduled_end_time.isoformat()
                }
        else:
            return {
                "available_cars": [],
                "scheduled_start_time": scheduled_start_time.isoformat(),
                "scheduled_end_time": scheduled_end_time.isoformat()
            }
    
    available_cars = query.all()

    result = []
    for car in available_cars:
        result.append({
            "id": uuid_to_sid(car.id),
            "name": car.name,
            "plate_number": car.plate_number,
            "price_per_minute": car.price_per_minute,
            "price_per_hour": car.price_per_hour,
            "price_per_day": car.price_per_day,
            "auto_class": car.auto_class,
            "body_type": car.body_type,
            "transmission_type": car.transmission_type,
            "photos": sort_car_photos(car.photos or []),
            "description": car.description,
            "vin": car.vin,
            "color": car.color
        })

    return {
        "available_cars": result,
        "scheduled_start_time": scheduled_start_time.isoformat(),
        "scheduled_end_time": scheduled_end_time.isoformat()
    }
