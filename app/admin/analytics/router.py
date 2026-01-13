"""
Admin Analytics Router - История транзакций для аналитики
"""
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.dependencies.database.database import get_db
from app.models.user_model import User, UserRole
from app.models.wallet_transaction_model import WalletTransaction, WalletTransactionType
from app.models.history_model import RentalHistory
from app.models.car_model import Car
from app.auth.dependencies.get_current_user import get_current_user
from app.utils.short_id import uuid_to_sid
from app.utils.time_utils import get_local_time
from fastapi import HTTPException
from math import ceil

analytics_router = APIRouter(prefix="/analytics", tags=["Admin Analytics"])


DEPOSIT_TYPES = [
    WalletTransactionType.DEPOSIT,
    WalletTransactionType.PROMO_BONUS,
    WalletTransactionType.COMPANY_BONUS,
    WalletTransactionType.REFUND,
]

EXPENSE_TYPES = [
    WalletTransactionType.RENT_OPEN_FEE,
    WalletTransactionType.RENT_WAITING_FEE,
    WalletTransactionType.RENT_MINUTE_CHARGE,
    WalletTransactionType.RENT_OVERTIME_FEE,
    WalletTransactionType.RENT_DISTANCE_FEE,
    WalletTransactionType.RENT_BASE_CHARGE,
    WalletTransactionType.RENT_FUEL_FEE,
    WalletTransactionType.DELIVERY_FEE,
    WalletTransactionType.DELIVERY_PENALTY,
    WalletTransactionType.ADMIN_DEDUCTION,
    WalletTransactionType.DAMAGE_PENALTY,
    WalletTransactionType.FINE_PENALTY,
    WalletTransactionType.SANCTION_PENALTY,
    WalletTransactionType.RESERVATION_REBOOKING_FEE,
    WalletTransactionType.RESERVATION_CANCELLATION_FEE,
    WalletTransactionType.RENT_DRIVER_FEE,
]


def _get_period_start(period: str) -> datetime:
    """Возвращает начало периода (день, неделя, месяц)"""
    now = get_local_time()
    if period == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start = now - timedelta(days=now.weekday())
        return start.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _calculate_summary(db: Session, transaction_types: List[WalletTransactionType]) -> dict:
    """Рассчитывает суммы за день, неделю, месяц"""
    now = get_local_time()
    
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    def get_sum(start_date: datetime) -> int:
        result = db.query(func.sum(func.abs(WalletTransaction.amount))).filter(
            WalletTransaction.transaction_type.in_(transaction_types),
            WalletTransaction.created_at >= start_date
        ).scalar()
        return int(result or 0)
    
    return {
        "today": get_sum(day_start),
        "week": get_sum(week_start),
        "month": get_sum(month_start)
    }


@analytics_router.get("/deposits", summary="История пополнений для аналитики")
async def get_deposits_analytics(
    period: str = Query("day", description="Период: day, week, month"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Возвращает:
    - summary: общая сумма пополнений за день, неделю, месяц
    - transactions: список пополнений за выбранный период
    """
    if current_user.role != UserRole.ADMIN:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Только для администраторов")
    
    summary = _calculate_summary(db, DEPOSIT_TYPES)
    period_start = _get_period_start(period)
    offset = (page - 1) * limit
    
    transactions_query = (
        db.query(WalletTransaction, User)
        .join(User, User.id == WalletTransaction.user_id)
        .filter(
            WalletTransaction.transaction_type.in_(DEPOSIT_TYPES),
            WalletTransaction.created_at >= period_start
        )
        .order_by(WalletTransaction.created_at.desc())
    )
    
    total_count = transactions_query.count()
    transactions = transactions_query.offset(offset).limit(limit).all()
    
    items = []
    for tx, user in transactions:
        items.append({
            "transaction_id": uuid_to_sid(tx.id),
            "user_id": uuid_to_sid(user.id),
            "user_name": f"{user.first_name or ''} {user.last_name or ''}".strip() or "Не указано",
            "phone": user.phone_number,
            "amount": int(tx.amount),
            "type": tx.transaction_type.value,
            "description": tx.description,
            "created_at": tx.created_at.isoformat() if tx.created_at else None
        })
    
    return {
        "summary": summary,
        "period": period,
        "total_count": total_count,
        "page": page,
        "limit": limit,
        "transactions": items
    }


@analytics_router.get("/expenses", summary="История расходов для аналитики")
async def get_expenses_analytics(
    period: str = Query("day", description="Период: day, week, month"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Возвращает:
    - summary: общая сумма расходов за день, неделю, месяц
    - transactions: список расходов за выбранный период (с информацией о машине если есть)
    """
    if current_user.role != UserRole.ADMIN:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Только для администраторов")
    
    summary = _calculate_summary(db, EXPENSE_TYPES)
    period_start = _get_period_start(period)
    offset = (page - 1) * limit
    
    transactions_query = (
        db.query(WalletTransaction, User, RentalHistory, Car)
        .join(User, User.id == WalletTransaction.user_id)
        .outerjoin(RentalHistory, RentalHistory.id == WalletTransaction.related_rental_id)
        .outerjoin(Car, Car.id == RentalHistory.car_id)
        .filter(
            WalletTransaction.transaction_type.in_(EXPENSE_TYPES),
            WalletTransaction.created_at >= period_start
        )
        .order_by(WalletTransaction.created_at.desc())
    )
    
    total_count = transactions_query.count()
    transactions = transactions_query.offset(offset).limit(limit).all()
    
    items = []
    for tx, user, rental, car in transactions:
        item = {
            "transaction_id": uuid_to_sid(tx.id),
            "user_id": uuid_to_sid(user.id),
            "user_name": f"{user.first_name or ''} {user.last_name or ''}".strip() or "Не указано",
            "phone": user.phone_number,
            "amount": abs(int(tx.amount)), 
            "type": tx.transaction_type.value,
            "description": tx.description,
            "created_at": tx.created_at.isoformat() if tx.created_at else None,
            "car_name": car.name if car else None,
            "plate_number": car.plate_number if car else None,
            "rental_id": uuid_to_sid(rental.id) if rental else None,
        }
        items.append(item)
    
    return {
        "summary": summary,
        "period": period,
        "total_count": total_count,
        "page": page,
        "limit": limit,
        "transactions": items
    }


@analytics_router.get("/transactions", summary="Полная история транзакций")
async def get_all_transactions(
    page: int = Query(1, ge=1, description="Страница"),
    limit: int = Query(50, ge=1, le=200, description="Записей на странице"),
    transaction_type: Optional[str] = Query(None, description="Фильтр по типу транзакции"),
    filter_type: Optional[str] = Query(None, description="Фильтр: deposits, expenses, deposits_with_tracking_id"),
    user_phone: Optional[str] = Query(None, description="Фильтр по номеру телефона"),
    date_from: Optional[str] = Query(None, description="Дата начала (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Дата окончания (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Полная история транзакций.
    
    Фильтры:
    - deposits: только пополнения
    - expenses: только траты
    - deposits_with_tracking_id: только пополнения с tracking_id
    """
    from collections import defaultdict
    
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    query = (
        db.query(WalletTransaction, User, RentalHistory, Car)
        .join(User, User.id == WalletTransaction.user_id)
        .outerjoin(RentalHistory, RentalHistory.id == WalletTransaction.related_rental_id)
        .outerjoin(Car, Car.id == RentalHistory.car_id)
    )
    
    # Применяем фильтр по типу (deposits, expenses, deposits_with_tracking_id)
    if filter_type:
        if filter_type == "deposits":
            query = query.filter(WalletTransaction.transaction_type.in_(DEPOSIT_TYPES))
        elif filter_type == "expenses":
            query = query.filter(WalletTransaction.transaction_type.in_(EXPENSE_TYPES))
        elif filter_type == "deposits_with_tracking_id":
            query = query.filter(
                WalletTransaction.transaction_type.in_(DEPOSIT_TYPES),
                WalletTransaction.tracking_id.isnot(None)
            )
        else:
            raise HTTPException(status_code=400, detail=f"Неизвестный тип фильтра: {filter_type}. Доступные: deposits, expenses, deposits_with_tracking_id")
    
    if transaction_type:
        try:
            tx_type = WalletTransactionType(transaction_type)
            query = query.filter(WalletTransaction.transaction_type == tx_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Неизвестный тип транзакции: {transaction_type}")
    
    if user_phone:
        query = query.filter(User.phone_number.contains(user_phone))
    
    if date_from:
        try:
            from_date = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(WalletTransaction.created_at >= from_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат date_from (YYYY-MM-DD)")
    
    if date_to:
        try:
            to_date = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(WalletTransaction.created_at < to_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат date_to (YYYY-MM-DD)")
    
    total = query.count()
    offset = (page - 1) * limit
    
    transactions = query.order_by(WalletTransaction.created_at.desc()).offset(offset).limit(limit).all()
    transactions_by_type = defaultdict(list)
    
    for tx, user, rental, car in transactions:
        tx_data = {
            "id": uuid_to_sid(tx.id),
            "amount": float(tx.amount),
            "balance_before": float(tx.balance_before),
            "balance_after": float(tx.balance_after),
            "description": tx.description,
            "created_at": tx.created_at.isoformat() if tx.created_at else None,
            "transaction_type": tx.transaction_type.value,
            "user": {
                "id": uuid_to_sid(user.id),
                "first_name": user.first_name,
                "last_name": user.last_name,
                "middle_name": user.middle_name,
                "phone": user.phone_number,
                "selfie_url": user.selfie_url,
                "wallet_balance": float(user.wallet_balance or 0)
            },
            "car": {
                "id": uuid_to_sid(car.id) if car else None,
                "name": car.name if car else None,
                "plate_number": car.plate_number if car else None
            } if car else None,
            "rental_id": uuid_to_sid(rental.id) if rental else None,
            "tracking_id": tx.tracking_id
        }
        
        # Добавляем информацию об аренде, если она есть
        if rental:
            total_price_without_fuel = (
                (rental.base_price or 0) +
                (rental.open_fee or 0) +
                (rental.delivery_fee or 0) +
                (rental.waiting_fee or 0) +
                (rental.overtime_fee or 0) +
                (rental.distance_fee or 0) +
                (rental.driver_fee or 0)
            )
            tx_data["rental"] = {
                "total_price": float(rental.total_price or 0),
                "total_price_without_fuel": float(total_price_without_fuel)
            }
        
        transactions_by_type[tx.transaction_type.value].append(tx_data)
    
    # Вычисляем summary: общая сумма пополнений и сумма пополнений без tracking_id
    base_summary_query = db.query(func.sum(func.abs(WalletTransaction.amount))).filter(
        WalletTransaction.transaction_type.in_(DEPOSIT_TYPES)
    )
    
    # Применяем те же фильтры по датам что и к основному запросу
    if date_from:
        try:
            from_date = datetime.strptime(date_from, "%Y-%m-%d")
            base_summary_query = base_summary_query.filter(WalletTransaction.created_at >= from_date)
        except ValueError:
            pass
    
    if date_to:
        try:
            to_date = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            base_summary_query = base_summary_query.filter(WalletTransaction.created_at < to_date)
        except ValueError:
            pass
    
    # Общая сумма всех пополнений
    total_deposits = base_summary_query.scalar() or 0
    
    # Сумма пополнений без tracking_id (создаем новый запрос с теми же фильтрами)
    deposits_without_tracking_query = db.query(func.sum(func.abs(WalletTransaction.amount))).filter(
        WalletTransaction.transaction_type.in_(DEPOSIT_TYPES),
        (WalletTransaction.tracking_id.is_(None)) | (WalletTransaction.tracking_id == "")
    )
    
    if date_from:
        try:
            from_date = datetime.strptime(date_from, "%Y-%m-%d")
            deposits_without_tracking_query = deposits_without_tracking_query.filter(WalletTransaction.created_at >= from_date)
        except ValueError:
            pass
    
    if date_to:
        try:
            to_date = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            deposits_without_tracking_query = deposits_without_tracking_query.filter(WalletTransaction.created_at < to_date)
        except ValueError:
            pass
    
    total_deposits_without_tracking = deposits_without_tracking_query.scalar() or 0
    
    # Общая сумма всех трат
    expenses_summary_query = db.query(func.sum(func.abs(WalletTransaction.amount))).filter(
        WalletTransaction.transaction_type.in_(EXPENSE_TYPES)
    )
    
    if date_from:
        try:
            from_date = datetime.strptime(date_from, "%Y-%m-%d")
            expenses_summary_query = expenses_summary_query.filter(WalletTransaction.created_at >= from_date)
        except ValueError:
            pass
    
    if date_to:
        try:
            to_date = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            expenses_summary_query = expenses_summary_query.filter(WalletTransaction.created_at < to_date)
        except ValueError:
            pass
    
    total_expenses = expenses_summary_query.scalar() or 0
    
    summary_by_type = {}
    for tx_type in WalletTransactionType:
        type_query = db.query(func.sum(func.abs(WalletTransaction.amount))).filter(
            WalletTransaction.transaction_type == tx_type
        )
        
        if date_from:
            try:
                from_date = datetime.strptime(date_from, "%Y-%m-%d")
                type_query = type_query.filter(WalletTransaction.created_at >= from_date)
            except ValueError:
                pass
        
        if date_to:
            try:
                to_date = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
                type_query = type_query.filter(WalletTransaction.created_at < to_date)
            except ValueError:
                pass
        
        total_amount = type_query.scalar() or 0
        summary_by_type[tx_type.value] = float(total_amount)
    
    return {
        "transactions": dict(transactions_by_type),
        "summary": {
            "total_deposits": float(total_deposits),
            "total_deposits_without_tracking_id": float(total_deposits_without_tracking),
            "total_deposits_with_tracking_id": float(total_deposits - total_deposits_without_tracking),
            "total_expenses": float(total_expenses),
            "by_type": summary_by_type
        },
        "total": total,
        "page": page,
        "limit": limit,
        "pages": ceil(total / limit) if limit > 0 else 0,
        "available_types": [t.value for t in WalletTransactionType],
        "filter_type": filter_type
    }
