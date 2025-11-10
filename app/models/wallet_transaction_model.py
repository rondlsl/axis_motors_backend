from datetime import datetime, timedelta
import enum
import uuid

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, Enum, UUID
from sqlalchemy.orm import relationship

from app.dependencies.database.database import Base
from app.utils.short_id import uuid_to_sid


def get_local_time() -> datetime:
    """Возвращает текущее время с смещением +5 часов (Алматинское время)"""
    return datetime.utcnow() + timedelta(hours=5)


class WalletTransactionType(enum.Enum):
    # Пополнения/возвраты
    DEPOSIT = "deposit"
    PROMO_BONUS = "promo_bonus"
    COMPANY_BONUS = "company_bonus"
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
    
    # Владелец
    OWNER_WAITING_FEE_SHARE = "owner_waiting_fee_share"  # 50% от платного ожидания владельцу при отмене


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
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
    related_rental_id = Column(UUID(as_uuid=True), ForeignKey("rental_history.id"), nullable=True)
    tracking_id = Column(String, nullable=True, index=True)  # ID транзакции от платежной системы
    created_at = Column(DateTime, nullable=False, default=get_local_time)

    user = relationship("User")
    rental = relationship("RentalHistory")
    
    @property
    def sid(self) -> str:
        """Короткий ID для использования в API"""
        return uuid_to_sid(self.id)


