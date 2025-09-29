from typing import Optional

from sqlalchemy.orm import Session

from app.models.wallet_transaction_model import WalletTransaction, WalletTransactionType
from app.models.history_model import RentalHistory
from app.models.user_model import User


def record_wallet_transaction(
    db: Session,
    *,
    user: User,
    amount: int | float,
    ttype: WalletTransactionType,
    description: Optional[str] = None,
    related_rental: Optional[RentalHistory] = None,
    balance_before_override: Optional[float] = None,
) -> WalletTransaction:
    balance_before = balance_before_override if balance_before_override is not None else (user.wallet_balance or 0)
    # В проекте баланс хранится как Numeric(10,2), поддерживаем int -> float
    new_balance = (float(balance_before) + float(amount))

    tx = WalletTransaction(
        user_id=user.id,
        amount=amount,
        transaction_type=ttype,
        description=description,
        balance_before=balance_before,
        balance_after=new_balance,
        related_rental_id=related_rental.id if related_rental else None,
    )
    db.add(tx)
    # Обновление баланса на вызывающей стороне уже произведено.
    return tx


