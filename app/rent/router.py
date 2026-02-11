from math import floor, ceil
from decimal import Decimal
import asyncio
from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, status, Query, Security
from pydantic import BaseModel, constr, Field, conint
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, text
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import httpx
import uuid
import base64

from app.core.logging_config import get_logger
logger = get_logger(__name__)

from app.utils.short_id import safe_sid_to_uuid, uuid_to_sid
from app.utils.sid_converter import convert_uuid_response_to_sid

from app.auth.dependencies.get_current_user import get_current_user
from app.auth.dependencies.save_documents import save_file, validate_photos
from app.dependencies.database.database import get_db
from app.models.history_model import RentalType, RentalStatus, RentalHistory, RentalReview
from app.models.promo_codes_model import PromoCode, UserPromoCode, UserPromoStatus
from app.models.user_model import User, UserRole
from app.models.application_model import Application, ApplicationStatus
from app.models.car_model import Car, CarStatus, CarAutoClass, CarBodyType
from app.models.contract_model import UserContractSignature, ContractFile, ContractType
from app.models.guarantor_model import Guarantor, GuarantorRequest, GuarantorRequestStatus
from app.push.utils import (
    send_notification_to_all_mechanics_async,
    send_push_to_user_by_id,
    send_localized_notification_to_user,
    send_localized_notification_to_user_async,
    send_localized_notification_to_all_mechanics,
    user_has_push_tokens,
)
from app.rent.exceptions import InsufficientBalanceException
from app.wallet.utils import record_wallet_transaction
from app.models.wallet_transaction_model import WalletTransactionType, WalletTransaction
from app.push.enums import NotificationStatus
from app.rent.utils.calculate_price import (
    calculate_total_price,
    get_open_price,
    calc_required_balance,
    calculate_rental_cost_breakdown,
    MINUTE_TARIFF_MIN_MINUTES,
)
from app.rent.utils.tariff_settings import validate_tariff_for_booking, get_tariff_settings_for_car
from app.gps_api.utils.route_data import get_gps_route_data
from app.gps_api.utils.auth_api import get_auth_token
from app.gps_api.utils.car_data import auto_lock_vehicle_after_rental, execute_gps_sequence, send_open, send_unlock_engine
from app.RateLimitedHTTPClient import RateLimitedHTTPClient
from app.core.config import GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD, TELEGRAM_BOT_TOKEN, TELEGRAM_BOT_TOKEN_2, FORTE_SHOP_ID, FORTE_SECRET_KEY
from app.utils.atomic_operations import delete_uploaded_files
from app.utils.telegram_logger import log_error_to_telegram
from app.utils.time_utils import get_local_time
from app.guarantor.sms_utils import send_rental_start_sms, send_rental_complete_sms
from app.owner.schemas import RouteData, RouteMapData
from app.admin.cars.utils import sort_car_photos
from app.rent.schemas import (
    AdvanceBookingRequest, 
    BookingResponse, 
    BookingListResponse, 
    CancelBookingRequest, 
    CancelBookingResponse,
    RentalCalculatorRequest,
    RentalCalculatorResponse,
    RentalCostBreakdown,
    ExtendRentalRequest,
    ExtendRentalResponse
)
from pathlib import Path
from tempfile import NamedTemporaryFile
import shutil
from fastapi.concurrency import run_in_threadpool
from app.services.face_verify import verify_user_upload_against_profile
from app.websocket.notifications import notify_user_status_update, notify_vehicles_list_update
from app.rent.utils.user_utils import get_user_available_auto_classes
from app.rent.utils.balance_utils import recalculate_user_balance_before_rental, verify_and_fix_rental_balance


def get_required_trips_for_class_upgrade(user_classes: List[str], target_class: str) -> int:
    """
    Определяет количество необходимых поездок для доступа к классу авто.
    
    Логика:
    - Класс A -> Класс B: нужно 3 поездки
    - Класс B -> Класс C: нужно 3 поездки
    - Класс A -> Класс C: нужно 5 поездок
    
    Возвращает 0 если пользователь уже имеет доступ к этому классу.
    """
    if not user_classes:
        user_classes = []
    
    # Нормализуем классы к верхнему регистру
    user_classes_upper = [c.upper().strip() for c in user_classes if c]
    target_class_upper = target_class.upper().strip() if target_class else ""
    
    # Если у пользователя уже есть доступ к этому классу - не требуется поездок
    if target_class_upper in user_classes_upper:
        return 0
    
    # Определяем максимальный класс пользователя
    class_hierarchy = {"A": 1, "B": 2, "C": 3}
    target_level = class_hierarchy.get(target_class_upper, 0)
    
    if target_level == 0:
        return 0  # Неизвестный класс - пропускаем проверку
    
    # Находим максимальный уровень класса у пользователя
    max_user_level = 0
    for cls in user_classes_upper:
        level = class_hierarchy.get(cls, 0)
        if level > max_user_level:
            max_user_level = level
    
    # Если у пользователя нет классов, считаем что он на уровне 0
    if max_user_level == 0:
        max_user_level = 1  # По умолчанию считаем класс A
    
    # Если целевой класс ниже или равен текущему - доступ есть
    if target_level <= max_user_level:
        return 0
    
    # Рассчитываем необходимое количество поездок
    level_diff = target_level - max_user_level
    
    if level_diff == 1:
        # Переход на 1 класс выше (A->B или B->C): 3 поездки
        return 3
    elif level_diff == 2:
        # Переход на 2 класса выше (A->C): 5 поездок
        return 5
    else:
        return 0


def check_user_trips_for_class_access(db: Session, user: User, target_car_class: str) -> None:
    """
    Проверяет, имеет ли пользователь достаточно завершенных поездок для доступа к классу авто.
    Выбрасывает HTTPException если поездок недостаточно.
    """
    # Получаем классы пользователя
    user_classes = user.auto_class if user.auto_class else []
    
    # Определяем необходимое количество поездок
    required_trips = get_required_trips_for_class_upgrade(user_classes, target_car_class)
    
    if required_trips == 0:
        return  # Доступ разрешен
    
    # Считаем завершенные поездки пользователя
    completed_trips = db.query(RentalHistory).filter(
        RentalHistory.user_id == user.id,
        RentalHistory.rental_status == RentalStatus.COMPLETED,
        RentalHistory.start_time.isnot(None)  # Только реальные поездки, не отмененные брони
    ).count()
    
    if completed_trips < required_trips:
        trips_remaining = required_trips - completed_trips
        
        # Формируем понятное сообщение об ошибке
        user_class_str = ", ".join(user_classes) if user_classes else "A"
        raise HTTPException(
            status_code=403,
            detail=f"Для доступа к автомобилям класса {target_car_class} необходимо совершить {required_trips} поездок. "
                   f"У вас {completed_trips} завершенных поездок. Осталось: {trips_remaining} поездок."
        )


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
FUEL_PRICE_PER_LITER = 400
ELECTRIC_FUEL_PRICE_PER_LITER = 100


def schedule_notifications(
        user_ids: Optional[List[uuid.UUID]] = None,
        refresh_vehicles: bool = False
) -> None:
    """
    Планировщик уведомлений через WebSocket.
    """
    user_ids = user_ids or []
    unique_ids = {str(uid) for uid in user_ids if uid}
    
    if refresh_vehicles:
        asyncio.create_task(notify_vehicles_list_update())
    
    for uid in unique_ids:
        asyncio.create_task(notify_user_status_update(uid))


def validate_user_can_rent(current_user: User, db: Session) -> None:
    """
    Валидация прав пользователя на аренду автомобилей.
    Проверяет роль и статус заявки пользователя.
    """
    logger.info(
        "validate_user_can_rent: START user_id=%s phone=%s role=%s documents_verified=%s auto_class=%s",
        current_user.id, current_user.phone_number, current_user.role, current_user.documents_verified, getattr(current_user, 'auto_class', None),
    )

    # Владельцы могут арендовать свои машины всегда
    if current_user.role == UserRole.ADMIN:
        logger.info("validate_user_can_rent: user_id=%s is ADMIN - access granted", current_user.id)
        return  # Админы могут всё

    # Проверяем статус заявки в applications для всех пользователей (кроме админов)
    application = db.query(Application).filter(
        Application.user_id == current_user.id
    ).first()

    if application:
        logger.info(
            "validate_user_can_rent: user_id=%s application found application_id=%s financier_status=%s mvd_status=%s",
            current_user.id, application.id, application.financier_status, application.mvd_status,
        )
    else:
        logger.info("validate_user_can_rent: user_id=%s NO APPLICATION FOUND", current_user.id)
    
    # ПРИМЕЧАНИЕ: Проверка mvd_status == REJECTED убрана, так как:
    # - Для роли USER есть отдельная проверка на APPROVED статусы ниже
    # - Для роли REJECTFIRST есть отдельная проверка на MVD
    # - При смене роли в админке статусы application обновляются автоматически
    
    # Блокированные пользователи не могут арендовать
    if current_user.role in [UserRole.REJECTSECOND]:
        logger.warning("validate_user_can_rent: BLOCKED user_id=%s reason=REJECTSECOND", current_user.id)
        raise HTTPException(
            status_code=403,
            detail="Доступ к аренде заблокирован. Обратитесь в поддержку."
        )

    # Пользователи без документов не могут арендовать
    if current_user.role == UserRole.CLIENT:
        logger.warning("validate_user_can_rent: BLOCKED user_id=%s reason=CLIENT (no documents)", current_user.id)
        raise HTTPException(
            status_code=403,
            detail="Для аренды необходимо загрузить и верифицировать документы"
        )

    # Пользователи с неправильными документами не могут арендовать
    if current_user.role == UserRole.REJECTFIRSTDOC:
        logger.warning("validate_user_can_rent: BLOCKED user_id=%s reason=REJECTFIRSTDOC", current_user.id)
        raise HTTPException(
            status_code=403,
            detail="Необходимо загрузить документы заново"
        )

    # Пользователи без сертификатов не могут арендовать
    if current_user.role == UserRole.REJECTFIRSTCERT:
        logger.warning("validate_user_can_rent: BLOCKED user_id=%s reason=REJECTFIRSTCERT", current_user.id)
        raise HTTPException(
            status_code=403,
            detail="Необходимо прикрепить недостающие сертификаты"
        )
    
    # Пользователи с финансовыми проблемами не могут арендовать
    if current_user.role == UserRole.REJECTFIRST:
        logger.info("validate_user_can_rent: user_id=%s has role REJECTFIRST, checking guarantor", current_user.id)
        # Проверяем наличие активного гаранта с одобренным запросом
        active_guarantor = db.query(Guarantor).join(
            GuarantorRequest, Guarantor.request_id == GuarantorRequest.id
        ).options(
            joinedload(Guarantor.guarantor_user)
        ).filter(
            Guarantor.client_id == current_user.id,
            Guarantor.is_active == True,
            GuarantorRequest.status == GuarantorRequestStatus.ACCEPTED
        ).first()

        if active_guarantor:
            guarantor_auto_class = active_guarantor.guarantor_user.auto_class if active_guarantor.guarantor_user else None
            logger.info(
                "validate_user_can_rent: user_id=%s guarantor found guarantor_id=%s guarantor_auto_class=%s",
                current_user.id, active_guarantor.guarantor_id, guarantor_auto_class,
            )
        else:
            logger.info("validate_user_can_rent: user_id=%s NO ACTIVE GUARANTOR found", current_user.id)

        if not active_guarantor or not active_guarantor.guarantor_user or not active_guarantor.guarantor_user.auto_class:
            logger.warning("validate_user_can_rent: BLOCKED user_id=%s reason=REJECTFIRST without valid guarantor", current_user.id)
            raise HTTPException(
                status_code=403,
                detail="Аренда недоступна по финансовым причинам. Обратитесь к гаранту"
            )

        # Проверяем, что МВД одобрил заявку
        if not application or application.mvd_status != ApplicationStatus.APPROVED:
            logger.warning(
                "validate_user_can_rent: BLOCKED user_id=%s reason=REJECTFIRST MVD not approved mvd_status=%s",
                current_user.id, application.mvd_status if application else "NO APPLICATION",
            )
            raise HTTPException(
                status_code=403,
                detail="Ваша заявка находится на рассмотрении. Дождитесь одобрения"
            )

    # Пользователи в процессе верификации не могут арендовать
    if current_user.role in [UserRole.PENDINGTOFIRST, UserRole.PENDINGTOSECOND]:
        logger.warning("validate_user_can_rent: BLOCKED user_id=%s reason=pending verification role=%s", current_user.id, current_user.role)
        raise HTTPException(
            status_code=403,
            detail="Ваша заявка на рассмотрении. Дождитесь одобрения"
        )

    # Для роли USER проверяем только верификацию документов.
    # Статусы заявки (financier_status, mvd_status) не проверяем — если админ поставил роль USER,
    # пользователь может арендовать (статусы application могут быть устаревшими после смены роли).
    if current_user.role == UserRole.USER:
        logger.info("validate_user_can_rent: user_id=%s has role USER, checking documents_verified", current_user.id)
        if not bool(current_user.documents_verified):
            logger.warning("validate_user_can_rent: BLOCKED user_id=%s reason=documents not verified", current_user.id)
            raise HTTPException(
                status_code=403,
                detail="Для аренды необходимо пройти верификацию документов"
            )

    logger.info("validate_user_can_rent: SUCCESS user_id=%s can rent role=%s", current_user.id, current_user.role)


def apply_offset(dt: datetime) -> str | None:
    """Возвращает время в ISO формате (время уже хранится в UTC+5 в базе)"""
    return dt.isoformat() if dt else None


def to_utc_for_glonass(dt: datetime) -> str | None:
    """Преобразует время из UTC+5 (хранится в базе) в UTC для отправки в API Глонасса"""
    if dt is None:
        return None
    # Вычитаем 5 часов, чтобы получить UTC время
    utc_time = dt - timedelta(hours=OFFSET_HOURS)
    return utc_time.strftime('%Y-%m-%dT%H:%M:%S.000Z')


async def get_ecodriving_rating(vehicle_id: str, start_time: datetime, end_time: datetime) -> Optional[float]:
    """
    Получает рейтинг вождения (EcoDriving) из Glonasssoft API.
    
    :param vehicle_id: ID автомобиля в системе Glonasssoft (gps_id)
    :param start_time: Время начала аренды (в UTC+5)
    :param end_time: Время окончания аренды (в UTC+5)
    :return: Рейтинг (score) от 0 до 6, или None при ошибке
    """
    try:
        auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        if not auth_token:
            logger.error("Failed to get auth token for EcoDriving rating")
            return None
        
        from_utc = to_utc_for_glonass(start_time)
        to_utc = to_utc_for_glonass(end_time)
        
        if not from_utc or not to_utc:
            logger.error("Failed to convert datetime to UTC for EcoDriving rating")
            return None
        
        try:
            vehicle_id_int = int(vehicle_id)
        except (ValueError, TypeError):
            logger.error(f"Invalid vehicle_id format: {vehicle_id}")
            return None
        
        client = RateLimitedHTTPClient.get_instance()
        url = "https://regions.glonasssoft.ru/api/v3/EcoDriving/rating"
        headers = {
            "X-Auth": auth_token,
            "Content-Type": "application/json"
        }
        payload = {
            "vehicleIds": [vehicle_id_int],
            "from": from_utc,
            "to": to_utc
        }
        
        response = await client.send_request("POST", url, headers=headers, json=payload)
        
        if response.status_code == 200:
            data = response.json()
            if "items" in data and len(data["items"]) > 0:
                score = data["items"][0].get("score")
                if score is not None:
                    score = min(float(score), 6.0)
                    logger.info(f"EcoDriving rating retrieved: {score} for vehicle {vehicle_id}")
                    return score
                else:
                    logger.warning(f"No score in EcoDriving response for vehicle {vehicle_id}")
            else:
                logger.warning(f"No items in EcoDriving response for vehicle {vehicle_id}")
        else:
            logger.error(f"EcoDriving API error: {response.status_code} - {response.text}")
        
        return None
    except Exception as e:
        logger.error(f"Error getting EcoDriving rating: {e}", exc_info=True)
        return None


def update_user_rating(user_id: uuid.UUID, db: Session) -> None:
    """
    Обновляет рейтинг пользователя как среднее арифметическое всех рейтингов из rental_history.
    
    :param user_id: ID пользователя
    :param db: Сессия базы данных
    """
    try:
        rentals = db.query(RentalHistory).filter(
            RentalHistory.user_id == user_id,
            RentalHistory.rental_status == RentalStatus.COMPLETED,
            RentalHistory.rating.isnot(None)
        ).all()
        
        if not rentals:
            return
        
        ratings = [float(rental.rating) for rental in rentals if rental.rating is not None]
        if ratings:
            average_rating = sum(ratings) / len(ratings)
            average_rating = min(average_rating, 6.0)
            
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                user.rating = average_rating
                logger.info(f"Updated user {user_id} rating to {average_rating} (based on {len(ratings)} rentals)")
    except Exception as e:
        logger.error(f"Error updating user rating: {e}", exc_info=True)


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
                    # Электрокар: 100₸/л, Обычный: 400₸/л
                    if car.body_type == CarBodyType.ELECTRIC:
                        price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER  # 100₸
                    else:
                        price_per_liter = FUEL_PRICE_PER_LITER  # 400₸
                    
                    # Топливо оплачивается для всех тарифов (MINUTES, HOURS, DAYS)
                    fuel_fee_display = int(fuel_consumed * price_per_liter)
        
        # Вычисляем сумму без топлива для отображения
        total_price_without_fuel = (
            (rental.base_price or 0)
            + (rental.open_fee or 0)
            + (rental.delivery_fee or 0)
            + (rental.waiting_fee or 0)
            + (rental.overtime_fee or 0)
            + (rental.distance_fee or 0)
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
            "fuel_after_main_tariff": rental.fuel_after_main_tariff,
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
            "delivery_mechanic_comment": review.delivery_mechanic_comment if review else None,
            "rating": rental.rating,
            "with_driver": rental.with_driver,
            "driver_fee": rental.driver_fee or 0,
            "rebooking_fee": rental.rebooking_fee or 0
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
        + (rental.open_fee or 0)
        + (rental.delivery_fee or 0)
        + (rental.waiting_fee or 0)
        + (rental.overtime_fee or 0)
        + (rental.distance_fee or 0)
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
            int((ceil(rental.fuel_before) - floor(rental.fuel_after)) * (ELECTRIC_FUEL_PRICE_PER_LITER if car.body_type == CarBodyType.ELECTRIC else FUEL_PRICE_PER_LITER))
            if rental.fuel_before is not None and rental.fuel_after is not None and
               rental.fuel_after < rental.fuel_before and
               (ceil(rental.fuel_before) - floor(rental.fuel_after)) > 0 else 0
        ))(),
        "fuel_before": rental.fuel_before,
        "fuel_after": rental.fuel_after,
        "fuel_after_main_tariff": rental.fuel_after_main_tariff,
        "waiting_fee": rental.waiting_fee,
        "overtime_fee": rental.overtime_fee,
        "distance_fee": rental.distance_fee,
        "rating": rental.rating,
        "with_driver": rental.with_driver,
        "driver_fee": rental.driver_fee or 0,
        "rebooking_fee": rental.rebooking_fee or 0,
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
                start_date=rental.start_time.isoformat() if rental.start_time else None,
                end_date=rental.end_time.isoformat() if rental.end_time else None
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


async def verify_forte_transaction(tracking_id: str) -> tuple[bool, Optional[int], Optional[str]]:
    """
    Проверяет транзакцию через API ForteBank
    Возвращает: (is_successful, amount, error_message)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if not FORTE_SHOP_ID or not FORTE_SECRET_KEY:
        logger.error("ForteBank credentials not configured")
        return False, None, "ForteBank credentials not configured"
    
    try:
        # Создаем Basic Auth заголовок
        credentials = f"{FORTE_SHOP_ID}:{FORTE_SECRET_KEY}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        url = f"https://gateway.fortebank.com/v2/transactions/tracking_id/{tracking_id}"
        headers = {
            "Authorization": f"Basic {encoded_credentials}"
        }
        
        logger.info(f"Checking ForteBank transaction: tracking_id={tracking_id}, url={url}")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            
            # Логируем ответ для отладки
            logger.info(f"ForteBank API response: status={response.status_code}, tracking_id={tracking_id}")
            
            if response.status_code == 404:
                logger.warning(f"Transaction not found: tracking_id={tracking_id}")
                return False, None, "Транзакция не найдена"
            
            if response.status_code != 200:
                # Пытаемся получить детали ошибки из ответа
                try:
                    error_data = response.json()
                    error_message = error_data.get("message") or error_data.get("detail") or error_data.get("error") or str(error_data)
                    logger.error(f"ForteBank API error: status={response.status_code}, message={error_message}, full_response={error_data}")
                    # Возвращаем детальное сообщение об ошибке
                    return False, None, f"Ошибка API ForteBank ({response.status_code}): {error_message}"
                except Exception as parse_error:
                    error_text = response.text[:1000]  # Первые 1000 символов
                    logger.error(f"ForteBank API error: status={response.status_code}, response_text={error_text}, parse_error={str(parse_error)}")
                    return False, None, f"Ошибка API ForteBank ({response.status_code}): {error_text if error_text else 'Не удалось получить детали ошибки'}"
            
            data = response.json()
            transactions = data.get("transactions", [])
            
            logger.info(f"Found {len(transactions)} transactions for tracking_id={tracking_id}")
            
            if not transactions:
                logger.warning(f"No transactions found: tracking_id={tracking_id}")
                return False, None, "Транзакции не найдены"
            
            # Ищем успешную транзакцию
            successful_transaction = None
            for tx in transactions:
                tx_status = tx.get("status")
                logger.info(f"Transaction status: {tx_status}, type: {tx.get('type')}, amount: {tx.get('amount')}")
                if tx_status == "successful":
                    successful_transaction = tx
                    break
            
            if not successful_transaction:
                logger.warning(f"No successful transaction found: tracking_id={tracking_id}, transactions={transactions}")
                return False, None, "Успешная транзакция не найдена"
            
            # Проверяем, что это платеж (type == "payment")
            if successful_transaction.get("type") != "payment":
                logger.warning(f"Transaction is not a payment: type={successful_transaction.get('type')}")
                return False, None, "Транзакция не является платежом"
            
            # Получаем сумму (в тийинах, нужно разделить на 100)
            amount_tiyin = successful_transaction.get("amount", 0)
            amount_kzt = amount_tiyin / 100
            
            logger.info(f"Transaction verified successfully: tracking_id={tracking_id}, amount={amount_kzt} KZT")
            
            return True, int(amount_kzt), None
            
    except httpx.TimeoutException as e:
        logger.error(f"Timeout checking ForteBank transaction: tracking_id={tracking_id}, error={str(e)}")
        return False, None, "Таймаут при проверке транзакции"
    except httpx.RequestError as e:
        logger.error(f"Request error checking ForteBank transaction: tracking_id={tracking_id}, error={str(e)}")
        return False, None, f"Ошибка запроса: {str(e)}"
    except Exception as e:
        logger.exception(f"Unexpected error checking ForteBank transaction: tracking_id={tracking_id}, error={str(e)}")
        return False, None, f"Ошибка при проверке транзакции: {str(e)}"


@RentRouter.post("/add_money")
async def add_money(amount: int,
              tracking_id: Optional[str] = None,
              db: Session = Depends(get_db),
              current_user: User = Depends(get_current_user)):
    if not tracking_id:
        raise HTTPException(
            status_code=400,
            detail="tracking_id обязателен для пополнения"
        )
    
    existing_transaction = db.query(WalletTransaction).filter(
        WalletTransaction.tracking_id == tracking_id
    ).with_for_update().first()
    
    if existing_transaction:
        if existing_transaction.user_id == current_user.id:
            return {
                "wallet_balance": float(current_user.wallet_balance),
                "bonus": 0,
                "promo_applied": False,
                "message": "Транзакция уже была обработана"
            }
        else:
            raise HTTPException(
                status_code=400,
                detail="Транзакция уже была обработана для другого пользователя"
            )
    
    # Проверяем транзакцию через API ForteBank
    is_successful, verified_amount, error_message = await verify_forte_transaction(tracking_id)
    
    if not is_successful:
        raise HTTPException(
            status_code=400,
            detail=error_message or "Транзакция не прошла проверку"
        )
    
    # Используем сумму из проверенной транзакции
    if verified_amount and verified_amount != amount:
        amount = verified_amount
    
    # Ищем у юзера активный промокод
    up = db.query(UserPromoCode) \
        .filter_by(user_id=current_user.id, status=UserPromoStatus.ACTIVATED) \
        .join(PromoCode) \
        .first()

    bonus = 0
    promo_applied = False

    if up:
        bonus = int(amount * (float(up.promo.discount_percent) / 100))
        promo_applied = True

        # Фиксируем баланс до депозита
        before = float(current_user.wallet_balance or 0)
        
        # Записываем транзакции
        record_wallet_transaction(db, user=current_user, amount=amount, ttype=WalletTransactionType.DEPOSIT, description="Пополнение кошелька", balance_before_override=before, tracking_id=tracking_id)
        record_wallet_transaction(db, user=current_user, amount=bonus, ttype=WalletTransactionType.PROMO_BONUS, description=f"Бонус по промокоду {up.promo.code if up and up.promo else ''}", balance_before_override=before + amount)
        
        # Атомарное обновление баланса через SQL
        total_amount = amount + bonus
        db.execute(
            text("UPDATE users SET wallet_balance = wallet_balance + :amount WHERE id = :user_id"),
            {"amount": total_amount, "user_id": current_user.id}
        )

        # Меняем статус промокода
        up.status = UserPromoStatus.USED
        up.used_at = get_local_time()

    else:
        # Обычное пополнение
        record_wallet_transaction(db, user=current_user, amount=amount, ttype=WalletTransactionType.DEPOSIT, description="Пополнение кошелька", tracking_id=tracking_id)
        
        # Атомарное обновление баланса через SQL
        db.execute(
            text("UPDATE users SET wallet_balance = wallet_balance + :amount WHERE id = :user_id"),
            {"amount": amount, "user_id": current_user.id}
        )

    db.commit()
    
    # Обновляем объект пользователя после commit
    db.refresh(current_user)

    asyncio.create_task(notify_user_status_update(str(current_user.id)))

    # Отправляем уведомление о пополнении баланса
    if user_has_push_tokens(db, current_user.id):
        asyncio.create_task(
            send_localized_notification_to_user_async(
                current_user.id,
                "balance_top_up",
                "balance_top_up"
            )
        )

    return {
        "wallet_balance": float(current_user.wallet_balance),
        "bonus": bonus,
        "promo_applied": promo_applied
    }


class ApplyPromoRequest(BaseModel):
    code: str


@RentRouter.post("/promo_codes/apply")
async def apply_promo(body: ApplyPromoRequest,
                db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    # 1) Пробуем найти скидочный промокод
    promo = db.query(PromoCode) \
        .filter_by(code=body.code, is_active=True) \
        .first()

    if promo:
        # --- Скидочный промокод ---
        exist = db.query(UserPromoCode) \
            .filter_by(user_id=current_user.id, status=UserPromoStatus.ACTIVATED) \
            .first()
        if exist:
            raise HTTPException(400, "У вас уже есть неиспользованный промокод")

        up = UserPromoCode(user_id=current_user.id, promo_code_id=promo.id)
        db.add(up)
        db.commit()

        # Отправляем уведомление о доступном промокоде
        if user_has_push_tokens(db, current_user.id):
            asyncio.create_task(
                send_localized_notification_to_user_async(
                    current_user.id,
                    "promo_code_available",
                    "promo_code_available"
                )
            )

        return {
            "message": "Промокод активирован",
            "code": promo.code,
            "discount_percent": float(promo.discount_percent)
        }

    # 2) Не найден как скидочный — пробуем как бонусный
    from app.promo.service import apply_promo_code

    success, message, bonus_amount, new_balance = await apply_promo_code(
        db, current_user, body.code,
    )

    if not success:
        if "уже использовали" in message:
            raise HTTPException(409, message)
        raise HTTPException(400, message)

    return {
        "message": message,
        "bonus_amount": bonus_amount,
        "new_balance": new_balance,
    }


@RentRouter.get("/tariff-availability")
async def get_tariff_availability(
    car_id: str = Query(..., description="ID автомобиля"),
    db: Session = Depends(get_db),
):
    """
    Публичный эндпоинт: доступность тарифов для бронирования по конкретной машине.
    Недоступные тарифы не должны показываться в выборе и не принимаются в API бронирования.
    """
    car_uuid = safe_sid_to_uuid(car_id)
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    settings = get_tariff_settings_for_car(car)
    logger.debug(
        "tariff_availability: car_id=%s minutes=%s hourly=%s min_hours=%s",
        car_id, settings["minutes_tariff_enabled"], settings["hourly_tariff_enabled"], settings["hourly_min_hours"],
    )
    return settings


@RentRouter.post("/calculator", response_model=RentalCalculatorResponse)
async def calculate_rental_cost(
        request: RentalCalculatorRequest,
        db: Session = Depends(get_db)
):
    """
    Калькулятор стоимости аренды.
    Позволяет пользователю заранее рассчитать минимальный баланс для аренды автомобиля.
    Публичный эндпоинт, не требует авторизации.
    Для владельцев минимальный баланс будет рассчитан как 0 при реальном резервировании.
    """
    car_uuid = safe_sid_to_uuid(request.car_id)
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    validate_tariff_for_booking(request.rental_type, request.duration, car)
    
    # Для калькулятора всегда считаем как для обычного пользователя
    # (владельцы получат минимальный баланс = 0 при реальном резервировании)
    is_owner = False
    
    # Валидация duration для HOURS и DAYS
    if request.rental_type in [RentalType.HOURS, RentalType.DAYS]:
        if request.duration is None or request.duration <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Параметр duration обязателен для типа аренды {request.rental_type.value}"
            )
    
    # Рассчитываем детализированную стоимость
    try:
        cost_breakdown = calculate_rental_cost_breakdown(
            rental_type=request.rental_type,
            duration=request.duration,
            car=car,
            include_delivery=request.include_delivery,
            is_owner=is_owner,
            with_driver=request.with_driver
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Ошибка расчета стоимости аренды: %s", e)
        raise HTTPException(status_code=500, detail=f"Ошибка расчета стоимости: {str(e)}")

    logger.info(
        "calculator: расчёт выполнен car_id=%s rental_type=%s total_minimum_balance=%s",
        request.car_id,
        request.rental_type.value if hasattr(request.rental_type, "value") else request.rental_type,
        cost_breakdown["total_minimum_balance"],
    )
    return {
        "car_id": request.car_id,
        "car_name": car.name,
        "rental_type": request.rental_type,
        "duration": request.duration,
        "include_delivery": request.include_delivery,
        "breakdown": RentalCostBreakdown(**cost_breakdown["breakdown"]),
        "total_minimum_balance": cost_breakdown["total_minimum_balance"]
    }


@RentRouter.post("/reserve-car/{car_id}")
async def reserve_car(
        car_id: str,
        rental_type: RentalType,
        duration: Optional[int] = None,
        with_driver: bool = Query(False, description="Аренда с водителем"),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    logger.info(
        "reserve_car: START car_id=%s rental_type=%s duration=%s with_driver=%s user_id=%s user_phone=%s user_role=%s",
        car_id, rental_type, duration, with_driver, current_user.id, current_user.phone_number, current_user.role,
    )

    car_uuid = safe_sid_to_uuid(car_id)
    car_meta = db.query(Car.id, Car.owner_id, Car.status).filter(Car.id == car_uuid).first()
    if not car_meta:
        logger.warning("reserve_car: car not found car_id=%s", car_id)
        raise HTTPException(status_code=404, detail="Car not found")

    logger.info(
        "reserve_car: car found car_id=%s car_uuid=%s owner_id=%s status=%s is_owner=%s",
        car_id, car_uuid, car_meta.owner_id, car_meta.status, car_meta.owner_id == current_user.id,
    )

    # Запреты по ролям/верификации для НЕ владельцев
    if car_meta.owner_id != current_user.id:
        logger.info("reserve_car: user is not owner, validating user_id=%s", current_user.id)
        validate_user_can_rent(current_user, db)

        # Проверяем подписание договора о присоединении (MAIN_CONTRACT)
        main_contract_signed = db.query(UserContractSignature).join(ContractFile).filter(
            UserContractSignature.user_id == current_user.id,
            ContractFile.contract_type == ContractType.MAIN_CONTRACT
        ).first() is not None

        logger.info("reserve_car: contract check user_id=%s main_contract_signed=%s", current_user.id, main_contract_signed)

        if not main_contract_signed:
            logger.warning("reserve_car: blocked user_id=%s reason=main contract not signed", current_user.id)
            raise HTTPException(
                status_code=403,
                detail="Необходимо подписать договор о присоединении перед бронированием автомобиля"
            )

        logger.info("reserve_car: validation passed for user_id=%s", current_user.id)

    # 1) Проверяем, нет ли у пользователя уже активной аренды
    active_rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status.in_([
            RentalStatus.RESERVED,
            RentalStatus.IN_USE
        ])
    ).first()
    if active_rental:
        logger.warning(
            "reserve_car: user has active rental user_id=%s rental_id=%s car_id=%s",
            current_user.id, uuid_to_sid(active_rental.id), car_id,
        )
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
        logger.warning("reserve_car: car not available car_id=%s user_id=%s (not FREE)", car_id, current_user.id)
        raise HTTPException(status_code=404, detail="Car not found or not available")

    # 3) Проверка доступа к классу авто по количеству поездок (только для НЕ владельцев)
    if car.owner_id != current_user.id and car.auto_class:
        check_user_trips_for_class_access(db, current_user, car.auto_class.value if hasattr(car.auto_class, 'value') else str(car.auto_class))

    orig_open_fee = get_open_price(car)
    open_fee = orig_open_fee if rental_type in (RentalType.MINUTES, RentalType.HOURS) else 0

    # стоимость открытия
    price_per_hour = car.price_per_hour
    price_per_day = car.price_per_day

    # Владелец: берёт свою машину бесплатно
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
            reservation_time=get_local_time(),
            with_driver=with_driver
        )
        db.add(rental)
        db.commit()
        db.refresh(rental)

        # Обновляем статус машины
        car.current_renter_id = current_user.id
        car.status = CarStatus.OWNER  # Машина у владельца
        
        # Обновляем время последней активности пользователя
        current_user.last_activity_at = get_local_time()
        
        db.commit()

        logger.info(
            "reserve_car: owner rental created rental_id=%s car_id=%s user_id=%s",
            uuid_to_sid(rental.id), car_id, current_user.id,
        )
        return {
            "message": "Car reserved successfully (owner rental)",
            "rental_id": uuid_to_sid(rental.id),
            "reservation_time": rental.reservation_time.isoformat()
        }

    # Доступность тарифа и минимум часов для часового (только для не-владельцев)
    validate_tariff_for_booking(rental_type, duration, car)
    logger.info(
        "reserve_car: тариф проверен car_id=%s rental_type=%s duration=%s user_id=%s",
        car_id, rental_type.value if hasattr(rental_type, "value") else rental_type, duration, current_user.id,
    )

    # Проверяем, был ли у пользователя ранее отмененная бронь для этого же car_id
    # Отмена бронирования: CANCELLED или COMPLETED без start_time (отменено до начала использования)
    # Успешное завершение аренды имеет start_time, поэтому не учитывается
    previous_rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.car_id == car.id,
        or_(
            RentalHistory.rental_status == RentalStatus.CANCELLED,
            and_(
                RentalHistory.rental_status == RentalStatus.COMPLETED,
                RentalHistory.start_time.is_(None)  # Отмена бронирования до начала использования
            )
        )
    ).order_by(RentalHistory.reservation_time.desc()).first()
    
    rebooking_fee = 0

    # НЕ владельцу – проверка баланса
    required_balance = calc_required_balance(
        rental_type=rental_type,
        duration=duration,
        car=car,
        include_delivery=False,
        is_owner=False
    )
    logger.info(
        "reserve_car: требуемый баланс car_id=%s required=%s balance=%s user_id=%s",
        car_id, required_balance, int(current_user.wallet_balance or 0), current_user.id,
    )
    # Добавляем комиссию за повторное бронирование к требуемому балансу
    total_required_balance = required_balance + rebooking_fee

    if current_user.wallet_balance < total_required_balance:
        logger.warning(
            "reserve_car: insufficient balance car_id=%s user_id=%s required=%s balance=%s",
            car_id, current_user.id, total_required_balance, float(current_user.wallet_balance or 0),
        )
        raise InsufficientBalanceException(required_amount=total_required_balance)

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
        open_fee=0,
        delivery_fee=0,
        waiting_fee=0,
        overtime_fee=0,
        distance_fee=0,
        total_price=base,
        reservation_time=get_local_time(),
        with_driver=with_driver,
        rebooking_fee=rebooking_fee 
    )
    db.add(rental)
    db.commit()
    db.refresh(rental)
    logger.info(
        "reserve_car: бронь создана rental_id=%s car_id=%s user_id=%s rental_type=%s duration=%s",
        uuid_to_sid(rental.id), car_id, current_user.id,
        rental_type.value if hasattr(rental_type, "value") else rental_type, duration,
    )

    # Списываем комиссию за повторное бронирование, если применимо
    if rebooking_fee > 0:
        balance_before = float(current_user.wallet_balance or 0)
        current_user.wallet_balance = balance_before - rebooking_fee
        record_wallet_transaction(
            db,
            user=current_user,
            amount=-rebooking_fee,
            ttype=WalletTransactionType.RESERVATION_REBOOKING_FEE,
            description=f"Списание за повторное бронирование того же автомобиля",
            related_rental=rental
        )

    # Обновляем машину: устанавливаем текущего арендатора и меняем статус на RESERVED
    car.current_renter_id = current_user.id
    car.status = CarStatus.RESERVED
    
    # Обновляем время последней активности пользователя
    current_user.last_activity_at = get_local_time()
    
    db.commit()

    schedule_notifications(
        user_ids=[current_user.id, car.owner_id],
        refresh_vehicles=True
    )

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
        with_driver: bool = Query(False, description="Аренда с водителем"),
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
            total_price = delivery_fee

        elif rental_type == RentalType.HOURS:
            if duration is None:
                raise HTTPException(status_code=400, detail="Duration обязателен для аренды по часам.")
            base_price = calculate_total_price(rental_type, duration, price_per_hour, price_per_day)
            total_price = base_price + delivery_fee

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
        open_fee=0,
        delivery_fee=delivery_fee,
        waiting_fee=0,
        overtime_fee=0,
        distance_fee=0,
        total_price=total_price,
        reservation_time=get_local_time(),
        delivery_latitude=delivery_latitude,
        delivery_longitude=delivery_longitude,
        with_driver=with_driver
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
    current_user.last_activity_at = get_local_time()
    
    db.commit()

    # Уведомляем всех механиков
    await send_localized_notification_to_all_mechanics(
        db, 
        "delivery_new_order", 
        "delivery_new_order",
        car_name=car.name,
        plate_number=car.plate_number
    )

    schedule_notifications(
        user_ids=[current_user.id, car.owner_id],
        refresh_vehicles=True
    )

    # Уведомление в Telegram о новом заказе доставки
    try:
        name_parts = []
        if current_user.first_name:
            name_parts.append(current_user.first_name)
        if current_user.middle_name:
            name_parts.append(current_user.middle_name)
        if current_user.last_name:
            name_parts.append(current_user.last_name)
        full_name = " ".join(name_parts) if name_parts else "Не указано"

        phone_number = current_user.phone_number or "Не указан"
        email = current_user.email or "Не указан"
        user_short_id = uuid_to_sid(current_user.id)
        car_short_id = uuid_to_sid(car.id)
        rental_short_id = uuid_to_sid(rental.id)
        duration_text = f"{duration} ед." if duration is not None else "Не указана"

        notification_text = (
            "🚗 Новый заказ доставки \n\n"
            f"Клиент: {full_name}\n"
            f"User ID: {user_short_id}\n"
            f"Телефон: {phone_number}\n"
            f"Email: {email}\n\n"
            f"Авто: {car.name}\n"
            f"Гос. номер: {car.plate_number or 'Не указан'}\n"
            f"Car ID: {car_short_id}\n"
            f"Rental ID: {rental_short_id}\n"
            f"Точка доставки: {delivery_latitude:.6f}, {delivery_longitude:.6f}"
        )

        async def _send_delivery_notification(text: str, chat_id: int, bot_token: str):
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": chat_id, "text": text}
                    )
            except Exception as e:
                logger.error(f"Ошибка отправки Telegram уведомления о доставке (chat {chat_id}): {e}")

        chat_ids = [965048905, 5941825713, 860991388, 1594112444, 808277096, 7656716395, 964255811, 8522837235, 797693964]
        if TELEGRAM_BOT_TOKEN:
            for chat_id in chat_ids:
                asyncio.create_task(_send_delivery_notification(notification_text, chat_id, TELEGRAM_BOT_TOKEN))
        if TELEGRAM_BOT_TOKEN_2:
            for chat_id in chat_ids:
                asyncio.create_task(_send_delivery_notification(notification_text, chat_id, TELEGRAM_BOT_TOKEN_2))
    except Exception as e:
        logger.error(f"Не удалось отправить Telegram уведомление о доставке: {e}")

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

    now = get_local_time()
    # Для расчета времени используем reservation_time или start_time
    base_time = rental.start_time or rental.reservation_time or now

    if car.owner_id == current_user.id:
        # Логика для владельца: аренда бесплатная, пропускаем комиссии
        rental.rental_status = RentalStatus.COMPLETED
        rental.end_time = now
        # start_time устанавливается только при реальном старте аренды, не при отмене
        rental.total_price = 0
        rental.already_payed = 0
        rental.end_latitude = car.latitude
        rental.end_longitude = car.longitude
        # Записываем топливо при завершении аренды
        if rental.rental_type in (RentalType.HOURS, RentalType.DAYS) and rental.overtime_fee and rental.overtime_fee > 0:
            rental.fuel_after_main_tariff = car.fuel_level
        else:
            if rental.fuel_after is None:
                rental.fuel_after = car.fuel_level
        
        # Рассчитываем продолжительность поездки в минутах (только если аренда уже началась)
        if rental.start_time:
            duration_seconds = (now - rental.start_time).total_seconds()
            rental.duration = int(duration_seconds / 60)
        else:
            # Если аренда отменена до старта, продолжительность = 0
            rental.duration = 0
        
        car.current_renter_id = None
        car.status = CarStatus.FREE
        db.commit()

        schedule_notifications(
            user_ids=[current_user.id, car.owner_id],
            refresh_vehicles=True
        )

        return {
            "message": "Аренда отменена (owner rental)",
            "minutes_used": int((now - (rental.start_time or base_time)).total_seconds() / 60),
            "cancellation_fee": 0,
            "current_wallet_balance": float(current_user.wallet_balance)
        }
    else:
        # Рассчитываем время, прошедшее с момента бронирования
        time_passed = (now - base_time).total_seconds() / 60

        cancellation_penalty = 2000
        
        if current_user.wallet_balance < cancellation_penalty:
            raise HTTPException(
                status_code=400,
                detail=f"Недостаточно средств для отмены бронирования. Комиссия за отмену: {cancellation_penalty} тг"
            )
        
        balance_before_penalty = float(current_user.wallet_balance or 0)
        current_user.wallet_balance = balance_before_penalty - cancellation_penalty
        
        cancellation_tx = WalletTransaction(
            user_id=current_user.id,
            amount=-cancellation_penalty,
            transaction_type=WalletTransactionType.RESERVATION_CANCELLATION_FEE,
            description="Комиссия за отмену бронирования",
            balance_before=balance_before_penalty,
            balance_after=current_user.wallet_balance,
            related_rental_id=rental.id,
            created_at=get_local_time(),
        )
        db.add(cancellation_tx)

        # Комиссия за ожидание при отмене (если прошло больше 15 минут)
        # Рассчитываем полную сумму платного ожидания на момент отмены
        total_waiting_fee = 0
        if time_passed > 15:
            extra_minutes = floor(time_passed - 15)
            total_waiting_fee = int(extra_minutes * car.price_per_minute * 0.5)

        # Уже начисленная сумма платного ожидания (из billing.py)
        already_charged_waiting_fee = rental.waiting_fee or 0
        
        # Дополнительная сумма, которую нужно списать при отмене
        additional_fee = max(0, total_waiting_fee - already_charged_waiting_fee)
        
        # Обновляем или создаем транзакцию платного ожидания
        if total_waiting_fee > 0:
            # Находим существующую транзакцию платного ожидания для этой аренды
            existing_tx = db.query(WalletTransaction).filter(
                WalletTransaction.user_id == current_user.id,
                WalletTransaction.transaction_type == WalletTransactionType.RENT_WAITING_FEE,
                WalletTransaction.related_rental_id == rental.id
            ).first()
            
            if additional_fee > 0:
                if current_user.wallet_balance < additional_fee:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Недостаточно средств для отмены аренды с комиссией: {additional_fee} тг"
                    )
            
            if existing_tx:
                # Обновляем существующую транзакцию
                if additional_fee > 0:
                    current_balance = float(current_user.wallet_balance or 0)
                    new_balance_after = current_balance - additional_fee
                    
                    existing_tx.amount = -total_waiting_fee
                    existing_tx.description = f"Платное ожидание за {int(time_passed - 15)} мин"
                    existing_tx.balance_after = new_balance_after
                    
                    current_user.wallet_balance = new_balance_after
                else:
                    # Транзакция уже содержит правильную сумму, просто обновляем описание
                    existing_tx.description = f"Платное ожидание за {int(time_passed - 15)} мин"
            else:
                # Создаем новую транзакцию, если её еще нет
                if total_waiting_fee > 0:
                    balance_before = float(current_user.wallet_balance or 0)
                    new_balance = balance_before - total_waiting_fee
                    
                    if current_user.wallet_balance < total_waiting_fee:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Недостаточно средств для отмены аренды с комиссией: {total_waiting_fee} тг"
                        )
                    
                    tx = WalletTransaction(
                        user_id=current_user.id,
                        amount=-total_waiting_fee,
                        transaction_type=WalletTransactionType.RENT_WAITING_FEE,
                        description=f"Платное ожидание за {int(time_passed - 15)} мин",
                        balance_before=balance_before,
                        balance_after=new_balance,
                        related_rental_id=rental.id,
                        created_at=get_local_time(),
                    )
                    db.add(tx)
                    current_user.wallet_balance = new_balance
            
            # Обновляем waiting_fee в rental
            rental.waiting_fee = total_waiting_fee
        
        # Итоговая сумма платного ожидания
        final_waiting_fee = total_waiting_fee
        
        # Начисление 50% от суммы платного ожидания владельцу при отмене
        if final_waiting_fee > 0 and car.owner_id:
            owner = db.query(User).filter(User.id == car.owner_id).first()
            if owner:
                owner_earnings = int(final_waiting_fee * 0.5)
                owner.wallet_balance = (owner.wallet_balance or 0) + owner_earnings
                record_wallet_transaction(
                    db, 
                    user=owner, 
                    amount=owner_earnings, 
                    ttype=WalletTransactionType.OWNER_WAITING_FEE_SHARE, 
                    description=f"50% от платного ожидания при отмене бронирования (аренда ID: {rental.id})",
                    related_rental=rental
                )

        # Завершаем аренду
        rental.rental_status = RentalStatus.COMPLETED
        rental.end_time = now
        # start_time устанавливается только при реальном старте аренды, не при отмене
        rental.total_price = final_waiting_fee
        rental.already_payed = final_waiting_fee
        # Записываем топливо при завершении аренды
        if rental.rental_type in (RentalType.HOURS, RentalType.DAYS) and rental.overtime_fee and rental.overtime_fee > 0:
            rental.fuel_after_main_tariff = car.fuel_level
        else:
            if rental.fuel_after is None:
                rental.fuel_after = car.fuel_level
        
        # Рассчитываем продолжительность поездки в минутах (только если аренда уже началась)
        if rental.start_time:
            duration_seconds = (now - rental.start_time).total_seconds()
            rental.duration = int(duration_seconds / 60)
        else:
            # Если аренда отменена до старта, продолжительность = 0
            rental.duration = 0

        # Освобождаем машину и возвращаем статус "FREE"
        car.current_renter_id = None
        car.status = CarStatus.FREE

        try:
            db.commit()

            schedule_notifications(
                user_ids=[current_user.id, car.owner_id],
                refresh_vehicles=True
            )

            return {
                "message": "Аренда отменена",
                "minutes_used": int(time_passed),
                "cancellation_fee": cancellation_penalty + final_waiting_fee,
                "cancellation_penalty": cancellation_penalty,
                "waiting_fee": final_waiting_fee,
                "current_wallet_balance": float(current_user.wallet_balance)
            }
        except Exception as e:
            db.rollback()
            try:
                await log_error_to_telegram(
                    error=e,
                    request=None,
                    user=current_user,
                    additional_context={
                        "action": "cancel_rental_reservation",
                        "rental_id": str(rental.id),
                        "car_id": str(rental.car_id),
                        "user_id": str(current_user.id),
                        "cancellation_fee": final_waiting_fee
                    }
                )
            except:
                pass
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
    rental.end_time = get_local_time()
    
    # Если доставка была в процессе, записываем время окончания
    if rental.delivery_start_time and not rental.delivery_end_time:
        rental.delivery_end_time = get_local_time()
    
    # Записываем топливо при завершении аренды
    if rental.rental_type in (RentalType.HOURS, RentalType.DAYS) and rental.overtime_fee and rental.overtime_fee > 0:
        rental.fuel_after_main_tariff = car.fuel_level
    else:
        if rental.fuel_after is None:
            rental.fuel_after = car.fuel_level
    
    # Рассчитываем продолжительность поездки в минутах
    if rental.start_time:
        duration_seconds = (get_local_time() - rental.start_time).total_seconds()
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

    schedule_notifications(
        user_ids=[current_user.id, car.owner_id],
        refresh_vehicles=True
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
        rental.start_time = get_local_time()
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
                logger.info(f"Двигатель автомобиля {car.name} разблокирован при начале аренды (владелец)")
            else:
                logger.error(f"Ошибка GPS последовательности для владельца: {result.get('error', 'Unknown error')}")
        except Exception as e:
            logger.error(f"Ошибка разблокировки двигателя при начале аренды (владелец): {e}")
            # Логируем критическую ошибку GPS команды
            try:
                await log_error_to_telegram(
                    error=e,
                    request=None,
                    user=current_user,
                    additional_context={
                        "action": "start_rental_owner_unlock_engine",
                        "car_id": car_id,
                        "car_name": car.name,
                        "gps_imei": car.gps_imei,
                        "rental_id": str(rental.id)
                    }
                )
            except:
                pass
        
        is_owner_rental = True
    else:
        # Обновляем время последней активности пользователя
        current_user.last_activity_at = get_local_time()

        # Для суточного и часового тарифа списываем полную стоимость сразу
        # Для минутного тарифа списываем только open_fee (поминутный тариф списывается во время поездки)
        total_cost = 0
        
        if rental.rental_type in [RentalType.HOURS, RentalType.DAYS]:
            # Проверяем достаточность баланса
            open_fee_value = get_open_price(car) if rental.rental_type == RentalType.HOURS else 0
            total_cost = (rental.base_price or 0) + open_fee_value + (rental.delivery_fee or 0)
            
            if current_user.wallet_balance < total_cost:
                raise HTTPException(
                    status_code=402,
                    detail=f"Нужно минимум {total_cost} ₸ для старта. Пополните кошелёк!"
                )
            
            # Списываем ОТДЕЛЬНЫМИ транзакциями для прозрачности
            total_charged = 0
            
            # 1. Базовая стоимость аренды
            if rental.base_price and rental.base_price > 0:
                record_wallet_transaction(
                    db, 
                    user=current_user, 
                    amount=-rental.base_price, 
                    ttype=WalletTransactionType.RENT_BASE_CHARGE, 
                    description=f"Оплата аренды: {rental.duration} {'час(ов)' if rental.rental_type == RentalType.HOURS else 'день(дней)'}",
                    related_rental=rental
                )
                current_user.wallet_balance -= rental.base_price
                total_charged += rental.base_price
            
            # 2. Открытие дверей
            open_fee_value = get_open_price(car) if rental.rental_type == RentalType.HOURS else 0
            if open_fee_value > 0:
                record_wallet_transaction(
                    db, 
                    user=current_user, 
                    amount=-open_fee_value, 
                    ttype=WalletTransactionType.RENT_BASE_CHARGE, 
                    description="Оплата открытия дверей",
                    related_rental=rental
                )
                current_user.wallet_balance -= open_fee_value
                total_charged += open_fee_value
                rental.open_fee = open_fee_value
            
            # 3. Доставка (списываем только если еще не была списана при резервировании)
            if rental.delivery_fee and rental.delivery_fee > 0:
                # Проверяем, была ли уже создана транзакция DELIVERY_FEE для этой аренды
                existing_delivery_transaction = db.query(WalletTransaction).filter(
                    WalletTransaction.related_rental_id == rental.id,
                    WalletTransaction.transaction_type == WalletTransactionType.DELIVERY_FEE
                ).first()
                
                if not existing_delivery_transaction:
                    # Доставка еще не была списана, списываем сейчас
                    record_wallet_transaction(
                        db, 
                        user=current_user, 
                        amount=-rental.delivery_fee, 
                        ttype=WalletTransactionType.RENT_BASE_CHARGE, 
                        description="Оплата доставки",
                        related_rental=rental
                    )
                    current_user.wallet_balance -= rental.delivery_fee
                    total_charged += rental.delivery_fee
            
            if current_user.wallet_balance >= 0:
                rental.already_payed = total_charged
            else:
                rental.already_payed = 0
                
        elif rental.rental_type == RentalType.MINUTES:
            # Для минутного тарифа списываем только open_fee и delivery_fee
            open_fee_value = get_open_price(car)
            delivery_fee = rental.delivery_fee or 0
            total_cost = open_fee_value + delivery_fee
            
            if current_user.wallet_balance < total_cost:
                raise HTTPException(
                    status_code=402,
                    detail=f"Нужно минимум {total_cost} ₸ для старта. Пополните кошелёк!"
                )
            
            # Списываем ОТДЕЛЬНЫМИ транзакциями для прозрачности
            total_charged = 0
            
            # 1. Открытие дверей
            if open_fee_value > 0:
                record_wallet_transaction(
                    db, 
                    user=current_user, 
                    amount=-open_fee_value, 
                    ttype=WalletTransactionType.RENT_BASE_CHARGE, 
                    description="Оплата открытия дверей",
                    related_rental=rental
                )
                current_user.wallet_balance -= open_fee_value
                total_charged += open_fee_value
                rental.open_fee = open_fee_value
            
            # 2. Доставка (списываем только если еще не была списана при резервировании)
            if delivery_fee > 0:
                # Проверяем, была ли уже создана транзакция DELIVERY_FEE для этой аренды
                existing_delivery_transaction = db.query(WalletTransaction).filter(
                    WalletTransaction.related_rental_id == rental.id,
                    WalletTransaction.transaction_type == WalletTransactionType.DELIVERY_FEE
                ).first()
                
                if not existing_delivery_transaction:
                    # Доставка еще не была списана, списываем сейчас
                    record_wallet_transaction(
                        db, 
                        user=current_user, 
                        amount=-delivery_fee, 
                        ttype=WalletTransactionType.RENT_BASE_CHARGE, 
                        description="Оплата доставки",
                        related_rental=rental
                    )
                    current_user.wallet_balance -= delivery_fee
                    total_charged += delivery_fee
            
            if current_user.wallet_balance >= 0:
                rental.already_payed = total_charged
            else:
                rental.already_payed = 0

        # Устанавливаем start_time и статус только после всех проверок и списаний
        rental.rental_status = RentalStatus.IN_USE
        rental.start_time = get_local_time()

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
                    logger.error(f"Ошибка GPS последовательности при старте: {result.get('error', 'Unknown error')}")
        except Exception as e:
            logger.error(f"Ошибка GPS команд при старте аренды: {e}")
            # Логируем критическую ошибку GPS команды
            try:
                await log_error_to_telegram(
                    error=e,
                    request=None,
                    user=current_user,
                    additional_context={
                        "action": "start_rental_unlock_engine",
                        "car_id": car_id,
                        "car_name": car.name,
                        "gps_imei": car.gps_imei,
                        "rental_id": str(rental.id),
                        "rental_type": rental.rental_type.value,
                        "total_cost": total_cost
                    }
                )
            except:
                pass

        is_owner_rental = False

    # Отправляем уведомление в Telegram на оба бота о начале аренды
    try:
        name_parts = []
        if current_user.first_name:
            name_parts.append(current_user.first_name)
        if current_user.middle_name:
            name_parts.append(current_user.middle_name)
        if current_user.last_name:
            name_parts.append(current_user.last_name)
        full_name = " ".join(name_parts) if name_parts else "Не указано"
        
        notification_text = (
            f"Начало аренды\n\n"
            f"Клиент: {full_name}\n"
            f"Телефон: {current_user.phone_number or 'Не указан'}\n"
            f"Машина: {car.name}\n"
            f"Гос. номер: {car.plate_number or 'Не указан'}\n"
            f"ID аренды: {uuid_to_sid(rental.id)}"
        )
        
        async def _send_telegram_notification(text: str, chat_id: int, bot_token: str):
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": chat_id, "text": text}
                    )
            except Exception as e:
                logger.error(f"Ошибка отправки Telegram уведомления в {chat_id}: {e}")
        
        # Список чатов для уведомлений
        chat_ids = [965048905, 5941825713, 860991388, 1594112444, 808277096, 7656716395, 964255811, 8522837235, 797693964]
        
        if TELEGRAM_BOT_TOKEN:
            for chat_id in chat_ids:
                asyncio.create_task(_send_telegram_notification(notification_text, chat_id, TELEGRAM_BOT_TOKEN))
        
        if TELEGRAM_BOT_TOKEN_2:
            for chat_id in chat_ids:
                asyncio.create_task(_send_telegram_notification(notification_text, chat_id, TELEGRAM_BOT_TOKEN_2))
                
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления о начале аренды в Telegram: {e}")

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
    #     logger.debug(f"SMS отправлена клиенту {current_user.phone_number} при начале аренды")
    # except Exception as e:
    #     logger.error(f"Ошибка отправки SMS при начале аренды: {e}")

    # Обновляем все данные из БД для получения свежих данных
    db.expire_all()
    db.refresh(current_user)
    db.refresh(rental)
    db.refresh(car)
    if car.owner_id:
        owner = db.query(User).filter(User.id == car.owner_id).first()
        if owner:
            db.refresh(owner)
    
    # Отправляем WebSocket уведомления в самом конце, после всех операций
    try:
        await notify_user_status_update(str(current_user.id))
        if car.owner_id:
            await notify_user_status_update(str(car.owner_id))
        logger.info(f"WebSocket user_status notification sent for user {current_user.id} after starting rental")
    except Exception as e:
        logger.error(f"Error sending WebSocket notification: {e}")
    
    if is_owner_rental:
        schedule_notifications(
            user_ids=[current_user.id, car.owner_id],
            refresh_vehicles=True
        )
        return {"message": "Rental started successfully (owner rental)", "rental_id": uuid_to_sid(rental.id)}
    else:
        schedule_notifications(
            user_ids=[current_user.id, car.owner_id],
            refresh_vehicles=True
        )
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
    import time
    start_time = time.time()
    logger.info(f"[UPLOAD_PHOTOS_BEFORE] ========== START ========== user_id={current_user.id}")
    
    # Получаем rental из БД
    query_start = time.time()
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
    ).first()
    query_duration = time.time() - query_start
    logger.info(f"[UPLOAD_PHOTOS_BEFORE] DB query for rental took {query_duration:.3f}s")
    
    if not rental:
        logger.info(f"[UPLOAD_PHOTOS_BEFORE] ERROR: No active rental found for user {current_user.id}")
        raise HTTPException(status_code=404, detail="No active rental found")
    
    logger.info(f"[UPLOAD_PHOTOS_BEFORE] Found rental_id={rental.id}, status={rental.rental_status}")

    # Валидация фото
    validate_start = time.time()
    validate_photos([selfie], 'selfie')
    validate_photos(car_photos, 'car_photos')
    validate_duration = time.time() - validate_start
    logger.info(f"[UPLOAD_PHOTOS_BEFORE] Photo validation took {validate_duration:.3f}s (selfie + {len(car_photos)} car photos)")

    uploaded_files = []
    
    try:
        # 1) Сверяем селфи клиента с документом из профиля
        try:
            verify_start = time.time()
            logger.info(f"[UPLOAD_PHOTOS_BEFORE] Starting face verification...")
            is_same, msg = await run_in_threadpool(verify_user_upload_against_profile, current_user, selfie)
            verify_duration = time.time() - verify_start
            logger.info(f"[UPLOAD_PHOTOS_BEFORE] Face verification took {verify_duration:.3f}s, is_same={is_same}")
            if not is_same:
                logger.info(f"[UPLOAD_PHOTOS_BEFORE] Face verification FAILED: {msg}")
                raise HTTPException(status_code=400, detail=msg)
        except HTTPException:
            raise
        except Exception as e:
            logger.info(f"[UPLOAD_PHOTOS_BEFORE] Face verification EXCEPTION: {type(e).__name__}: {str(e)}")
            raise HTTPException(status_code=400, detail="Ой! Похоже на фотографии не вы, но если это вы, то пожалуйста сделайте селфи как в профиле.")

        # 2) Если верификация успешна — сохраняем фото
        urls = list(rental.photos_before or [])
        logger.info(f"[UPLOAD_PHOTOS_BEFORE] Current photos_before count: {len(urls)}")
        
        # save selfie
        logger.info(f"[UPLOAD_PHOTOS_BEFORE] Saving selfie...")
        save_start = time.time()
        selfie_url = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/before/selfie/")
        urls.append(selfie_url)
        uploaded_files.append(selfie_url)
        logger.info(f"[UPLOAD_PHOTOS_BEFORE] Selfie save TOTAL took {time.time() - save_start:.3f}s")
        
        # save exterior
        logger.info(f"[UPLOAD_PHOTOS_BEFORE] Saving {len(car_photos)} car photos...")
        for idx, p in enumerate(car_photos):
            photo_start = time.time()
            logger.info(f"[UPLOAD_PHOTOS_BEFORE] Saving car photo {idx+1}/{len(car_photos)}: {p.filename}")
            car_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/before/car/")
            urls.append(car_url)
            uploaded_files.append(car_url)
            logger.info(f"[UPLOAD_PHOTOS_BEFORE] Car photo {idx+1} save TOTAL took {time.time() - photo_start:.3f}s")

        rental.photos_before = urls
        logger.info(f"[UPLOAD_PHOTOS_BEFORE] Total photos_before after save: {len(urls)}")
        
        # DB commit - закрываем транзакцию перед GPS операциями, чтобы не блокировать БД
        commit_start = time.time()
        logger.info(f"[UPLOAD_PHOTOS_BEFORE] Committing DB changes...")
        db.commit()
        commit_duration = time.time() - commit_start
        logger.info(f"[UPLOAD_PHOTOS_BEFORE] DB commit took {commit_duration:.3f}s")
        
        # Получаем car из БД
        car_query_start = time.time()
        car = db.query(Car).get(rental.car_id)
        car_query_duration = time.time() - car_query_start
        logger.info(f"[UPLOAD_PHOTOS_BEFORE] Car query took {car_query_duration:.3f}s, car_id={rental.car_id}, gps_imei={car.gps_imei if car else 'None'}")
        
        if car and car.gps_imei:
            gps_start = time.time()
            logger.info(f"[UPLOAD_PHOTOS_BEFORE] Starting GPS sequence for imei={car.gps_imei}")
            
            auth_start = time.time()
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            auth_duration = time.time() - auth_start
            logger.info(f"[UPLOAD_PHOTOS_BEFORE] GPS auth took {auth_duration:.3f}s")
            
            # Универсальная последовательность: открыть замки → выдать ключ → открыть замки → забрать ключ
            sequence_start = time.time()
            logger.info(f"[UPLOAD_PHOTOS_BEFORE] Executing GPS sequence 'selfie_exterior'...")
            result = await execute_gps_sequence(car.gps_imei, auth_token, "selfie_exterior")
            sequence_duration = time.time() - sequence_start
            logger.info(f"[UPLOAD_PHOTOS_BEFORE] GPS sequence took {sequence_duration:.3f}s, success={result.get('success', False)}")
            
            if not result["success"]:
                error_msg = result.get('error', 'Unknown error')
                logger.info(f"[UPLOAD_PHOTOS_BEFORE] GPS sequence FAILED: {error_msg}")
                logger.error(f"Ошибка GPS последовательности для селфи+кузов: {error_msg}")
                raise Exception(f"GPS sequence failed: {error_msg}")
            else:
                # Логируем только краткую информацию, без детального списка команд
                logger.info(f"[UPLOAD_PHOTOS_BEFORE] GPS sequence SUCCESS for car_id={car.id}")
                logger.info(f"GPS последовательность 'selfie_exterior' успешно выполнена для авто {car.id}")
        else:
            logger.info(f"[UPLOAD_PHOTOS_BEFORE] Skipping GPS sequence (car={car is not None}, gps_imei={car.gps_imei if car else 'None'})")
        
        # Обновляем все данные из БД для получения свежих данных (после всех операций)
        refresh_start = time.time()
        logger.info(f"[UPLOAD_PHOTOS_BEFORE] Refreshing DB objects...")
        db.expire_all()
        db.refresh(rental)
        db.refresh(current_user)
        if car:
            db.refresh(car)
        if car and car.owner_id:
            owner = db.query(User).filter(User.id == car.owner_id).first()
            if owner:
                db.refresh(owner)
        refresh_duration = time.time() - refresh_start
        logger.info(f"[UPLOAD_PHOTOS_BEFORE] DB refresh took {refresh_duration:.3f}s")
        
        # Отправляем WebSocket уведомления в самом конце, после всех операций
        ws_start = time.time()
        logger.info(f"[UPLOAD_PHOTOS_BEFORE] Sending WebSocket notifications...")
        try:
            await notify_user_status_update(str(current_user.id))
            if car and car.owner_id:
                await notify_user_status_update(str(car.owner_id))
            ws_duration = time.time() - ws_start
            logger.info(f"[UPLOAD_PHOTOS_BEFORE] WebSocket notifications sent in {ws_duration:.3f}s")
            logger.info(f"WebSocket user_status notification sent for user {current_user.id} after uploading photos before")
        except Exception as e:
            ws_duration = time.time() - ws_start
            logger.info(f"[UPLOAD_PHOTOS_BEFORE] WebSocket notification ERROR after {ws_duration:.3f}s: {e}")
            logger.error(f"Error sending WebSocket notification: {e}");
        
        total_duration = time.time() - start_time
        logger.info(f"[UPLOAD_PHOTOS_BEFORE] ========== SUCCESS TOTAL: {total_duration:.3f}s ==========")
        
        return {"message": "Photos before (selfie+car) uploaded", "photo_count": len(urls)}
    except HTTPException:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "upload_photos_before",
                    "rental_id": str(rental.id) if rental else None,
                    "user_id": str(current_user.id),
                    "files_uploaded": len(uploaded_files)
                }
            )
        except:
            pass
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
    import time
    start_time = time.time()
    logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] ========== START ========== user_id={current_user.id}")
    
    # Получаем rental из БД
    query_start = time.time()
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
    ).first()
    query_duration = time.time() - query_start
    logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] DB query for rental took {query_duration:.3f}s")
    
    if not rental:
        logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] ERROR: No active rental found for user {current_user.id}")
        raise HTTPException(status_code=404, detail="No active rental found")
    
    logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] Found rental_id={rental.id}, status={rental.rental_status}")

    # Требуем, чтобы перед салоном были загружены внешние фото
    check_start = time.time()
    existing = rental.photos_before or []
    has_exterior = any(('/before/car/' in p) or ('\\before\\car\\' in p) for p in existing)
    check_duration = time.time() - check_start
    logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] Exterior check took {check_duration:.3f}s, has_exterior={has_exterior}, existing_count={len(existing)}")
    
    if not has_exterior:
        logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] ERROR: Exterior photos not found, cannot upload interior")
        raise HTTPException(status_code=400, detail="Сначала загрузите внешние фото")

    # Валидация фото
    validate_start = time.time()
    validate_photos(interior_photos, 'interior_photos')
    validate_duration = time.time() - validate_start
    logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] Photo validation took {validate_duration:.3f}s, count={len(interior_photos)}")

    uploaded_files = []
    
    try:
        urls = list(rental.photos_before or [])
        logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] Current photos_before count: {len(urls)}")
        
        # Сохранение interior фото
        logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] Saving {len(interior_photos)} interior photos...")
        for idx, p in enumerate(interior_photos):
            photo_start = time.time()
            logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] Saving interior photo {idx+1}/{len(interior_photos)}: {p.filename}")
            interior_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/before/interior/")
            urls.append(interior_url)
            uploaded_files.append(interior_url)
            logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] Interior photo {idx+1} save TOTAL took {time.time() - photo_start:.3f}s")
        
        rental.photos_before = urls
        logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] Total photos_before after save: {len(urls)}")
        
        # DB commit
        commit_start = time.time()
        logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] Committing DB changes...")
        db.commit()
        commit_duration = time.time() - commit_start
        logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] DB commit took {commit_duration:.3f}s")
        
        # Обновляем все данные из БД для получения свежих данных (после всех операций)
        refresh_start = time.time()
        logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] Refreshing DB objects...")
        db.expire_all()
        db.refresh(rental)
        db.refresh(current_user)
        car = db.query(Car).filter(Car.id == rental.car_id).first()
        if car:
            db.refresh(car)
        if car and car.owner_id:
            owner = db.query(User).filter(User.id == car.owner_id).first()
            if owner:
                db.refresh(owner)
        refresh_duration = time.time() - refresh_start
        logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] DB refresh took {refresh_duration:.3f}s")
        
        # Отправляем WebSocket уведомления в самом конце, после всех операций
        ws_start = time.time()
        logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] Sending WebSocket notifications...")
        try:
            await notify_user_status_update(str(current_user.id))
            if car and car.owner_id:
                await notify_user_status_update(str(car.owner_id))
            ws_duration = time.time() - ws_start
            logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] WebSocket notifications sent in {ws_duration:.3f}s")
            logger.info(f"WebSocket user_status notification sent for user {current_user.id} after uploading photos before interior")
        except Exception as e:
            ws_duration = time.time() - ws_start
            logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] WebSocket notification ERROR after {ws_duration:.3f}s: {e}")
            logger.error(f"Error sending WebSocket notification: {e}")
        
        total_duration = time.time() - start_time
        logger.info(f"[UPLOAD_PHOTOS_BEFORE_INTERIOR] ========== SUCCESS TOTAL: {total_duration:.3f}s ==========")
        
        return {"message": "Photos before (interior) uploaded", "photo_count": len(interior_photos)}
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "upload_photos_before_interior",
                    "rental_id": str(rental.id) if rental else None,
                    "user_id": str(current_user.id),
                    "files_uploaded": len(uploaded_files)
                }
            )
        except:
            pass
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
    vehicle_status = await check_vehicle_status_for_completion(car.gps_imei, car.plate_number)
    
    if "error" in vehicle_status:
        raise HTTPException(status_code=400, detail=vehicle_status["error"])
    
    # Проверка состояния автомобиля (включая is_ignition_on) для всех машин перед загрузкой фото (селфи + салон)
    if vehicle_status.get("errors"):
        error_message = "Перед завершением аренды:\n" + "\n".join(vehicle_status["errors"])
        raise HTTPException(status_code=400, detail=error_message)

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
        db.commit()
        # Закрываем транзакцию перед GPS операциями, чтобы не блокировать БД
        
        # После загрузки селфи+салона: заблокировать двигатель → забрать ключ → закрыть замки
        car = db.query(Car).get(rental.car_id)
        logger.info(f"[DEBUG] Car found: {car is not None}, GPS IMEI: {car.gps_imei if car else 'N/A'}")
        if car and car.gps_imei:
            logger.info(f"[DEBUG] Calling GPS sequence complete_selfie_interior for {car.gps_imei}")
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            # Универсальная последовательность: заблокировать двигатель → забрать ключ → закрыть замки
            result = await execute_gps_sequence(car.gps_imei, auth_token, "complete_selfie_interior")
            if not result["success"]:
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"Ошибка GPS последовательности для завершения селфи+салон: {error_msg}")
                raise Exception(f"GPS sequence failed: {error_msg}")
        else:
            logger.info(f"[DEBUG] Skipping GPS sequence - no car or no IMEI")
        
        # Обновляем все данные из БД для получения свежих данных (после всех операций)
        db.expire_all()
        db.refresh(rental)
        db.refresh(current_user)
        if car:
            db.refresh(car)
        if car and car.owner_id:
            owner = db.query(User).filter(User.id == car.owner_id).first()
            if owner:
                db.refresh(owner)
        
        # Отправляем WebSocket уведомления в самом конце, после всех операций
        try:
            await notify_user_status_update(str(current_user.id))
            if car and car.owner_id:
                await notify_user_status_update(str(car.owner_id))
            logger.info(f"WebSocket user_status notification sent for user {current_user.id} after uploading photos after")
        except Exception as e:
            logger.error(f"Error sending WebSocket notification: {e}")
        
        return {"message": "Photos after (selfie+interior) uploaded", "photo_count": len(interior_photos) + 1}
    except HTTPException:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "upload_photos_after",
                    "rental_id": str(rental.id) if rental else None,
                    "user_id": str(current_user.id),
                    "files_uploaded": len(uploaded_files)
                }
            )
        except:
            pass
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
        vehicle_status = await check_vehicle_status_for_completion(car.gps_imei, car.plate_number)
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
        db.commit()
        # Закрываем транзакцию перед GPS операциями, чтобы не блокировать БД
        
        # После загрузки кузова: заблокировать двигатель → забрать ключ → закрыть замки
        if car and car.gps_imei:
            
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            # Универсальная последовательность: заблокировать двигатель → забрать ключ → закрыть замки
            result = await execute_gps_sequence(car.gps_imei, auth_token, "complete_exterior")
            if not result["success"]:
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"Ошибка GPS последовательности для завершения кузова: {error_msg}")
                raise Exception(f"GPS sequence failed: {error_msg}")
        
        # Обновляем все данные из БД для получения свежих данных (после всех операций)
        db.expire_all()
        db.refresh(rental)
        db.refresh(current_user)
        if car:
            db.refresh(car)
        if car and car.owner_id:
            owner = db.query(User).filter(User.id == car.owner_id).first()
            if owner:
                db.refresh(owner)
        
        # Отправляем WebSocket уведомления в самом конце, после всех операций
        try:
            await notify_user_status_update(str(current_user.id))
            if car and car.owner_id:
                await notify_user_status_update(str(car.owner_id))
            logger.info(f"WebSocket user_status notification sent for user {current_user.id} after uploading photos after car")
        except Exception as e:
            logger.error(f"Error sending WebSocket notification: {e}")
        
        return {
            "message": "Photos after (car) uploaded successfully", 
            "photo_count": len(car_photos),
            "rental_completed": False
        }
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "upload_photos_after_car",
                    "rental_id": str(rental.id) if rental else None,
                    "user_id": str(current_user.id),
                    "files_uploaded": len(uploaded_files)
                }
            )
        except:
            pass
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
        db.commit()
        # Закрываем транзакцию перед GPS операциями, чтобы не блокировать БД
        
        # Открываем замки после успешной загрузки фото
        if car and car.gps_imei:
            try:
                auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
                if not auth_token:
                    raise Exception("Failed to get auth token")
                    
                open_result = await send_open(car.gps_imei, auth_token)
                command_id = open_result.get('command_id')
                if command_id:
                    logger.info(f"Замки успешно открыты для владельца. Command ID: {command_id}")
                else:
                    logger.warning(f"Команда отправлена, но command_id не получен")
            except Exception as gps_error:
                logger.error(f"Ошибка GPS при открытии замков: {str(gps_error)}")
                # Не прерываем процесс загрузки фото, только логируем ошибку
                try:
                    await log_error_to_telegram(
                        error=gps_error,
                        request=None,
                        user=current_user,
                        additional_context={
                            "action": "gps_open_after_owner_photos",
                            "rental_id": str(rental.id),
                            "car_id": str(car.id),
                            "gps_imei": car.gps_imei
                        }
                    )
                except:
                    pass
        
        return {"message": "Owner photos before (car) uploaded", "photo_count": len(car_photos)}
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "upload_photos_before_owner",
                    "rental_id": str(rental.id) if rental else None,
                    "user_id": str(current_user.id),
                    "files_uploaded": len(uploaded_files)
                }
            )
        except:
            pass
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
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "upload_photos_before_owner_interior",
                    "rental_id": str(rental.id) if rental else None,
                    "user_id": str(current_user.id),
                    "files_uploaded": len(uploaded_files)
                }
            )
        except:
            pass
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
    vehicle_status = await check_vehicle_status_for_completion(car.gps_imei, car.plate_number)
    
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
        db.commit()
        # Закрываем транзакцию перед GPS операциями, чтобы не блокировать БД
        
        # После загрузки салона владельцем: заблокировать двигатель → забрать ключ → закрыть замки
        car = db.query(Car).get(rental.car_id)
        if car and car.gps_imei:
            
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            # Универсальная последовательность: заблокировать двигатель → забрать ключ → закрыть замки
            result = await execute_gps_sequence(car.gps_imei, auth_token, "complete_selfie_interior")
            if not result["success"]:
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"Ошибка GPS последовательности для завершения салона владельцем: {error_msg}")
                raise Exception(f"GPS sequence failed: {error_msg}")
        
        return {"message": "Owner photos after (interior) uploaded", "photo_count": len(interior_photos)}
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "upload_photos_after_owner_interior",
                    "rental_id": str(rental.id) if rental else None,
                    "user_id": str(current_user.id),
                    "files_uploaded": len(uploaded_files)
                }
            )
        except:
            pass
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
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "upload_photos_after_owner_car",
                    "rental_id": str(rental.id) if rental else None,
                    "user_id": str(current_user.id),
                    "files_uploaded": len(uploaded_files)
                }
            )
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Error uploading owner photos after (car): {str(e)}")


class RentalReviewInput(BaseModel):
    rating: conint(ge=1, le=5) = Field(..., description="Оценка от 1 до 5")
    comment: Optional[constr(max_length=255)] = Field(None, description="Комментарий к аренде (до 255 символов)")


async def check_vehicle_status_for_completion(vehicle_imei: str, plate_number: Optional[str] = None) -> Dict[str, Any]:
    """
    Проверяет состояние автомобиля для завершения аренды.
    Возвращает ошибки если автомобиль не готов к завершению аренды.
    """
    try:
        from app.core.config import VEHICLES_API_URL
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{VEHICLES_API_URL}/vehicles/?skip=0&limit=100")
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
            
            # Проверка зажигания (двигатель должен быть заглушен)
            if vehicle.get("is_ignition_on", False):
                errors.append("Для завершения аренды пожалуйста выключите зажигание (заглушите двигатель)")

            # Проверка багажника
            if vehicle.get("is_trunk_open", False):
                errors.append("Для завершения аренды пожалуйста закройте багажник")
            
            # Проверка дверей
            # Пропускаем проверку для G63 и Range Rover, а также для F980802 (временно игнорируем статус замков)
            skip_door_check = (
                vehicle_imei in ["860803068155890", "800298270", "860803068151105"] or
                plate_number == "F980802"
            )
            if not skip_door_check:
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
            # Пропускаем проверку для Hongqi e-qm5 (IMEI: 860803068139548)
            if vehicle_imei != "860803068139548":
                if vehicle.get("are_lights_on", False) and not vehicle.get("is_light_auto_mode_on", False):
                    errors.append("Для завершения аренды пожалуйста выключите фары или переведите в режим AUTO")
            
            return {"errors": errors, "vehicle": vehicle}
            
    except Exception as e:
        return {"error": f"Ошибка при проверке состояния автомобиля: {str(e)}"}


@RentRouter.post("/extend", response_model=ExtendRentalResponse)
async def extend_rental(
        request: ExtendRentalRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Продление суточного тарифа аренды.
    
    Доступно только для аренд типа DAYS со статусом IN_USE.
    Можно продлить только после окончания основного тарифа (когда начался поминутный тариф).
    """
    from math import ceil
    
    validate_user_can_rent(current_user, db)
    
    rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == current_user.id,
        RentalHistory.rental_status == RentalStatus.IN_USE
    ).first()
    
    if not rental:
        raise HTTPException(
            status_code=404,
            detail="Активная аренда не найдена"
        )
    
    if rental.rental_type != RentalType.DAYS:
        raise HTTPException(
            status_code=400,
            detail="Продление доступно только для суточного тарифа"
        )
    
    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    if car.status != CarStatus.IN_USE:
        raise HTTPException(
            status_code=400,
            detail="Автомобиль недоступен для продления аренды"
        )
    
    if not rental.start_time:
        raise HTTPException(
            status_code=400,
            detail="Аренда еще не началась"
        )
    
    now = get_local_time()
    elapsed = (now - rental.start_time).total_seconds() / 60 
    planned_minutes = rental.duration * 1440  
    
    remaining_minutes = planned_minutes - elapsed
    if elapsed < planned_minutes - 120:
        raise HTTPException(
            status_code=400,
            detail=f"Продление доступно только когда осталось менее 2 часов до окончания тарифа или после его окончания. Осталось: {ceil(remaining_minutes / 60)} часов"
        )
    
    total_duration = rental.duration + request.days
    extension_cost = calculate_total_price(
        rental_type=RentalType.DAYS,
        duration=request.days,
        price_per_hour=0, 
        price_per_day=car.price_per_day
    )
    
    if current_user.wallet_balance < extension_cost:
        raise HTTPException(
            status_code=402,
            detail=f"Недостаточно средств для продления. Требуется: {extension_cost} ₸, доступно: {int(current_user.wallet_balance)} ₸"
        )
    
    balance_before = float(current_user.wallet_balance)
    current_user.wallet_balance = balance_before - extension_cost
    
    # Обновляем время последней активности пользователя
    current_user.last_activity_at = get_local_time()
    
    try:
        record_wallet_transaction(
            db,
            user=current_user,
            amount=-extension_cost,
            ttype=WalletTransactionType.RENT_BASE_CHARGE,
            description=f"Продление аренды на {request.days} {'день' if request.days == 1 else 'дня' if request.days < 5 else 'дней'}",
            related_rental=rental
        )
        
        old_duration = rental.duration
        old_base_price = rental.base_price or 0
        
        rental.duration = total_duration
        rental.base_price = old_base_price + extension_cost
        
        if current_user.wallet_balance >= 0:
            rental.already_payed = (
                (rental.base_price or 0) +
                (rental.open_fee or 0) +
                (rental.delivery_fee or 0) +
                (rental.waiting_fee or 0) +
                (rental.overtime_fee or 0)
            )
        
        rental.total_price = (
            (rental.base_price or 0) +
            (rental.open_fee or 0) +
            (rental.delivery_fee or 0) +
            (rental.waiting_fee or 0) +
            (rental.overtime_fee or 0) +
            (rental.distance_fee or 0)
        )
        
        db.commit()
    except Exception as e:
        db.rollback()
        # Откатываем изменение баланса
        current_user.wallet_balance = balance_before
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при продлении аренды: {str(e)}"
        )
    
    try:
        user_locale = current_user.locale or "ru"
        
        if user_locale == "ru":
            days_text = "день" if request.days == 1 else "дня" if request.days < 5 else "дней"
            days_text2 = "день" if total_duration == 1 else "дня" if total_duration < 5 else "дней"
        elif user_locale == "en":
            days_text = "day" if request.days == 1 else "days"
            days_text2 = "day" if total_duration == 1 else "days"
        elif user_locale == "kz":
            days_text = "күн"
            days_text2 = "күн"
        elif user_locale == "zh":
            days_text = "天"
            days_text2 = "天"
        else:
            days_text = "день" if request.days == 1 else "дня" if request.days < 5 else "дней"
            days_text2 = "день" if total_duration == 1 else "дня" if total_duration < 5 else "дней"
        
        asyncio.create_task(
            send_localized_notification_to_user_async(
                current_user.id,
                "rental_extended",
                "rental_extended",
                days=request.days,
                days_text=days_text,
                new_duration=total_duration,
                days_text2=days_text2,
                cost=extension_cost
            )
        )
    except Exception:
        pass
    
    try:
        loop = asyncio.get_running_loop()
        asyncio.create_task(notify_user_status_update(str(current_user.id)))
    except RuntimeError:
        pass
    
    return ExtendRentalResponse(
        message=f"Аренда успешно продлена на {request.days} {'день' if request.days == 1 else 'дня' if request.days < 5 else 'дней'}",
        rental_id=uuid_to_sid(rental.id),
        new_duration=total_duration,
        extension_cost=extension_cost,
        new_base_price=rental.base_price,
        remaining_balance=float(current_user.wallet_balance)
    )


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
    vehicle_status = await check_vehicle_status_for_completion(car.gps_imei, car.plate_number)
    
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
    now = get_local_time()
    rental.end_time = now
    rental.end_latitude = car.latitude
    rental.end_longitude = car.longitude

    # Для часового/суточного тарифа: сохраняем уровень топлива на момент окончания основного тарифа
    # если аренда вышла за пределы основного тарифа
    if rental.rental_type in (RentalType.HOURS, RentalType.DAYS):
        # Рассчитываем запланированное время в минутах
        planned_minutes = (
            rental.duration * 60
            if rental.rental_type == RentalType.HOURS
            else rental.duration * 24 * 60
        )
        # Рассчитываем фактическое время
        total_seconds_temp = (now - rental.start_time).total_seconds()
        actual_minutes_temp = total_seconds_temp / 60
        
        if actual_minutes_temp > planned_minutes:
            # Аренда вышла за пределы основного тарифа
            # Сохраняем уровень топлива на момент окончания основного тарифа
            # (это значение должно было быть установлено ранее, если нет - используем текущий)
            if not hasattr(rental, 'fuel_after_main_tariff') or rental.fuel_after_main_tariff is None:
                rental.fuel_after_main_tariff = car.fuel_level
        else:
            # Аренда завершилась в пределах основного тарифа
            if rental.fuel_after is None:
                rental.fuel_after = car.fuel_level
    else:
        # Для поминутного тарифа просто сохраняем текущий уровень
        if rental.fuel_after is None:
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
    
    # Сохраняем оригинальное значение duration (часы/дни) до перезаписи
    original_duration = rental.duration

    # 7) Базовая плата по типу аренды
    if rental.rental_type == RentalType.MINUTES:
        # Поминутный тариф: считаем по фактическому времени
        rental.base_price = rounded_minutes * car.price_per_minute
    elif rental.rental_type == RentalType.HOURS:
        # Часовой тариф: базовая плата по заказанному количеству часов
        rental.base_price = original_duration * car.price_per_hour
    else:  # DAYS
        # Суточный тариф: базовая плата по заказанному количеству дней
        rental.base_price = original_duration * car.price_per_day

    # 8) Переработка (сверхтариф) для часов/дней
    if rental.rental_type in (RentalType.HOURS, RentalType.DAYS):
        planned_minutes = (
            original_duration * 60
            if rental.rental_type == RentalType.HOURS
            else original_duration * 24 * 60
        )
        overtime_mins = max(0, rounded_minutes - planned_minutes)
        rental.overtime_fee = overtime_mins * car.price_per_minute
    else:
        rental.overtime_fee = 0

    # 9) Расчет платного ожидания (waiting_fee)
    # Платное ожидание рассчитывается на основе времени между reservation_time и start_time
    # Первые 15 минут бесплатные, далее за каждую минуту: price_per_minute * 0.5
    waiting_fee = 0
    waiting_minutes = 0
    extra_minutes = 0
    
    if rental.reservation_time and rental.start_time:
        waiting_seconds = (rental.start_time - rental.reservation_time).total_seconds()
        waiting_minutes = waiting_seconds / 60
        
        if waiting_minutes > 15:
            # Платное ожидание: минуты сверх 15 минут
            extra_minutes = ceil(waiting_minutes - 15)
            waiting_fee = int(extra_minutes * car.price_per_minute * 0.5)
    
    # Проверяем, была ли уже создана транзакция для waiting_fee
    existing_waiting_tx = db.query(WalletTransaction).filter(
        WalletTransaction.related_rental_id == rental.id,
        WalletTransaction.transaction_type == WalletTransactionType.RENT_WAITING_FEE
    ).first()
    
    if waiting_fee > 0:
        # Нужно обновить или создать транзакцию
        if existing_waiting_tx:
            # Обновляем существующую транзакцию
            already_charged = float(abs(existing_waiting_tx.amount)) if existing_waiting_tx.amount else 0
            difference = waiting_fee - already_charged
            
            if abs(difference) > 0.01:  # Есть разница
                if difference > 0:
                    # Нужно доплатить - разрешаем списание даже при отрицательном балансе
                    balance_before = float(current_user.wallet_balance)
                    current_user.wallet_balance -= Decimal(str(difference))
                    
                    existing_waiting_tx.amount = -waiting_fee
                    existing_waiting_tx.description = f"Платное ожидание {int(extra_minutes)} мин"
                    existing_waiting_tx.balance_before = balance_before
                    existing_waiting_tx.balance_after = float(current_user.wallet_balance)
                else:
                    # Переплата - возвращаем разницу (в теории не должно быть, но на всякий случай)
                    refund = abs(difference)
                    balance_before = float(current_user.wallet_balance)
                    current_user.wallet_balance += Decimal(str(refund))
                    
                    existing_waiting_tx.amount = -waiting_fee
                    existing_waiting_tx.description = f"Платное ожидание {int(extra_minutes)} мин (перерасчёт)"
                    existing_waiting_tx.balance_before = balance_before
                    existing_waiting_tx.balance_after = float(current_user.wallet_balance)
        else:
            # Создаём новую транзакцию - разрешаем списание даже при отрицательном балансе
            balance_before = float(current_user.wallet_balance)
            current_user.wallet_balance -= Decimal(str(waiting_fee))
            
            waiting_tx = WalletTransaction(
                user_id=current_user.id,
                amount=-waiting_fee,
                transaction_type=WalletTransactionType.RENT_WAITING_FEE,
                description=f"Платное ожидание {int(extra_minutes)} мин",
                balance_before=balance_before,
                balance_after=float(current_user.wallet_balance),
                related_rental_id=rental.id,
                created_at=get_local_time()
            )
            db.add(waiting_tx)
    
    rental.waiting_fee = waiting_fee

    # 10) Убедиться, что все остальные сборы не None
    rental.open_fee = rental.open_fee or 0
    rental.delivery_fee = rental.delivery_fee or 0
    rental.distance_fee = rental.distance_fee or 0

    # 10) Расчет топлива
    fuel_fee = 0
    fuel_consumed = 0
    
    if rental.rental_type == RentalType.MINUTES:
        # Поминутный тариф: бензин НЕ считаем
        fuel_fee = 0
    elif rental.rental_type in (RentalType.HOURS, RentalType.DAYS):
        # Часовой/суточный тариф: бензин считаем ТОЛЬКО после основного тарифа
        existing_fuel_tx = db.query(WalletTransaction).filter(
            WalletTransaction.related_rental_id == rental.id,
            WalletTransaction.transaction_type == WalletTransactionType.RENT_FUEL_FEE
        ).first()
        
        if existing_fuel_tx:
            # Топливо уже было списано ранее
            fuel_fee = float(abs(existing_fuel_tx.amount)) if existing_fuel_tx.amount else 0
        else:
            # Рассчитываем топливо только после основного тарифа
            # Топливо считается только за период основного тарифа, не за овертайм
            planned_minutes = (
                original_duration * 60
                if rental.rental_type == RentalType.HOURS
                else original_duration * 24 * 60
            )
            
            if rounded_minutes > planned_minutes:
                # Аренда вышла за пределы основного тарифа
                # Топливо считаем только за период основного тарифа (до fuel_after_main_tariff)
                fuel_after_main = rental.fuel_after_main_tariff if hasattr(rental, 'fuel_after_main_tariff') and rental.fuel_after_main_tariff is not None else None
                
                if fuel_after_main is None:
                    # Если fuel_after_main_tariff не был установлен, используем текущий уровень
                    # (это может произойти, если аренда только что завершилась)
                    fuel_after_main = car.fuel_level
                
                if rental.fuel_before is not None and fuel_after_main is not None:
                    if fuel_after_main < rental.fuel_before:
                        fuel_before_rounded = ceil(rental.fuel_before)
                        fuel_after_rounded = floor(fuel_after_main)
                        fuel_consumed = fuel_before_rounded - fuel_after_rounded
                        if fuel_consumed > 0:
                            if car.body_type == CarBodyType.ELECTRIC:
                                price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
                            else:
                                price_per_liter = FUEL_PRICE_PER_LITER
                            fuel_fee = int(fuel_consumed * price_per_liter)
                            
                            # Разрешаем списание даже при отрицательном балансе
                            balance_before_fuel = float(current_user.wallet_balance)
                            current_user.wallet_balance -= Decimal(str(fuel_fee))
                            tx = WalletTransaction(
                                user_id=current_user.id,
                                amount=-fuel_fee,
                                transaction_type=WalletTransactionType.RENT_FUEL_FEE,
                                description=f"Оплата топлива: {int(fuel_consumed)} л × {price_per_liter}₸ = {fuel_fee:,}₸" if car.body_type != CarBodyType.ELECTRIC else f"Оплата заряда: {int(fuel_consumed)}% × {price_per_liter}₸ = {fuel_fee:,}₸",
                                balance_before=balance_before_fuel,
                                balance_after=float(current_user.wallet_balance),
                                related_rental_id=rental.id,
                                created_at=get_local_time()
                            )
                            db.add(tx)
            else:
                # Аренда завершилась в пределах основного тарифа
                # Топливо считаем по разнице fuel_before и fuel_after
                if rental.fuel_before is not None and rental.fuel_after is not None:
                    if rental.fuel_after < rental.fuel_before:
                        fuel_before_rounded = ceil(rental.fuel_before)
                        fuel_after_rounded = floor(rental.fuel_after)
                        fuel_consumed = fuel_before_rounded - fuel_after_rounded
                        if fuel_consumed > 0:
                            if car.body_type == CarBodyType.ELECTRIC:
                                price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
                            else:
                                price_per_liter = FUEL_PRICE_PER_LITER
                            fuel_fee = int(fuel_consumed * price_per_liter)
                            
                            # Разрешаем списание даже при отрицательном балансе
                            balance_before_fuel = float(current_user.wallet_balance)
                            current_user.wallet_balance -= Decimal(str(fuel_fee))
                            tx = WalletTransaction(
                                user_id=current_user.id,
                                amount=-fuel_fee,
                                transaction_type=WalletTransactionType.RENT_FUEL_FEE,
                                description=f"Оплата топлива: {int(fuel_consumed)} л × {price_per_liter}₸ = {fuel_fee:,}₸" if car.body_type != CarBodyType.ELECTRIC else f"Оплата заряда: {int(fuel_consumed)}% × {price_per_liter}₸ = {fuel_fee:,}₸",
                                balance_before=balance_before_fuel,
                                balance_after=float(current_user.wallet_balance),
                                related_rental_id=rental.id,
                                created_at=get_local_time()
                            )
                            db.add(tx)

    if car.owner_id == current_user.id:
        rental.base_price = 0
        rental.open_fee = 0
        rental.waiting_fee = 0
        rental.overtime_fee = 0
        rental.distance_fee = 0
        rental.total_price = fuel_fee
        rental.already_payed = 0
    else:
        total_price_without_fuel = (
            (rental.base_price or 0)
            + (rental.open_fee or 0)
            + (rental.delivery_fee or 0)
            + (rental.waiting_fee or 0)
            + (rental.overtime_fee or 0)
            + (rental.distance_fee or 0)
        )
        rental.total_price = total_price_without_fuel + fuel_fee
        
        if current_user.wallet_balance >= 0:
            if rental.rental_type in [RentalType.HOURS, RentalType.DAYS]:
                rental.already_payed = (
                    (rental.base_price or 0) +
                    (rental.open_fee or 0) +
                    (rental.delivery_fee or 0) +
                    (rental.waiting_fee or 0) +
                    (rental.overtime_fee or 0) +
                    fuel_fee
                )
            elif rental.rental_type == RentalType.MINUTES:
                # Для поминутного тарифа: base_price уже включает все поминутные списания
                rental.already_payed = (
                    (rental.base_price or 0) +
                    (rental.open_fee or 0) +
                    (rental.delivery_fee or 0) +
                    (rental.waiting_fee or 0) +
                    (rental.distance_fee or 0) +
                    (rental.driver_fee or 0)
                )
            else:
                rental.already_payed = 0
        else:
            if rental.already_payed is None:
                rental.already_payed = 0

    # 12) Рассчитываем и сохраняем фактическую продолжительность поездки в минутах для истории
    rental.duration = rounded_minutes
    
    # 13) Окончательная блокировка двигателя при завершении аренды
    try:
        auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        
        # Универсальная последовательность: заблокировать двигатель
        result = await execute_gps_sequence(car.gps_imei, auth_token, "final_lock")
        if result["success"]:
            logger.info(f"Двигатель автомобиля {car.name} окончательно заблокирован после завершения аренды")
        else:
            logger.error(f"Ошибка GPS последовательности при окончательной блокировке: {result.get('error', 'Unknown error')}")
    except Exception as e:
        logger.error(f"Ошибка блокировки двигателя: {e}")
        # Логируем критическую ошибку GPS команды
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "complete_rental_lock_engine",
                    "car_id": str(car.id),
                    "car_name": car.name,
                    "gps_imei": car.gps_imei,
                    "rental_id": str(rental.id),
                    "rental_type": rental.rental_type.value,
                    "total_price": rental.total_price,
                    "duration_minutes": rounded_minutes
                }
            )
        except:
            pass

    # 14) Получаем рейтинг вождения из Glonasssoft API
    try:
        if car.gps_id and rental.start_time:
            if rental.end_time is None:
                logger.warning(f"rental.end_time is None, using current time for EcoDriving rating request")
                rating_end_time = now
            else:
                rating_end_time = rental.end_time
            
            eco_rating = await get_ecodriving_rating(
                vehicle_id=car.gps_id,
                start_time=rental.start_time,
                end_time=rating_end_time
            )
            if eco_rating is not None:
                rental.rating = eco_rating
                logger.info(f"EcoDriving rating {eco_rating} saved for rental {rental.id}")
            else:
                logger.warning(f"Failed to get EcoDriving rating for rental {rental.id}")
        else:
            logger.warning(f"Cannot get EcoDriving rating: gps_id={car.gps_id}, start_time={rental.start_time}")
    except Exception as e:
        logger.error(f"Error getting EcoDriving rating: {e}", exc_info=True)

    # ========== ФИНАЛЬНЫЙ ПЕРЕРАСЧЁТ АРЕНДЫ ==========
    # Выполняем контрольный перерасчёт и сверяем суммы между:
    # 1) Аренда (rental.base_price, rental.overtime_fee)
    # 2) Транзакции (WalletTransaction)
    # 3) Баланс пользователя
    
    if not (car.owner_id == current_user.id):  # Для владельца автомобиля перерасчёт не нужен
        if rental.rental_type == RentalType.MINUTES:
            # ========== ПОМИНУТНЫЙ ТАРИФ ==========
            # 1) Рассчитать правильную итоговую стоимость по формуле: минуты × цена_за_минуту
            expected_total_cost = rounded_minutes * car.price_per_minute
            
            # 2) Найти транзакцию поминутного списания
            minute_charge_tx = db.query(WalletTransaction).filter(
                WalletTransaction.related_rental_id == rental.id,
                WalletTransaction.transaction_type == WalletTransactionType.RENT_MINUTE_CHARGE
            ).order_by(WalletTransaction.created_at.desc()).first()
            
            # 3) Сверить суммы
            actual_charged = float(abs(minute_charge_tx.amount)) if minute_charge_tx and minute_charge_tx.amount else 0
            
            # 4) Проверяем, нужен ли перерасчёт
            if abs(actual_charged - expected_total_cost) > 0.01 or minute_charge_tx is None:  # Допускаем погрешность в 1 копейку
                # НЕСОВПАДЕНИЕ или транзакция отсутствует! Выполняем перерасчёт
                difference = expected_total_cost - actual_charged
                
                if difference != 0:
                    logger.info(
                        f"🔄 Финальный перерасчёт поминутной аренды {rental.id}: "
                        f"ожидалось {expected_total_cost}₸, списано {actual_charged}₸, "
                        f"разница {difference}₸"
                    )
                
                # Откорректировать транзакцию
                if minute_charge_tx:
                    # Обновляем существующую транзакцию
                    # Возвращаем старую сумму в баланс
                    balance_before_correction = float(current_user.wallet_balance or 0) + float(abs(minute_charge_tx.amount) if minute_charge_tx.amount else 0)
                    
                    # Разрешаем списание даже при отрицательном балансе
                    current_user.wallet_balance = Decimal(str(balance_before_correction - expected_total_cost))
                    
                    minute_charge_tx.amount = -expected_total_cost
                    minute_charge_tx.description = f"Поминутное списание {rounded_minutes} мин"
                    minute_charge_tx.balance_before = balance_before_correction
                    minute_charge_tx.balance_after = float(current_user.wallet_balance)
                else:
                    # Создаём новую транзакцию, если её не было
                    balance_before_correction = float(current_user.wallet_balance)
                    
                    # Разрешаем списание даже при отрицательном балансе
                    current_user.wallet_balance -= Decimal(str(expected_total_cost))
                    
                    minute_charge_tx = WalletTransaction(
                        user_id=current_user.id,
                        amount=-expected_total_cost,
                        transaction_type=WalletTransactionType.RENT_MINUTE_CHARGE,
                        description=f"Поминутное списание {rounded_minutes} мин",
                        balance_before=balance_before_correction,
                        balance_after=float(current_user.wallet_balance),
                        related_rental_id=rental.id,
                        created_at=get_local_time()
                    )
                    db.add(minute_charge_tx)
                
                # Обновить аренду
                if expected_total_cost > 0:
                    rental.base_price = expected_total_cost
                rental.overtime_fee = 0  # Для поминутного тарифа овертайм не применяется
                
                # Пересчитать total_price и already_payed
                rental.total_price = (
                    rental.base_price +
                    (rental.open_fee or 0) +
                    (rental.delivery_fee or 0) +
                    (rental.waiting_fee or 0) +
                    (rental.distance_fee or 0) +
                    (rental.driver_fee or 0)
                )
                
                if current_user.wallet_balance >= 0:
                    rental.already_payed = (
                        (rental.open_fee or 0) +
                        (rental.delivery_fee or 0) +
                        (rental.waiting_fee or 0) +
                        rental.base_price
                    )
                
                logger.info(
                    f"✅ Перерасчёт поминутной аренды завершён: base_price={rental.base_price}₸, "
                    f"total_price={rental.total_price}₸, баланс={current_user.wallet_balance}₸"
                )
        
        elif rental.rental_type in (RentalType.HOURS, RentalType.DAYS):
            # ========== ЧАСОВОЙ/ДНЕВНОЙ ТАРИФ С ОВЕРТАЙМОМ ==========
            # Проверяем, вышла ли аренда за пределы основного тарифа
            # Используем оригинальное значение duration (количество часов/дней из бронирования)
            planned_minutes = (
                original_duration * 60 if rental.rental_type == RentalType.HOURS
                else original_duration * 24 * 60
            )
            
            # Проверка base_price: сравниваем рассчитанное значение с суммой в транзакции
            expected_base_price = rental.base_price  # Уже рассчитан выше
            
            # Ищем транзакцию с base_price (может быть несколько транзакций RENT_BASE_CHARGE)
            # Проверяем описание, чтобы найти именно транзакцию за аренду, а не за открытие дверей или доставку
            base_charge_tx = None
            actual_base_charged = 0
            
            for tx in db.query(WalletTransaction).filter(
                WalletTransaction.related_rental_id == rental.id,
                WalletTransaction.transaction_type == WalletTransactionType.RENT_BASE_CHARGE
            ).all():
                desc = tx.description or ""
                # Транзакция base_price содержит "Оплата аренды" и количество часов/дней
                if "оплат" in desc.lower() and "аренд" in desc.lower() and ("час" in desc.lower() or "день" in desc.lower()):
                    actual_base_charged = float(abs(tx.amount)) if tx.amount else 0
                    base_charge_tx = tx
                    break
            
            # Если есть несовпадение или транзакция отсутствует (но base_price должен быть), исправляем
            # Для владельца base_price = 0, так что проверку не делаем
            if expected_base_price > 0 and abs(actual_base_charged - expected_base_price) > 0.01:
                difference = expected_base_price - actual_base_charged
                
                if base_charge_tx:
                    logger.warning(
                        f"⚠️ Финальный перерасчёт base_price аренды {rental.id}: "
                        f"ожидалось {expected_base_price}₸, списано {actual_base_charged}₸, "
                        f"разница {difference}₸"
                    )
                else:
                    logger.warning(
                        f"⚠️ Транзакция base_price не найдена для аренды {rental.id}, "
                        f"но ожидается {expected_base_price}₸. Создаём транзакцию."
                    )
                
                if base_charge_tx:
                    # Обновляем существующую транзакцию
                    balance_before_correction = float(current_user.wallet_balance or 0) + float(abs(base_charge_tx.amount) if base_charge_tx.amount else 0)
                    
                    # Разрешаем списание даже при отрицательном балансе
                    current_user.wallet_balance = Decimal(str(balance_before_correction - expected_base_price))
                    
                    base_charge_tx.amount = -expected_base_price
                    base_charge_tx.description = f"Оплата аренды: {original_duration} {'час(ов)' if rental.rental_type == RentalType.HOURS else 'день(дней)'} (перерасчёт)"
                    base_charge_tx.balance_before = balance_before_correction
                    base_charge_tx.balance_after = float(current_user.wallet_balance)
                else:
                    # Создаём новую транзакцию, если её не было
                    balance_before_correction = float(current_user.wallet_balance)
                    
                    # Разрешаем списание даже при отрицательном балансе
                    current_user.wallet_balance -= Decimal(str(expected_base_price))
                    
                    base_charge_tx = WalletTransaction(
                        user_id=current_user.id,
                        amount=-expected_base_price,
                        transaction_type=WalletTransactionType.RENT_BASE_CHARGE,
                        description=f"Оплата аренды: {original_duration} {'час(ов)' if rental.rental_type == RentalType.HOURS else 'день(дней)'}",
                        balance_before=balance_before_correction,
                        balance_after=float(current_user.wallet_balance),
                        related_rental_id=rental.id,
                        created_at=get_local_time()
                    )
                    db.add(base_charge_tx)
                
                # Обновляем base_price в аренде
                rental.base_price = expected_base_price
                
                # Пересчитываем total_price и already_payed
                rental.total_price = (
                    (rental.base_price or 0) +
                    (rental.open_fee or 0) +
                    (rental.delivery_fee or 0) +
                    (rental.waiting_fee or 0) +
                    (rental.overtime_fee or 0) +
                    (rental.distance_fee or 0) +
                    (rental.driver_fee or 0) +
                    fuel_fee
                )
                
                if current_user.wallet_balance >= 0:
                    rental.already_payed = (
                        (rental.base_price or 0) +
                        (rental.open_fee or 0) +
                        (rental.delivery_fee or 0) +
                        (rental.waiting_fee or 0) +
                        (rental.overtime_fee or 0) +
                        fuel_fee
                    )
                
                logger.info(
                    f"✅ Перерасчёт base_price завершён: base_price={rental.base_price}₸, "
                    f"total_price={rental.total_price}₸, баланс={current_user.wallet_balance}₸"
                )
            
            if rounded_minutes > planned_minutes:
                # Есть овертайм - нужен перерасчёт
                expected_overtime_minutes = int(rounded_minutes - planned_minutes)
                expected_overtime_cost = expected_overtime_minutes * car.price_per_minute
                
                # Найти транзакцию овертайма
                overtime_tx = db.query(WalletTransaction).filter(
                    WalletTransaction.related_rental_id == rental.id,
                    WalletTransaction.transaction_type == WalletTransactionType.RENT_OVERTIME_FEE
                ).order_by(WalletTransaction.created_at.desc()).first()
                
                # Сверить суммы
                actual_overtime_charged = float(abs(overtime_tx.amount)) if overtime_tx and overtime_tx.amount else 0
                
                if abs(actual_overtime_charged - expected_overtime_cost) > 0.01:
                    # НЕСОВПАДЕНИЕ! Выполняем перерасчёт
                    difference = expected_overtime_cost - actual_overtime_charged
                    
                    logger.warning(
                        f"⚠️ Финальный перерасчёт овертайма аренды {rental.id}: "
                        f"ожидалось {expected_overtime_cost}₸, списано {actual_overtime_charged}₸, "
                        f"разница {difference}₸"
                    )
                    
                    # Откорректировать транзакцию - разрешаем списание даже при отрицательном балансе
                    if overtime_tx:
                        balance_before_correction = float(current_user.wallet_balance or 0) + float(overtime_tx.amount if overtime_tx.amount else 0)
                        current_user.wallet_balance = Decimal(str(balance_before_correction - expected_overtime_cost))
                        
                        overtime_tx.amount = -expected_overtime_cost
                        overtime_tx.description = f"Сверхтариф {expected_overtime_minutes} мин (перерасчёт)"
                        overtime_tx.balance_before = balance_before_correction
                        overtime_tx.balance_after = float(current_user.wallet_balance or 0)
                    else:
                        balance_before_correction = float(current_user.wallet_balance or 0)
                        current_user.wallet_balance -= Decimal(str(expected_overtime_cost))
                        
                        overtime_tx = WalletTransaction(
                            user_id=current_user.id,
                            amount=-expected_overtime_cost,
                            transaction_type=WalletTransactionType.RENT_OVERTIME_FEE,
                            description=f"Сверхтариф {expected_overtime_minutes} мин",
                            balance_before=balance_before_correction,
                            balance_after=float(current_user.wallet_balance),
                            related_rental_id=rental.id,
                            created_at=get_local_time()
                        )
                        db.add(overtime_tx)
                    
                    # Обновить аренду
                    rental.overtime_fee = expected_overtime_cost
                    
                    # Пересчитать total_price и already_payed
                    rental.total_price = (
                        (rental.base_price or 0) +
                        (rental.open_fee or 0) +
                        (rental.delivery_fee or 0) +
                        (rental.waiting_fee or 0) +
                        rental.overtime_fee +
                        (rental.distance_fee or 0) +
                        (rental.driver_fee or 0) +
                        fuel_fee
                    )
                    
                    if current_user.wallet_balance >= 0:
                        rental.already_payed = (
                            (rental.base_price or 0) +
                            (rental.open_fee or 0) +
                            (rental.delivery_fee or 0) +
                            (rental.waiting_fee or 0) +
                            rental.overtime_fee +
                            fuel_fee
                        )
                    
                    logger.info(
                        f"✅ Перерасчёт овертайма завершён: overtime_fee={rental.overtime_fee}₸, "
                        f"total_price={rental.total_price}₸, баланс={current_user.wallet_balance}₸"
                    )
    
    # ========== КОНЕЦ ПЕРЕРАСЧЁТА ==========

    # ========== ВЕРИФИКАЦИЯ И ИСПРАВЛЕНИЕ БАЛАНСА ==========
    # Пересчитываем все транзакции ДО аренды, получаем правильный баланс,
    # собираем суммы из транзакций, синхронизируем поля аренды и исправляем баланс
    if not (car.owner_id == current_user.id):  # Для владельца не нужно
        try:
            verification_result = verify_and_fix_rental_balance(
                user=current_user,
                rental=rental,
                car=car,
                db=db
            )
            
            if verification_result.get("corrected"):
                logger.info(
                    f"🔧 Verification applied for user {current_user.id} after rental {rental.id}: "
                    f"balance_before_rental={verification_result.get('balance_before_rental')}, "
                    f"old_balance={verification_result.get('old_balance')}, "
                    f"new_balance={verification_result.get('new_balance')}, "
                    f"diff={verification_result.get('difference')}, "
                    f"rental_fields_updated={verification_result.get('rental_fields_updated')}, "
                    f"tx_corrections={verification_result.get('tx_corrections_count')}"
                )
            elif verification_result.get("success"):
                logger.info(
                    f"✅ Balance verified for user {current_user.id}: "
                    f"balance_before_rental={verification_result.get('balance_before_rental')}, "
                    f"expected_after={verification_result.get('expected_balance_after')}, "
                    f"tx_sums={verification_result.get('tx_sums')}"
                )
            else:
                logger.warning(
                    f"⚠️ Balance verification failed for user {current_user.id}: "
                    f"{verification_result.get('error')}"
                )
        except Exception as e:
            logger.error(f"Error during balance verification: {e}", exc_info=True)
    # ========== КОНЕЦ ВЕРИФИКАЦИИ БАЛАНСА ==========

    db.commit()
    
    try:
        update_user_rating(current_user.id, db)
        db.commit()
    except Exception as e:
        logger.error(f"Error updating user rating: {e}", exc_info=True)
    try:
        await send_localized_notification_to_all_mechanics(
            db,
            "new_car_for_inspection",
            "new_car_for_inspection",
            car_name=car.name,
            plate_number=car.plate_number
        )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления механикам: {e}", exc_info=True)

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
    #     logger.debug(f"SMS отправлена клиенту {current_user.phone_number} при завершении аренды")
    # except Exception as e:
    #     logger.error(f"Ошибка отправки SMS при завершении аренды: {e}")

    schedule_notifications(
        user_ids=[current_user.id, car.owner_id],
        refresh_vehicles=True
    )

    db.expire_all()
    db.refresh(current_user)
    db.refresh(rental)
    db.refresh(car)
    if car.owner_id:
        owner = db.query(User).filter(User.id == car.owner_id).first()
        if owner:
            db.refresh(owner)

    try:
        await notify_user_status_update(str(current_user.id))
        if car.owner_id:
            await notify_user_status_update(str(car.owner_id))
        await notify_vehicles_list_update()
        logger.info(f"WebSocket user_status notification sent for user {current_user.id} after completing rental")
    except Exception as e:
        logger.error(f"Error sending WebSocket notification: {e}")

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
    now = get_local_time()
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

    # Доступность тарифа и минимум часов для часового (настройки привязаны к машине)
    validate_tariff_for_booking(booking_request.rental_type, booking_request.duration, car)
    logger.info(
        "advance_booking: тариф проверен car_id=%s rental_type=%s duration=%s user_id=%s",
        booking_request.car_id,
        booking_request.rental_type.value if hasattr(booking_request.rental_type, "value") else booking_request.rental_type,
        booking_request.duration,
        current_user.id,
    )

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
            # Для поминутной аренды по умолчанию 60 минут (без дополнительного часа)
            booking_request.scheduled_end_time = booking_request.scheduled_start_time + timedelta(minutes=MINUTE_TARIFF_MIN_MINUTES)
        elif booking_request.rental_type == RentalType.HOURS:
            if booking_request.duration is None:
                raise HTTPException(status_code=400, detail="Duration обязателен для аренды по часам")
            booking_request.scheduled_end_time = booking_request.scheduled_start_time + timedelta(hours=booking_request.duration)
        else:  # DAYS
            if booking_request.duration is None:
                raise HTTPException(status_code=400, detail="Duration обязателен для посуточной аренды")
            booking_request.scheduled_end_time = booking_request.scheduled_start_time + timedelta(days=booking_request.duration)

    # Минутный тариф: минимум 60 минут
    if booking_request.rental_type == RentalType.MINUTES:
        span_minutes = (booking_request.scheduled_end_time - booking_request.scheduled_start_time).total_seconds() / 60
        if span_minutes < MINUTE_TARIFF_MIN_MINUTES:
            raise HTTPException(
                status_code=400,
                detail=f"Для минутного тарифа минимальное время бронирования — {MINUTE_TARIFF_MIN_MINUTES} минут. Указано: {int(span_minutes)} мин."
            )

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
        open_fee=0,
        delivery_fee=0,
        waiting_fee=0,
        overtime_fee=0,
        distance_fee=0,
        total_price=base,
        reservation_time=get_local_time(),
        scheduled_start_time=booking_request.scheduled_start_time,
        scheduled_end_time=booking_request.scheduled_end_time,
        is_advance_booking="true",
        delivery_latitude=booking_request.delivery_latitude,
        delivery_longitude=booking_request.delivery_longitude
    )
    
    db.add(rental)
    db.commit()
    db.refresh(rental)
    logger.info(
        "advance_booking: бронь создана rental_id=%s car_id=%s user_id=%s rental_type=%s scheduled=%s",
        uuid_to_sid(rental.id),
        booking_request.car_id,
        current_user.id,
        booking_request.rental_type.value if hasattr(booking_request.rental_type, "value") else booking_request.rental_type,
        booking_request.scheduled_start_time,
    )

    # 8) Обновляем машину: устанавливаем текущего арендатора и меняем статус
    car.current_renter_id = current_user.id
    car.status = CarStatus.SCHEDULED  # Для запланированных аренд машина получает статус SCHEDULED

    # Обновляем время последней активности пользователя
    current_user.last_activity_at = get_local_time()

    db.commit()

    schedule_notifications(
        user_ids=[current_user.id, car.owner_id],
        refresh_vehicles=True
    )

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
        current_user.wallet_balance += Decimal(str(refund_amount))
        rental.already_payed = 0

    # 4) Отменяем бронирование
    rental.rental_status = RentalStatus.CANCELLED
    rental.end_time = get_local_time()
    
    # Записываем топливо при завершении аренды (если аренда была начата)
    if rental.start_time and car.fuel_level is not None:
        if rental.rental_type in (RentalType.HOURS, RentalType.DAYS) and rental.overtime_fee and rental.overtime_fee > 0:
            rental.fuel_after_main_tariff = car.fuel_level
        else:
            if rental.fuel_after is None:
                rental.fuel_after = car.fuel_level
    
    # 5) Освобождаем автомобиль
    car.current_renter_id = None
    car.status = CarStatus.FREE
    
    db.commit()
    
    schedule_notifications(
        user_ids=[current_user.id, car.owner_id],
        refresh_vehicles=True
    )

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
            "minutes_tariff_enabled": getattr(car, "minutes_tariff_enabled", True),
            "hourly_tariff_enabled": getattr(car, "hourly_tariff_enabled", True),
            "hourly_min_hours": max(1, getattr(car, "hourly_min_hours", 1) or 1),
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
