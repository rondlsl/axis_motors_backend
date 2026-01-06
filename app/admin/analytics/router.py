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
