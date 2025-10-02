from datetime import datetime
import enum

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, Enum
from sqlalchemy.orm import relationship

from app.dependencies.database.database import Base


class WalletTransactionType(enum.Enum):
    # Пополнения/возвраты
    DEPOSIT = "deposit"
    PROMO_BONUS = "promo_bonus"
    REFUND = "refund"

    # Клиент: аренда/штрафы/доставка
    RENT_OPEN_FEE = "rent_open_fee"
    RENT_WAITING_FEE = "rent_waiting_fee"
    RENT_MINUTE_CHARGE = "rent_minute_charge"
    RENT_OVERTIME_FEE = "rent_overtime_fee"
    RENT_DISTANCE_FEE = "rent_distance_fee"
    RENT_BASE_CHARGE = "rent_base_charge"
    RENT_FUEL_FEE = "rent_fuel_fee"
    DELIVERY_FEE = "delivery_fee"

    # Механик доставки: штрафы
    DELIVERY_PENALTY = "delivery_penalty"

    # Дополнительно
    MANUAL_ADJUSTMENT = "manual_adjustment"  # ручная корректировка админом
    DAMAGE_PENALTY = "damage_penalty"        # штраф за повреждения
    FINE_PENALTY = "fine_penalty"            # штрафы ГАИ/штрафы регуляторов


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    transaction_type = Column(
        Enum(
            WalletTransactionType,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            name="wallet_transaction_type",
        ),
        nullable=False,
    )
    description = Column(String, nullable=True)
    balance_before = Column(Numeric(10, 2), nullable=False)
    balance_after = Column(Numeric(10, 2), nullable=False)
    related_rental_id = Column(Integer, ForeignKey("rental_history.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User")
    rental = relationship("RentalHistory")


