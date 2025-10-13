from datetime import datetime
from typing import Optional, List, Dict
import uuid

from pydantic import BaseModel


class WalletTransactionOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    amount: float
    type: str
    description: Optional[str] = None
    balance_before: float
    balance_after: float
    created_at: datetime
    related_rental_id: Optional[uuid.UUID] = None
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


class WalletUserBalanceItem(BaseModel):
    id: uuid.UUID
    phone_number: Optional[str]
    role: Optional[str]
    wallet_balance: float
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class WalletUsersBalancesOut(BaseModel):
    users: List[WalletUserBalanceItem]


