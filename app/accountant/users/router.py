"""
Router для работы с пользователями для бухгалтеров
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from math import ceil

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_accountant
from app.models.user_model import User
from app.models.wallet_transaction_model import WalletTransaction
from app.utils.short_id import uuid_to_sid, safe_sid_to_uuid
from app.admin.users.schemas import WalletTransactionSchema, WalletTransactionPaginationSchema

accountant_users_router = APIRouter(tags=["Accountant Users"])


@accountant_users_router.get("/users/{user_id}/transactions", response_model=WalletTransactionPaginationSchema)
async def get_user_transactions(
    user_id: str,
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(20, ge=1, le=100, description="Количество элементов на странице"),
    current_user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db)
):
    """
    Получение истории транзакций пользователя для бухгалтеров
    """
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
        
    query = db.query(WalletTransaction).filter(WalletTransaction.user_id == user.id)
    
    query = query.order_by(desc(WalletTransaction.created_at), desc(WalletTransaction.id))
    
    total_count = query.count()
    transactions = query.offset((page - 1) * limit).limit(limit).all()
    
    items = []
    for tx in transactions:
        tx_data = {
            "id": uuid_to_sid(tx.id),
            "amount": float(tx.amount),
            "transaction_type": tx.transaction_type.value if hasattr(tx.transaction_type, "value") else str(tx.transaction_type),
            "description": tx.description,
            "balance_before": float(tx.balance_before),
            "balance_after": float(tx.balance_after),
            "tracking_id": tx.tracking_id,
            "created_at": tx.created_at,
            "related_rental_id": uuid_to_sid(tx.related_rental_id) if tx.related_rental_id else None
        }
        items.append(WalletTransactionSchema(**tx_data))
        
    return {
        "items": items,
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": ceil(total_count / limit) if limit > 0 else 0,
        "wallet_balance": float(user.wallet_balance) if user.wallet_balance else 0.0
    }
