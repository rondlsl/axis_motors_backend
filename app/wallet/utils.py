from typing import Optional

from sqlalchemy.orm import Session

from app.models.wallet_transaction_model import WalletTransaction, WalletTransactionType
from app.models.history_model import RentalHistory
from app.models.user_model import User
from app.utils.time_utils import get_local_time


def _normalize_wallet_transaction_type(raw_type: WalletTransactionType | str) -> WalletTransactionType:
    """Accepts enum or string and returns a valid WalletTransactionType.

    Supports:
    - Enum instance (returned as-is)
    - Enum name strings (e.g. "RENT_BASE_CHARGE")
    - Enum value strings (e.g. "rent_base_charge")
    """
    if isinstance(raw_type, WalletTransactionType):
        return raw_type

    # Try match by name (case-insensitive)
    upper = str(raw_type).strip().upper()
    for member in WalletTransactionType:
        if member.name.upper() == upper:
            return member

    # Try match by value (case-sensitive first, then lower())
    value = str(raw_type).strip()
    for member in WalletTransactionType:
        if member.value == value:
            return member
    lower_value = value.lower()
    for member in WalletTransactionType:
        if member.value == lower_value:
            return member

    raise ValueError(f"Unknown wallet transaction type: {raw_type}")


def record_wallet_transaction(
    db: Session,
    *,
    user: User,
    amount: int | float,
    ttype: WalletTransactionType | str,
    description: Optional[str] = None,
    related_rental: Optional[RentalHistory] = None,
    balance_before_override: Optional[float] = None,
    tracking_id: Optional[str] = None,
) -> WalletTransaction:
    balance_before = balance_before_override if balance_before_override is not None else (user.wallet_balance or 0)
    # В проекте баланс хранится как Numeric(10,2), поддерживаем int -> float
    new_balance = (float(balance_before) + float(amount))

    normalized_type = _normalize_wallet_transaction_type(ttype)

    tx = WalletTransaction(
        user_id=user.id,
        amount=amount,
        transaction_type=normalized_type,
        description=description,
        balance_before=balance_before,
        balance_after=new_balance,
        related_rental_id=related_rental.id if related_rental else None,
        tracking_id=tracking_id,
        created_at=get_local_time(),
    )
    db.add(tx)
    # Обновление баланса на вызывающей стороне уже произведено.
    return tx


