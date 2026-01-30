"""
Router для работы с завершёнными арендами в админ панели
"""
import sys
import traceback
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, desc
from typing import List, Optional, Dict, Any
from math import ceil, floor

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.history_model import RentalHistory, RentalStatus, RentalReview
from app.models.car_model import Car, CarBodyType
from app.models.wallet_transaction_model import WalletTransaction
from app.models.rental_actions_model import RentalAction
from app.models.contract_model import UserContractSignature
from app.utils.short_id import uuid_to_sid, safe_sid_to_uuid
from app.admin.cars.utils import sort_car_photos
from app.rent.utils.calculate_price import FUEL_PRICE_PER_LITER, ELECTRIC_FUEL_PRICE_PER_LITER
from app.core.logging_config import get_logger

rentals_router = APIRouter(tags=["Admin Rentals"])
logger = get_logger(__name__)


def _log_delete_rental_stdout(message: str) -> None:
    """Пишет строку в stdout и сбрасывает буфер — всегда видна в логах (Docker/K8s), не зависит от LOG_LEVEL."""
    try:
        sys.stdout.write(f"[DELETE_RENTAL] {message}\n")
        sys.stdout.flush()
    except Exception:
        pass


def _get_tariff_display(rental_type_value: str) -> str:
    """Преобразует тип тарифа в читаемый вид"""
    tariff_map = {
        "minutes": "Минутный",
        "hours": "Часовой",
        "days": "Суточный"
    }
    return tariff_map.get(rental_type_value, rental_type_value)


def _calculate_fuel_fee(rental: RentalHistory, car: Car) -> int:
    """Рассчитывает стоимость топлива"""
    if rental.fuel_before is None or rental.fuel_after is None:
        return 0
    
    if rental.fuel_after >= rental.fuel_before:
        return 0
    
    fuel_consumed = ceil(rental.fuel_before) - floor(rental.fuel_after)
    if fuel_consumed <= 0:
        return 0
    
    fuel_price = ELECTRIC_FUEL_PRICE_PER_LITER if car.body_type == CarBodyType.ELECTRIC else FUEL_PRICE_PER_LITER
    return int(fuel_consumed * fuel_price)


def _build_car_info(car: Car) -> Dict[str, Any]:
    """Строит информацию о машине"""
    return {
        "id": uuid_to_sid(car.id),
        "name": car.name,
        "plate_number": car.plate_number,
        "engine_volume": car.engine_volume,
        "year": car.year,
        "drive_type": car.drive_type,
        "transmission_type": car.transmission_type.value if car.transmission_type else None,
        "body_type": car.body_type.value if car.body_type else None,
        "auto_class": car.auto_class.value if car.auto_class else None,
        "price_per_minute": car.price_per_minute,
        "price_per_hour": car.price_per_hour,
        "price_per_day": car.price_per_day,
        "latitude": car.latitude,
        "longitude": car.longitude,
        "fuel_level": car.fuel_level,
        "mileage": car.mileage,
        "course": car.course,
        "photos": sort_car_photos(car.photos or []),
        "description": car.description,
        "vin": car.vin,
        "color": car.color,
        "gps_id": car.gps_id,
        "gps_imei": car.gps_imei,
        "status": car.status.value if car.status else None,
    }


def _build_renter_info(renter: User, car: Optional[Car] = None) -> Dict[str, Any]:
    """Строит информацию об арендаторе"""
    # Проверяем, является ли пользователь владельцем конкретной машины
    is_owner = False
    if car and car.owner_id:
        is_owner = renter.id == car.owner_id
    
    return {
        "id": uuid_to_sid(renter.id),
        "first_name": renter.first_name,
        "last_name": renter.last_name,
        "phone_number": renter.phone_number,
        "selfie": renter.selfie_url,
        "is_owner": is_owner
    }


def _build_transactions(transactions: List[WalletTransaction]) -> List[Dict[str, Any]]:
    """Строит список транзакций"""
    return [
        {
            "id": uuid_to_sid(tx.id),
            "amount": float(tx.amount),
            "transaction_type": tx.transaction_type.value if hasattr(tx.transaction_type, 'value') else str(tx.transaction_type),
            "description": tx.description,
            "balance_before": float(tx.balance_before),
            "balance_after": float(tx.balance_after),
            "tracking_id": tx.tracking_id,
            "created_at": tx.created_at.isoformat() if tx.created_at else None,
            "related_rental_id": uuid_to_sid(tx.related_rental_id) if tx.related_rental_id else None,
        }
        for tx in transactions
    ]


@rentals_router.get("/completed", summary="Получить все завершённые аренды")
async def get_completed_rentals(
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(50, ge=1, le=200, description="Количество элементов на странице"),
    rental_id: Optional[str] = Query(None, description="ID аренды для фильтрации"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Возвращает все завершённые аренды с полной информацией:
    - Информация о машине
    - Информация об аренде (все поля)
    - Информация об арендаторе
    - Транзакции по аренде
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    # Получаем все завершённые аренды
    query = db.query(RentalHistory).filter(
        RentalHistory.rental_status == RentalStatus.COMPLETED
    )
    
    # Фильтруем по rental_id если передан
    if rental_id:
        try:
            rental_uuid = safe_sid_to_uuid(rental_id)
            query = query.filter(RentalHistory.id == rental_uuid)
        except Exception:
            raise HTTPException(status_code=400, detail="Некорректный ID аренды")
    
    # Сортируем по reservation_time по убыванию (самые новые сначала)
    query = query.order_by(desc(RentalHistory.reservation_time))
    
    # Применяем eager loading для связанных объектов
    query = query.options(
        joinedload(RentalHistory.car),
        joinedload(RentalHistory.user)
    )
    
    # Подсчитываем общее количество
    total = query.count()
    
    # Применяем пагинацию
    offset = (page - 1) * limit
    rentals = query.offset(offset).limit(limit).all()
    
    # Формируем результат
    items = []
    
    for rental in rentals:
        car = rental.car
        renter = rental.user
        
        # Рассчитываем fuel_fee
        fuel_fee = _calculate_fuel_fee(rental, car) if car else 0
        
        # Рассчитываем total_price_without_fuel
        total_price_without_fuel = (
            (rental.base_price or 0) +
            (rental.open_fee or 0) +
            (rental.delivery_fee or 0) +
            (rental.waiting_fee or 0) +
            (rental.overtime_fee or 0) +
            (rental.distance_fee or 0) +
            (rental.driver_fee or 0)
        )
        
        # Получаем транзакции для этой аренды
        transactions = db.query(WalletTransaction).filter(
            WalletTransaction.related_rental_id == rental.id
        ).order_by(WalletTransaction.created_at).all()
        
        # Строим информацию о машине
        car_info = _build_car_info(car) if car else {}
        
        # Строим информацию об арендаторе
        renter_info = _build_renter_info(renter, car) if renter else {}
        
        # Получаем tariff_display
        tariff_value = rental.rental_type.value if hasattr(rental.rental_type, 'value') else str(rental.rental_type)
        tariff_display = _get_tariff_display(tariff_value)
        
        # Рассчитываем заработок владельца
        base_price_owner = int((rental.base_price or 0) * 0.5 * 0.97)
        waiting_fee_owner = int((rental.waiting_fee or 0) * 0.5 * 0.97)
        overtime_fee_owner = int((rental.overtime_fee or 0) * 0.5 * 0.97)
        total_owner_earnings = int(((rental.base_price or 0) + (rental.waiting_fee or 0) + (rental.overtime_fee or 0)) * 0.5 * 0.97)
        
        # Формируем объект аренды
        rental_data = {
            # ID аренды
            "rental_id": uuid_to_sid(rental.id),
            
            # Информация о машине
            "car": car_info,
            
            # Информация об аренде
            "reservation_time": rental.reservation_time.isoformat() if rental.reservation_time else None,
            "start_time": rental.start_time.isoformat() if rental.start_time else None,
            "end_time": rental.end_time.isoformat() if rental.end_time else None,
            "duration": rental.duration,
            
            "already_payed": rental.already_payed or 0,
            "total_price": rental.total_price or 0,
            "total_price_without_fuel": total_price_without_fuel,
            
            "tariff": tariff_value,
            "tariff_display": tariff_display,
            
            "base_price": rental.base_price or 0,
            "open_fee": rental.open_fee or 0,
            "delivery_fee": rental.delivery_fee or 0,
            "fuel_fee": fuel_fee,
            "waiting_fee": rental.waiting_fee or 0,
            "overtime_fee": rental.overtime_fee or 0,
            "distance_fee": rental.distance_fee or 0,
            
            "with_driver": rental.with_driver or False,
            "driver_fee": rental.driver_fee or 0,
            "rebooking_fee": rental.rebooking_fee or 0,
            
            "base_price_owner": base_price_owner,
            "waiting_fee_owner": waiting_fee_owner,
            "overtime_fee_owner": overtime_fee_owner,
            "total_owner_earnings": total_owner_earnings,
            
            "fuel_before": float(rental.fuel_before) if rental.fuel_before is not None else None,
            "fuel_after": float(rental.fuel_after) if rental.fuel_after is not None else None,
            
            # Информация об арендаторе
            "renter": renter_info,
            
            # Транзакции
            "transactions": _build_transactions(transactions),
        }
        
        items.append(rental_data)
    
    return {
        "rentals": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": ceil(total / limit) if limit > 0 else 0
    }


@rentals_router.delete("/{rental_id}", summary="Удалить аренду по ID")
async def delete_rental_by_id(
    rental_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Удалить аренду по ID (только для администраторов и поддержки).
    
    Удаляются в порядке:
    - транзакции кошелька (related_rental_id)
    - подписи договоров (rental_id)
    - действия по аренде (rental_id)
    - отзыв по аренде (rental_id)
    - запись аренды (rental_history)
    """
    _log_delete_rental_stdout(f"start rental_id={rental_id} admin_id={current_user.id}")
    logger.info(
        "delete_rental_by_id: start rental_id=%s admin_id=%s",
        rental_id,
        str(current_user.id),
        extra={"rental_id": rental_id, "admin_id": str(current_user.id)},
    )
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        logger.warning("delete_rental_by_id: forbidden role=%s", current_user.role)
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    try:
        rental_uuid = safe_sid_to_uuid(rental_id)
        logger.info("delete_rental_by_id: parsed rental_uuid=%s", str(rental_uuid))
    except Exception as e:
        logger.warning("delete_rental_by_id: invalid rental_id=%s error=%s", rental_id, e)
        raise HTTPException(status_code=400, detail="Некорректный ID аренды")

    # 1) Строковая блокировка: SELECT ... FOR UPDATE — блокировка до конца транзакции (commit/rollback).
    # Billing job при попытке прочитать эту аренду будет ждать; после commit аренды уже не будет.
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).with_for_update().first()
    if not rental:
        logger.warning("delete_rental_by_id: rental not found rental_id=%s", rental_id)
        raise HTTPException(status_code=404, detail="Аренда не найдена")

    logger.info(
        "delete_rental_by_id: rental found car_id=%s user_id=%s status=%s",
        rental.car_id,
        rental.user_id,
        getattr(rental.rental_status, "value", str(rental.rental_status)),
        extra={"rental_id": rental_id, "car_id": rental.car_id},
    )

    try:
        # Массовое удаление без загрузки строк — избегаем LookupError по enum (в БД может быть 'success', в Python — ActionStatus.SUCCESS).
        deleted_wallet_transactions = db.query(WalletTransaction).filter(
            WalletTransaction.related_rental_id == rental_uuid
        ).delete(synchronize_session=False)
        logger.info("delete_rental_by_id: wallet_transactions deleted=%s", deleted_wallet_transactions)

        deleted_contract_signatures = db.query(UserContractSignature).filter(
            UserContractSignature.rental_id == rental_uuid
        ).delete(synchronize_session=False)
        logger.info("delete_rental_by_id: contract_signatures deleted=%s", deleted_contract_signatures)

        deleted_rental_actions = db.query(RentalAction).filter(
            RentalAction.rental_id == rental_uuid
        ).delete(synchronize_session=False)
        logger.info("delete_rental_by_id: rental_actions deleted=%s", deleted_rental_actions)

        deleted_rental_review = db.query(RentalReview).filter(
            RentalReview.rental_id == rental_uuid
        ).delete(synchronize_session=False)
        logger.info("delete_rental_by_id: rental_review deleted=%s", deleted_rental_review)

        # Удаляем запись аренды массовым DELETE, без db.delete(rental), чтобы не загружать
        # связь rental.actions (cascade delete-orphan) — иначе SQLAlchemy подгружает RentalAction
        # и падает на enum actionstatus ('success' в БД vs SUCCESS в Python).
        logger.info("delete_rental_by_id: deleting rental row")
        db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).delete(synchronize_session=False)
        db.expunge(rental)  # убираем из сессии, т.к. строка уже удалена массовым DELETE
        db.commit()
        logger.info("delete_rental_by_id: commit ok")

        # 3) Аудит: факт удаления — только в application-лог (rental_id, admin_id; timestamp даёт logger).
        logger.info(
            "Admin deleted rental: rental_id=%s admin_id=%s",
            rental_id,
            str(current_user.id),
            extra={"rental_id": rental_id, "admin_id": str(current_user.id)},
        )

        return {
            "message": "Аренда успешно удалена",
            "rental_id": rental_id,
            "deleted_wallet_transactions": deleted_wallet_transactions,
            "deleted_contract_signatures": deleted_contract_signatures,
            "deleted_rental_actions": deleted_rental_actions,
            "deleted_rental_review": deleted_rental_review,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        exc_type = type(e).__name__
        exc_msg = str(e)
        tb = traceback.format_exc()
        # Всегда видно в логах (stdout), не зависит от LOG_LEVEL
        _log_delete_rental_stdout(f"ERROR rental_id={rental_id} exception_type={exc_type} exception_msg={exc_msg}")
        _log_delete_rental_stdout(f"traceback:\n{tb}")
        logger.error(
            "delete_rental_by_id: rollback done rental_id=%s admin_id=%s exception_type=%s exception_msg=%s",
            rental_id,
            str(current_user.id),
            exc_type,
            exc_msg,
            extra={"rental_id": rental_id, "admin_id": str(current_user.id), "error": exc_msg},
        )
        logger.exception("Delete rental failed: rental_id=%s admin_id=%s", rental_id, str(current_user.id))
        raise HTTPException(status_code=500, detail="Ошибка удаления аренды")

