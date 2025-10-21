from datetime import datetime, timedelta
import calendar
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.utils.short_id import safe_sid_to_uuid, uuid_to_sid
from app.utils.sid_converter import convert_uuid_response_to_sid

from app.auth.dependencies.get_current_user import get_current_user
from app.dependencies.database.database import get_db
from app.models.user_model import User, UserRole
from app.models.wallet_transaction_model import WalletTransaction, WalletTransactionType
from app.wallet.schemas import (
    WalletTransactionsListOut,
    WalletTransactionsSummaryOut,
    WalletBalanceOut,
    WalletStatementOut,
    WalletTransactionOut,
    WalletUsersBalancesOut,
)


WalletRouter = APIRouter(tags=["Wallet"], prefix="/wallet")


def _apply_date_filters(
    q, *,
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    year: Optional[int],
    month: Optional[int],
    day: Optional[int],
):
    # Если явно указаны from/to — применяем их
    if date_from is not None:
        q = q.filter(WalletTransaction.created_at >= date_from)
    if date_to is not None:
        q = q.filter(WalletTransaction.created_at <= date_to)

    # Если from/to не заданы, но есть year/month/day — строим период
    if date_from is None and date_to is None and (year or month or day):
        if year and month and day:
            start = datetime(year, month, day)
            end = start + timedelta(days=1)
        elif year and month:
            last_day = calendar.monthrange(year, month)[1]
            start = datetime(year, month, 1)
            end = datetime(year, month, last_day, 23, 59, 59, 999999)
        elif year:
            start = datetime(year, 1, 1)
            end = datetime(year, 12, 31, 23, 59, 59, 999999)
        else:
            start, end = None, None

        if start is not None:
            q = q.filter(WalletTransaction.created_at >= start)
        if end is not None:
            q = q.filter(WalletTransaction.created_at <= end)

    return q


@WalletRouter.get("/transactions/export")
def export_my_transactions_csv(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    day: Optional[int] = Query(None),
):
    q = db.query(WalletTransaction).filter(WalletTransaction.user_id == current_user.id)
    q = _apply_date_filters(q, date_from=date_from, date_to=date_to, year=year, month=month, day=day)
    items = q.order_by(WalletTransaction.created_at.desc()).all()
    # Формируем CSV и отдаём как файл
    def _iter_csv():
        yield "id,created_at,type,amount,balance_before,balance_after,related_rental_id,tracking_id,description\n"
        for t in items:
            row = [
                str(t.id),
                t.created_at.isoformat(),
                t.transaction_type.value,
                str(float(t.amount)),
                str(float(t.balance_before)),
                str(float(t.balance_after)),
                str(t.related_rental_id or ""),
                str(t.tracking_id or ""),
                (t.description or "").replace(",", " ")
            ]
            yield ",".join(row) + "\n"

    filename = f"wallet_transactions_user_{current_user.id}.csv"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(_iter_csv(), media_type="text/csv", headers=headers)


@WalletRouter.get("/transactions", response_model=WalletTransactionsListOut)
def get_my_transactions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    rental_id: Optional[str] = Query(None),
    type: Optional[WalletTransactionType] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    day: Optional[int] = Query(None),
):
    q = db.query(WalletTransaction).filter(WalletTransaction.user_id == current_user.id)

    if rental_id is not None:
        try:
            rental_uuid = safe_sid_to_uuid(rental_id)
            q = q.filter(WalletTransaction.related_rental_id == rental_uuid)
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат rental_id")
    if type is not None:
        q = q.filter(WalletTransaction.transaction_type == type)

    q = _apply_date_filters(q, date_from=date_from, date_to=date_to, year=year, month=month, day=day)

    q = q.order_by(WalletTransaction.created_at.desc()).offset(offset).limit(limit)

    items = q.all()
    return {
        "transactions": [
            WalletTransactionOut(
                id=t.sid,
                user_id=t.user.sid,
                amount=float(t.amount),
                type=t.transaction_type.value,
                description=t.description,
                balance_before=float(t.balance_before),
                balance_after=float(t.balance_after),
                created_at=t.created_at,
                related_rental_id=t.related_rental_id,
                tracking_id=t.tracking_id,
                first_name=current_user.first_name,
                last_name=current_user.last_name,
                phone_number=current_user.phone_number,
            )
            for t in items
        ]
    }


@WalletRouter.get("/balance", response_model=WalletBalanceOut)
def get_my_balance(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    last_tx = (
        db.query(WalletTransaction)
        .filter(WalletTransaction.user_id == current_user.id)
        .order_by(WalletTransaction.created_at.desc())
        .first()
    )
    return WalletBalanceOut(
        wallet_balance=float(current_user.wallet_balance or 0),
        last_transaction_at=last_tx.created_at if last_tx else None,
    )


@WalletRouter.get("/transactions/summary", response_model=WalletTransactionsSummaryOut)
def get_my_transactions_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    type: Optional[WalletTransactionType] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    day: Optional[int] = Query(None),
):
    q = db.query(WalletTransaction).filter(WalletTransaction.user_id == current_user.id)
    if type is not None:
        q = q.filter(WalletTransaction.transaction_type == type)
    q = _apply_date_filters(q, date_from=date_from, date_to=date_to, year=year, month=month, day=day)

    # Итого по входящим/исходящим и разбивка по типам
    items = q.all()
    income = sum(float(t.amount) for t in items if float(t.amount) > 0)
    outcome = sum(-float(t.amount) for t in items if float(t.amount) < 0)
    by_type: dict[str, float] = {}
    for t in items:
        key = t.transaction_type.value
        by_type[key] = by_type.get(key, 0.0) + float(t.amount)

    return WalletTransactionsSummaryOut(
        income=income,
        outcome=outcome,
        by_type=by_type,
        count=len(items),
    )


@WalletRouter.get("/transactions/statement", response_model=WalletStatementOut)
def get_my_transactions_statement(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
):
    # Определяем период
    date_from = None
    date_to = None
    if year and month:
        last_day = calendar.monthrange(year, month)[1]
        date_from = datetime(year, month, 1)
        date_to = datetime(year, month, last_day, 23, 59, 59, 999999)
    elif year:
        date_from = datetime(year, 1, 1)
        date_to = datetime(year, 12, 31, 23, 59, 59, 999999)

    q = db.query(WalletTransaction).filter(WalletTransaction.user_id == current_user.id)
    q = _apply_date_filters(q, date_from=date_from, date_to=date_to, year=None, month=None, day=None)
    items = q.order_by(WalletTransaction.created_at.asc()).all()

    # Группировка по месяцам (YYYY-MM)
    groups: dict[str, dict] = {}
    for t in items:
        dt = t.created_at
        key = f"{dt.year:04d}-{dt.month:02d}"
        g = groups.setdefault(key, {
            "year": dt.year,
            "month": dt.month,
            "income": 0.0,
            "outcome": 0.0,
            "count": 0,
            "first_transaction_at": None,
            "last_transaction_at": None,
        })
        amount = float(t.amount)
        if amount > 0:
            g["income"] += amount
        else:
            g["outcome"] += -amount
        g["count"] += 1
        iso = t.created_at.isoformat()
        if g["first_transaction_at"] is None:
            g["first_transaction_at"] = iso
        g["last_transaction_at"] = iso

    # Сортировка по ключу (месяц убывание)
    ordered = [groups[k] for k in sorted(groups.keys(), reverse=True)]
    return WalletStatementOut(months=ordered)


@WalletRouter.get("/transactions/export")
def export_my_transactions_legacy_path(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    day: Optional[int] = Query(None),
):
    q = db.query(WalletTransaction).filter(WalletTransaction.user_id == current_user.id)
    q = _apply_date_filters(q, date_from=date_from, date_to=date_to, year=year, month=month, day=day)
    items = q.order_by(WalletTransaction.created_at.desc()).all()

    def _iter_csv():
        yield "id,created_at,type,amount,balance_before,balance_after,related_rental_id,tracking_id,description\n"
        for t in items:
            row = [
                str(t.id),
                t.created_at.isoformat(),
                t.transaction_type.value,
                str(float(t.amount)),
                str(float(t.balance_before)),
                str(float(t.balance_after)),
                str(t.related_rental_id or ""),
                str(t.tracking_id or ""),
                (t.description or "").replace(",", " ")
            ]
            yield ",".join(row) + "\n"

    filename = f"wallet_transactions_user_{current_user.id}.csv"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(_iter_csv(), media_type="text/csv", headers=headers)


@WalletRouter.get("/transactions/{transaction_id}", response_model=WalletTransactionOut)
def get_transaction_detail(
    transaction_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        transaction_uuid = safe_sid_to_uuid(transaction_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат ID")
    
    tx = (
        db.query(WalletTransaction)
        .filter(WalletTransaction.id == transaction_uuid, WalletTransaction.user_id == current_user.id)
        .first()
    )
    if not tx:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")
    return WalletTransactionOut(
        id=tx.sid,
        user_id=tx.user.sid,
        amount=float(tx.amount),
        type=tx.transaction_type.value,
        description=tx.description,
        balance_before=float(tx.balance_before),
        balance_after=float(tx.balance_after),
        created_at=tx.created_at,
        related_rental_id=tx.related_rental_id,
        tracking_id=tx.tracking_id,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        phone_number=current_user.phone_number,
    )

def _ensure_admin(user: User):
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")


@WalletRouter.get("/transactions/by-user/{user_id}", response_model=WalletTransactionsListOut)
def get_transactions_by_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    type: Optional[WalletTransactionType] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    day: Optional[int] = Query(None),
):
    _ensure_admin(current_user)
    
    try:
        user_uuid = safe_sid_to_uuid(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат ID")
    
    q = db.query(WalletTransaction).filter(WalletTransaction.user_id == user_uuid)
    if type is not None:
        q = q.filter(WalletTransaction.transaction_type == type)
    q = _apply_date_filters(q, date_from=date_from, date_to=date_to, year=year, month=month, day=day)
    items = q.order_by(WalletTransaction.created_at.desc()).offset(offset).limit(limit).all()

    user_ids = {t.user_id for t in items}
    users_map = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    return {
        "transactions": [
            WalletTransactionOut(
                id=t.sid,
                user_id=t.user.sid,
                amount=float(t.amount),
                type=t.transaction_type.value,
                description=t.description,
                balance_before=float(t.balance_before),
                balance_after=float(t.balance_after),
                created_at=t.created_at,
                related_rental_id=t.related_rental_id,
                tracking_id=t.tracking_id,
                first_name=getattr(users_map.get(t.user_id), "first_name", None),
                last_name=getattr(users_map.get(t.user_id), "last_name", None),
                phone_number=getattr(users_map.get(t.user_id), "phone_number", None),
            )
            for t in items
        ]
    }


@WalletRouter.get("/transactions/summary/by-user/{user_id}", response_model=WalletTransactionsSummaryOut)
def get_transactions_summary_by_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    type: Optional[WalletTransactionType] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    day: Optional[int] = Query(None),
):
    _ensure_admin(current_user)
    
    try:
        user_uuid = safe_sid_to_uuid(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат ID")
    
    q = db.query(WalletTransaction).filter(WalletTransaction.user_id == user_uuid)
    if type is not None:
        q = q.filter(WalletTransaction.transaction_type == type)
    q = _apply_date_filters(q, date_from=date_from, date_to=date_to, year=year, month=month, day=day)
    items = q.all()
    income = sum(float(t.amount) for t in items if float(t.amount) > 0)
    outcome = sum(-float(t.amount) for t in items if float(t.amount) < 0)
    by_type: dict[str, float] = {}
    for t in items:
        key = t.transaction_type.value
        by_type[key] = by_type.get(key, 0.0) + float(t.amount)
    return WalletTransactionsSummaryOut(income=income, outcome=outcome, by_type=by_type, count=len(items))


@WalletRouter.get("/users/balances", response_model=WalletUsersBalancesOut)
def get_users_balances(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    min_balance: Optional[float] = Query(None),
    max_balance: Optional[float] = Query(None),
    phone_search: Optional[str] = Query(None),
):
    _ensure_admin(current_user)
    q = db.query(User)
    if min_balance is not None:
        q = q.filter(User.wallet_balance >= min_balance)
    if max_balance is not None:
        q = q.filter(User.wallet_balance <= max_balance)
    if phone_search:
        q = q.filter(User.phone_number.contains(phone_search))
    users = q.order_by(User.id.asc()).offset(offset).limit(limit).all()
    return {
        "users": [
            {
                "id": uuid_to_sid(u.id),
                "phone_number": u.phone_number,
                "role": u.role.value if hasattr(u.role, "value") else str(u.role),
                "wallet_balance": float(u.wallet_balance or 0),
                "first_name": u.first_name,
                "last_name": u.last_name,
            }
            for u in users
        ]
    }


