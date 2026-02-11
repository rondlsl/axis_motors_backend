"""
Утилиты для пересчёта и верификации баланса пользователя при завершении аренды.

Основные функции:
- recalculate_user_balance_before_rental: Пересчёт транзакций ДО аренды
- verify_and_fix_rental_balance: Полная верификация и исправление баланса, транзакций и полей аренды
"""

import logging
from typing import Dict, Any
from decimal import Decimal
from sqlalchemy.orm import Session

from app.models.user_model import User
from app.models.history_model import RentalHistory, RentalType
from app.models.car_model import Car
from app.models.wallet_transaction_model import WalletTransaction, WalletTransactionType
from app.utils.time_utils import get_local_time

logger = logging.getLogger(__name__)


def to_float(value) -> float:
    """Безопасное преобразование Decimal/float/int в float."""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def recalculate_user_balance_before_rental(
    user: User, 
    rental: RentalHistory, 
    db: Session,
    initial_balance: float = 0.0
) -> Dict[str, Any]:
    """
    Пересчитывает balance_before и balance_after для всех транзакций пользователя
    ДО текущей аренды, затем возвращает правильный баланс перед арендой.
    
    Алгоритм:
    1. Получает все транзакции пользователя, отсортированные по created_at
    2. Находит транзакции ДО текущей аренды (по времени reservation_time аренды)
    3. Пересчитывает balance_before/balance_after для этих транзакций
    4. Возвращает баланс ДО аренды для дальнейших расчётов
    
    :param user: Пользователь
    :param rental: Текущая аренда
    :param db: Сессия базы данных
    :param initial_balance: Начальный баланс перед первой транзакцией
    :return: Словарь с результатами пересчёта
    """
    try:
        # Время начала аренды для определения "до аренды"
        rental_start_time = rental.reservation_time or rental.start_time
        
        if not rental_start_time:
            logger.warning(f"Rental {rental.id} has no reservation_time or start_time, skipping recalculation")
            return {
                "success": False,
                "error": "No rental start time",
                "balance_before_rental": to_float(user.wallet_balance)
            }
        
        # Получаем ВСЕ транзакции пользователя, отсортированные по времени
        all_transactions = (
            db.query(WalletTransaction)
            .filter(WalletTransaction.user_id == user.id)
            .order_by(WalletTransaction.created_at.asc())
            .all()
        )
        
        if not all_transactions:
            logger.info(f"User {user.id} has no transactions, balance_before_rental = {initial_balance}")
            return {
                "success": True,
                "balance_before_rental": initial_balance,
                "transactions_before_rental": 0,
                "transactions_total": 0
            }
        
        # Пересчитываем ВСЕ транзакции с начала
        running_balance = float(initial_balance)
        balance_before_rental = running_balance
        transactions_before_rental = 0
        
        for tx in all_transactions:
            # Проверяем, относится ли транзакция к текущей аренде
            is_current_rental_tx = tx.related_rental_id == rental.id
            
            # Если это транзакция ДО текущей аренды - пересчитываем
            if not is_current_rental_tx and tx.created_at < rental_start_time:
                old_before = tx.balance_before
                old_after = tx.balance_after
                
                tx.balance_before = running_balance
                tx.balance_after = running_balance + to_float(tx.amount)
                running_balance = tx.balance_after
                transactions_before_rental += 1
                
                # Логируем только если были изменения
                if old_before != tx.balance_before or old_after != tx.balance_after:
                    logger.debug(
                        f"TX {tx.id}: balance_before {old_before} -> {tx.balance_before}, "
                        f"balance_after {old_after} -> {tx.balance_after}"
                    )
            elif not is_current_rental_tx:
                # Транзакция после начала аренды, но не связанная с ней
                # Тоже пересчитываем для консистентности
                tx.balance_before = running_balance
                tx.balance_after = running_balance + to_float(tx.amount)
                running_balance = tx.balance_after
            # Транзакции текущей аренды пропускаем - они будут пересчитаны отдельно
        
        # Баланс ДО текущей аренды = running_balance после всех транзакций до аренды
        # Нужно найти баланс ПЕРЕД первой транзакцией текущей аренды
        rental_transactions = [tx for tx in all_transactions if tx.related_rental_id == rental.id]
        
        if rental_transactions:
            # Находим первую транзакцию аренды
            first_rental_tx = min(rental_transactions, key=lambda x: x.created_at)
            
            # Баланс до аренды = balance_before первой транзакции аренды
            # Но нам нужно пересчитать его на основе предыдущих транзакций
            
            # Пересчитываем с начала до первой транзакции аренды
            running_balance = float(initial_balance)
            for tx in all_transactions:
                if tx.created_at < first_rental_tx.created_at and tx.related_rental_id != rental.id:
                    tx.balance_before = running_balance
                    tx.balance_after = running_balance + to_float(tx.amount)
                    running_balance = tx.balance_after
            
            balance_before_rental = running_balance
        else:
            # Нет транзакций по аренде, берём текущий running_balance
            balance_before_rental = running_balance
        
        logger.info(
            f"User {user.id} balance recalculated: "
            f"initial={initial_balance}, "
            f"balance_before_rental={balance_before_rental}, "
            f"transactions_before_rental={transactions_before_rental}"
        )
        
        return {
            "success": True,
            "balance_before_rental": balance_before_rental,
            "transactions_before_rental": transactions_before_rental,
            "transactions_total": len(all_transactions),
            "initial_balance": initial_balance
        }
        
    except Exception as e:
        logger.error(f"Error recalculating user balance: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "balance_before_rental": to_float(user.wallet_balance)
        }


def verify_and_fix_rental_balance(
    user: User,
    rental: RentalHistory,
    car: Car,
    db: Session
) -> Dict[str, Any]:
    """
    Полная верификация и исправление баланса, транзакций и полей аренды.
    
    Алгоритм:
    1. Пересчитывает все транзакции ДО аренды → получает баланс ДО аренды
    2. Собирает суммы из транзакций по типам (base, open, waiting, overtime, fuel, etc.)
    3. Синхронизирует поля аренды с суммами из транзакций
    4. Пересчитывает balance_before/balance_after для всех транзакций аренды
    5. Обновляет total_price, already_payed
    6. Исправляет баланс пользователя
    
    :param user: Пользователь
    :param rental: Аренда
    :param car: Автомобиль
    :param db: Сессия БД
    :return: Результат верификации
    """
    try:
        # ========== 1. ПЕРЕСЧЁТ БАЛАНСА ДО АРЕНДЫ ==========
        recalc_result = recalculate_user_balance_before_rental(user, rental, db, initial_balance=0.0)
        
        if not recalc_result.get("success"):
            logger.warning(f"Failed to recalculate balance before rental: {recalc_result.get('error')}")
            return {
                "success": False,
                "error": recalc_result.get("error"),
                "corrected": False
            }
        
        balance_before_rental = recalc_result["balance_before_rental"]
        logger.info(f"📊 Balance BEFORE rental {rental.id}: {balance_before_rental:.2f}₸")
        
        # ========== 2. ПОЛУЧАЕМ ВСЕ ТРАНЗАКЦИИ АРЕНДЫ ==========
        rental_transactions = (
            db.query(WalletTransaction)
            .filter(WalletTransaction.related_rental_id == rental.id)
            .order_by(WalletTransaction.created_at.asc())
            .all()
        )
        
        # ========== 3. СОБИРАЕМ СУММЫ ИЗ ТРАНЗАКЦИЙ ПО ТИПАМ ==========
        tx_sums = {
            "base_price": 0,
            "open_fee": 0,
            "delivery_fee": 0,
            "waiting_fee": 0,
            "overtime_fee": 0,
            "fuel_fee": 0,
            "distance_fee": 0,
            "driver_fee": 0,
            "minute_charge": 0,
            "rebooking_fee": 0,
            "cancellation_fee": 0,
            "other": 0
        }
        
        for tx in rental_transactions:
            tx_amount = to_float(tx.amount)
            amount = abs(tx_amount) if tx_amount < 0 else 0
            tx_type = tx.transaction_type
            
            if tx_type == WalletTransactionType.RENT_BASE_CHARGE:
                # Определяем что это: base_price, open_fee или delivery_fee по описанию
                desc = (tx.description or "").lower()
                if "открыт" in desc or "open" in desc:
                    tx_sums["open_fee"] += amount
                elif "доставк" in desc or "delivery" in desc:
                    tx_sums["delivery_fee"] += amount
                else:
                    tx_sums["base_price"] += amount
            elif tx_type == WalletTransactionType.RENT_MINUTE_CHARGE:
                tx_sums["minute_charge"] += amount
            elif tx_type == WalletTransactionType.RENT_WAITING_FEE:
                tx_sums["waiting_fee"] += amount
            elif tx_type == WalletTransactionType.RENT_OVERTIME_FEE:
                tx_sums["overtime_fee"] += amount
            elif tx_type == WalletTransactionType.RENT_FUEL_FEE:
                tx_sums["fuel_fee"] += amount
            elif tx_type == WalletTransactionType.DELIVERY_FEE:
                tx_sums["delivery_fee"] += amount
            elif tx_type == WalletTransactionType.RESERVATION_REBOOKING_FEE:
                tx_sums["rebooking_fee"] += amount
            elif tx_type == WalletTransactionType.RESERVATION_CANCELLATION_FEE:
                tx_sums["cancellation_fee"] += amount
            else:
                tx_sums["other"] += amount
        
        # Для поминутного тарифа base_price = minute_charge
        if rental.rental_type == RentalType.MINUTES:
            tx_sums["base_price"] = tx_sums["minute_charge"]
        
        logger.info(f"📋 Transaction sums for rental {rental.id}: {tx_sums}")
        
        # ========== 4. СИНХРОНИЗИРУЕМ ПОЛЯ АРЕНДЫ С ТРАНЗАКЦИЯМИ ==========
        old_rental_values = {
            "base_price": rental.base_price,
            "open_fee": rental.open_fee,
            "delivery_fee": rental.delivery_fee,
            "waiting_fee": rental.waiting_fee,
            "overtime_fee": rental.overtime_fee,
            "distance_fee": rental.distance_fee,
            "driver_fee": rental.driver_fee,
            "rebooking_fee": rental.rebooking_fee,
            "total_price": rental.total_price,
            "already_payed": rental.already_payed
        }
        
        # Обновляем поля аренды на основе транзакций
        rental.base_price = int(tx_sums["base_price"])
        rental.open_fee = int(tx_sums["open_fee"])
        rental.delivery_fee = int(tx_sums["delivery_fee"])
        rental.waiting_fee = int(tx_sums["waiting_fee"])
        rental.overtime_fee = int(tx_sums["overtime_fee"])
        rental.rebooking_fee = int(tx_sums["rebooking_fee"])
        
        # distance_fee и driver_fee оставляем как есть, если не было транзакций
        if tx_sums["distance_fee"] > 0:
            rental.distance_fee = int(tx_sums["distance_fee"])
        if tx_sums["driver_fee"] > 0:
            rental.driver_fee = int(tx_sums["driver_fee"])
        
        # Пересчитываем total_price
        # Учитываем fuel_fee из транзакций (он не хранится в отдельном поле аренды)
        fuel_fee_from_tx = int(tx_sums["fuel_fee"])
        
        rental.total_price = (
            (rental.base_price or 0) +
            (rental.open_fee or 0) +
            (rental.delivery_fee or 0) +
            (rental.waiting_fee or 0) +
            (rental.overtime_fee or 0) +
            (rental.distance_fee or 0) +
            (rental.driver_fee or 0) +
            (rental.rebooking_fee or 0) +
            fuel_fee_from_tx
        )
        
        # already_payed = сумма всех списаний из транзакций
        total_charged = sum(tx_sums.values())
        rental.already_payed = int(total_charged)
        
        # Логируем изменения в полях аренды
        changes_made = []
        for field, old_val in old_rental_values.items():
            new_val = getattr(rental, field)
            if old_val != new_val:
                changes_made.append(f"{field}: {old_val} -> {new_val}")
        
        if changes_made:
            logger.info(f"🔧 Rental {rental.id} fields updated: {', '.join(changes_made)}")
        
        # ========== 5. ПЕРЕСЧИТЫВАЕМ balance_before/balance_after ДЛЯ ВСЕХ ТРАНЗАКЦИЙ ПЕРИОДА АРЕНДЫ ==========
        # BUGFIX: Раньше здесь итерировались только rental_transactions (related_rental_id == rental.id).
        # Из-за этого пополнения (DEPOSIT) во время аренды не учитывались в running_balance,
        # что приводило к "аннулированию" пополнений при расчёте expected_balance_after.
        # Теперь обрабатываем ВСЕ транзакции пользователя за период аренды в хронологическом порядке.
        # Это безопасно, т.к. мы не меняем amount — только пересчитываем balance_before/balance_after.
        
        rental_end_time = rental.end_time or get_local_time()
        
        if rental_transactions:
            # Граница = created_at первой транзакции аренды.
            # recalculate_user_balance_before_rental уже учёл все не-арендные транзакции
            # с created_at < first_rental_tx_time, поэтому начинаем ровно с этой точки.
            first_rental_tx_time = min(tx.created_at for tx in rental_transactions)
            
            logger.info(
                f"📅 Rental {rental.id} period: "
                f"{first_rental_tx_time.strftime('%Y-%m-%d %H:%M:%S')} -> "
                f"{rental_end_time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            
            # ВСЕ транзакции пользователя за период аренды:
            # списания аренды, пополнения, любые другие операции.
            # Не фильтруем по related_rental_id — именно это исправляет баг.
            # Сортировка по (created_at, id) для детерминированности при одинаковых timestamps.
            all_rental_period_transactions = (
                db.query(WalletTransaction)
                .filter(
                    WalletTransaction.user_id == user.id,
                    WalletTransaction.created_at >= first_rental_tx_time,
                    WalletTransaction.created_at <= rental_end_time
                )
                .order_by(WalletTransaction.created_at.asc(), WalletTransaction.id.asc())
                .all()
            )
            
            logger.info(
                f"📋 Found {len(all_rental_period_transactions)} transactions in rental period "
                f"(including {len(rental_transactions)} rental-specific)"
            )
            
            # Логируем типы транзакций для диагностики
            tx_types = {}
            for tx in all_rental_period_transactions:
                tx_type = tx.transaction_type.value
                tx_types[tx_type] = tx_types.get(tx_type, 0) + 1
            
            if tx_types:
                types_str = ", ".join([f"{t}:{c}" for t, c in tx_types.items()])
                logger.debug(f"  Transaction types in period: {types_str}")
                
        else:
            # Нет транзакций аренды — balance_before_rental уже учитывает всё,
            # нечего пересчитывать в периоде аренды.
            all_rental_period_transactions = []
            logger.info(f"📋 No rental transactions found for rental {rental.id}")
        
        running_balance = balance_before_rental
        tx_corrections = []
        
        logger.debug(f"🔄 Starting rental period balance calculation from {running_balance:.2f}")
        
        for i, tx in enumerate(all_rental_period_transactions, 1):
            old_before = tx.balance_before
            old_after = tx.balance_after
            
            tx.balance_before = running_balance
            tx.balance_after = running_balance + to_float(tx.amount)
            running_balance = tx.balance_after
            
            # Подробное логирование каждой транзакции
            is_rental_tx = tx.related_rental_id == rental.id
            tx_marker = "🔗" if is_rental_tx else "💰"
            
            logger.debug(
                f"  {i:2d}. {tx_marker} TX {tx.id} ({tx.transaction_type.value:20s}) "
                f"| before={old_before:8.2f} -> {tx.balance_before:8.2f} "
                f"| amount={to_float(tx.amount):+7.2f} "
                f"| after={old_after:8.2f} -> {tx.balance_after:8.2f} "
                f"| running={running_balance:8.2f}"
            )
            
            if abs(to_float(old_before) - tx.balance_before) > 0.01 or abs(to_float(old_after) - tx.balance_after) > 0.01:
                tx_corrections.append({
                    "tx_id": str(tx.id),
                    "type": tx.transaction_type.value,
                    "amount": to_float(tx.amount),
                    "old_before": old_before,
                    "new_before": tx.balance_before,
                    "old_after": old_after,
                    "new_after": tx.balance_after
                })
        
        if tx_corrections:
            logger.info(f"🔧 {len(tx_corrections)} transactions corrected for rental {rental.id}")
            for corr in tx_corrections:
                logger.debug(
                    f"  TX {corr['tx_id']} ({corr['type']}): "
                    f"before {corr['old_before']} -> {corr['new_before']}, "
                    f"after {corr['old_after']} -> {corr['new_after']}"
                )
        
        # ========== 6. ПЕРЕСЧИТЫВАЕМ ТРАНЗАКЦИИ ПОСЛЕ АРЕНДЫ ==========
        # Все транзакции пользователя после окончания аренды (любого типа).
        # Используем strict > чтобы не было overlap с шагом 5 (который использует <=).
        # Не фильтруем по related_rental_id — все пост-арендные транзакции должны
        # быть в единой цепочке running_balance.
        post_rental_transactions = (
            db.query(WalletTransaction)
            .filter(
                WalletTransaction.user_id == user.id,
                WalletTransaction.created_at > rental_end_time
            )
            .order_by(WalletTransaction.created_at.asc(), WalletTransaction.id.asc())
            .all()
        )
        
        logger.info(
            f"📋 Found {len(post_rental_transactions)} post-rental transactions "
            f"after {rental_end_time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        if post_rental_transactions:
            logger.debug(f"🔄 Continuing balance calculation from {running_balance:.2f}")
        
        for i, tx in enumerate(post_rental_transactions, 1):
            old_before = tx.balance_before
            old_after = tx.balance_after
            
            tx.balance_before = running_balance
            tx.balance_after = running_balance + to_float(tx.amount)
            running_balance = tx.balance_after
            
            # Логируем пост-арендные транзакции
            logger.debug(
                f"  POST {i:2d}. TX {tx.id} ({tx.transaction_type.value:20s}) "
                f"| before={old_before:8.2f} -> {tx.balance_before:8.2f} "
                f"| amount={to_float(tx.amount):+7.2f} "
                f"| after={old_after:8.2f} -> {tx.balance_after:8.2f} "
                f"| running={running_balance:8.2f}"
            )
            
            if abs(to_float(old_before) - tx.balance_before) > 0.01 or abs(to_float(old_after) - tx.balance_after) > 0.01:
                logger.debug(
                    f"    Post-rental TX {tx.id} balance corrected: "
                    f"before {old_before} -> {tx.balance_before}, "
                    f"after {old_after} -> {tx.balance_after}"
                )
        
        # ========== 7. ИСПРАВЛЯЕМ БАЛАНС ПОЛЬЗОВАТЕЛЯ ==========
        expected_balance_after = running_balance
        current_balance = to_float(user.wallet_balance)
        difference = expected_balance_after - current_balance
        
        # Итоговое логирование цепочки балансов
        logger.info(
            f"💰 Balance flow for rental {rental.id}: "
            f"before_rental={balance_before_rental:.2f} -> "
            f"after_rental_period={running_balance:.2f} -> "
            f"current={current_balance:.2f} "
            f"(diff={difference:+.2f})"
        )
        
        if abs(difference) > 0.01:
            logger.warning(
                f"⚠️ Balance mismatch for user {user.id}: "
                f"expected={expected_balance_after:.2f}, current={current_balance:.2f}, "
                f"difference={difference:.2f}"
            )
            
            old_balance = user.wallet_balance
            user.wallet_balance = expected_balance_after
            
            logger.info(
                f"✅ Balance corrected for user {user.id}: "
                f"{old_balance} -> {expected_balance_after}"
            )
            
            return {
                "success": True,
                "corrected": True,
                "balance_before_rental": balance_before_rental,
                "expected_balance_after": expected_balance_after,
                "old_balance": current_balance,
                "new_balance": expected_balance_after,
                "difference": difference,
                "rental_transactions_count": len(rental_transactions),
                "post_rental_transactions_count": len(post_rental_transactions),
                "tx_sums": tx_sums,
                "rental_fields_updated": changes_made,
                "tx_corrections_count": len(tx_corrections)
            }
        else:
            logger.info(
                f"✅ Balance verified for user {user.id}: "
                f"balance_before_rental={balance_before_rental:.2f}, "
                f"balance_after={expected_balance_after:.2f}"
            )
            
            return {
                "success": True,
                "corrected": len(changes_made) > 0 or len(tx_corrections) > 0,
                "balance_before_rental": balance_before_rental,
                "expected_balance_after": expected_balance_after,
                "current_balance": current_balance,
                "rental_transactions_count": len(rental_transactions),
                "post_rental_transactions_count": len(post_rental_transactions),
                "tx_sums": tx_sums,
                "rental_fields_updated": changes_made,
                "tx_corrections_count": len(tx_corrections)
            }
            
    except Exception as e:
        logger.error(f"Error verifying rental balance: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "corrected": False
        }
