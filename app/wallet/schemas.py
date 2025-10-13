from datetime import datetime
from typing import Optional, List, Dict
import uuid

from pydantic import BaseModel
from app.schemas.base import SidMixin


class WalletTransactionOut(SidMixin):
    id: str
    user_id: str
    amount: float
    type: str
    description: Optional[str] = None
    balance_before: float
    balance_after: float
    created_at: datetime
    related_rental_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None

    class Config:
        orm_mode = True


class WalletBalanceOut(BaseModel):
    wallet_balance: float
    last_transaction_at: Optional[datetime]


class WalletStatementMonth(BaseModel):
    year: int
    month: int
    income: float
    outcome: float
    count: int
    first_transaction_at: Optional[datetime]
    last_transaction_at: Optional[datetime]


class WalletStatementOut(BaseModel):
    months: List[WalletStatementMonth]


class WalletTransactionsListOut(BaseModel):
    transactions: List[WalletTransactionOut]


class WalletTransactionsSummaryOut(BaseModel):
    income: float
    outcome: float
    by_type: Dict[str, float]
    count: int


class WalletUserBalanceItem(SidMixin):
    id: str
    phone_number: Optional[str]
    role: Optional[str]
    wallet_balance: float
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    digital_signature: Optional[str] = None


class WalletUsersBalancesOut(BaseModel):
    users: List[WalletUserBalanceItem]


