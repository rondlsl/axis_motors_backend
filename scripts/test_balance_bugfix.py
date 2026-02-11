#!/usr/bin/env python3
"""
Мини-тест для демонстрации корректности исправления бага в verify_and_fix_rental_balance.

Баг: пополнения (DEPOSIT) во время аренды не учитывались в running_balance,
что приводило к "аннулированию" пополнений.

Тест моделирует логику running_balance БЕЗ подключения к БД.
"""

from datetime import datetime, timedelta


def to_float(value) -> float:
    if value is None:
        return 0.0
    return float(value)


class FakeTx:
    """Имитация WalletTransaction."""
    def __init__(self, tx_id, amount, created_at, related_rental_id=None, tx_type="UNKNOWN"):
        self.id = tx_id
        self.amount = amount
        self.created_at = created_at
        self.related_rental_id = related_rental_id
        self.transaction_type = tx_type
        self.balance_before = None
        self.balance_after = None

    def __repr__(self):
        return (
            f"TX(id={self.id}, type={self.transaction_type}, amount={self.amount:+.0f}, "
            f"before={self.balance_before}, after={self.balance_after})"
        )


def simulate_old_logic(balance_before_rental, rental_transactions, post_rental_transactions):
    """Старая логика: только rental_transactions в running_balance."""
    running = balance_before_rental

    for tx in rental_transactions:
        tx.balance_before = running
        tx.balance_after = running + to_float(tx.amount)
        running = tx.balance_after

    for tx in post_rental_transactions:
        tx.balance_before = running
        tx.balance_after = running + to_float(tx.amount)
        running = tx.balance_after

    return running


def simulate_new_logic(balance_before_rental, all_rental_period_txs, post_rental_transactions):
    """Новая логика: ВСЕ транзакции периода аренды в running_balance."""
    running = balance_before_rental

    for tx in all_rental_period_txs:
        tx.balance_before = running
        tx.balance_after = running + to_float(tx.amount)
        running = tx.balance_after

    for tx in post_rental_transactions:
        tx.balance_before = running
        tx.balance_after = running + to_float(tx.amount)
        running = tx.balance_after

    return running


def test_deposit_during_rental():
    """
    Сценарий:
      Старт баланса: 10 000
      Во время аренды: +20 000 (DEPOSIT)
      Списание аренды: -10 000 (RENT_BASE_CHARGE)

    Ожидаемый финальный баланс: 20 000
    """
    print("=" * 60)
    print("ТЕСТ: Пополнение во время аренды")
    print("=" * 60)

    RENTAL_ID = "rental-001"
    now = datetime.now()

    balance_before_rental = 10_000.0

    # Транзакции во время аренды (хронологический порядок)
    deposit = FakeTx(
        tx_id="tx-deposit",
        amount=20_000,
        created_at=now + timedelta(minutes=5),
        related_rental_id=None,
        tx_type="DEPOSIT"
    )
    charge = FakeTx(
        tx_id="tx-charge",
        amount=-10_000,
        created_at=now + timedelta(minutes=10),
        related_rental_id=RENTAL_ID,
        tx_type="RENT_BASE_CHARGE"
    )

    # --- Старая логика ---
    rental_txs_old = [charge]  # только related_rental_id == RENTAL_ID
    post_txs_old = []

    old_result = simulate_old_logic(balance_before_rental, rental_txs_old, post_txs_old)

    print(f"\n--- СТАРАЯ ЛОГИКА (баг) ---")
    print(f"  balance_before_rental: {balance_before_rental:.0f}")
    print(f"  rental_transactions:   [RENT_BASE_CHARGE -10000]")
    print(f"  deposit +20000:        НЕ УЧТЁН")
    print(f"  expected_balance:      {old_result:.0f}")
    print(f"  CORRECT?               {'✅' if old_result == 20_000 else '❌ НЕВЕРНО (ожидалось 20000)'}")

    # --- Новая логика ---
    # Пересоздаём объекты (balance_before/after сброшены)
    deposit2 = FakeTx("tx-deposit", 20_000, now + timedelta(minutes=5), None, "DEPOSIT")
    charge2 = FakeTx("tx-charge", -10_000, now + timedelta(minutes=10), RENTAL_ID, "RENT_BASE_CHARGE")

    all_period_txs = sorted([deposit2, charge2], key=lambda t: (t.created_at, t.id))
    post_txs_new = []

    new_result = simulate_new_logic(balance_before_rental, all_period_txs, post_txs_new)

    print(f"\n--- НОВАЯ ЛОГИКА (исправление) ---")
    print(f"  balance_before_rental: {balance_before_rental:.0f}")
    print(f"  all_rental_period_txs: [DEPOSIT +20000, RENT_BASE_CHARGE -10000]")
    print(f"  expected_balance:      {new_result:.0f}")
    print(f"  CORRECT?               {'✅' if new_result == 20_000 else '❌ НЕВЕРНО (ожидалось 20000)'}")

    print(f"\n  Цепочка running_balance:")
    for tx in all_period_txs:
        print(f"    {tx.transaction_type:25s} | before={tx.balance_before:>10.0f} | amount={tx.amount:>+8.0f} | after={tx.balance_after:>10.0f}")

    assert new_result == 20_000, f"FAIL: expected 20000, got {new_result}"
    print(f"\n✅ ТЕСТ ПРОЙДЕН")
    return True


def test_no_deposit_during_rental():
    """
    Сценарий без пополнений (регрессия):
      Старт: 10 000
      Списание: -5 000
      Списание: -3 000

    Ожидаемый финальный баланс: 2 000
    """
    print("\n" + "=" * 60)
    print("ТЕСТ: Без пополнений (регрессия)")
    print("=" * 60)

    RENTAL_ID = "rental-002"
    now = datetime.now()

    balance_before_rental = 10_000.0

    charge1 = FakeTx("tx-c1", -5_000, now + timedelta(minutes=1), RENTAL_ID, "RENT_BASE_CHARGE")
    charge2 = FakeTx("tx-c2", -3_000, now + timedelta(minutes=5), RENTAL_ID, "RENT_MINUTE_CHARGE")

    all_period_txs = sorted([charge1, charge2], key=lambda t: (t.created_at, t.id))
    result = simulate_new_logic(balance_before_rental, all_period_txs, [])

    print(f"\n  balance_before_rental: {balance_before_rental:.0f}")
    print(f"  expected_balance:      {result:.0f}")
    print(f"  CORRECT?               {'✅' if result == 2_000 else '❌ НЕВЕРНО (ожидалось 2000)'}")

    assert result == 2_000, f"FAIL: expected 2000, got {result}"
    print(f"\n✅ ТЕСТ ПРОЙДЕН")
    return True


def test_multiple_deposits_and_charges():
    """
    Сценарий с несколькими пополнениями и списаниями:
      Старт: 5 000
      +10 000 (DEPOSIT)
      -8 000 (RENT_BASE_CHARGE)
      +15 000 (DEPOSIT)
      -12 000 (RENT_MINUTE_CHARGE)

    Ожидаемый: 5000 + 10000 - 8000 + 15000 - 12000 = 10 000
    """
    print("\n" + "=" * 60)
    print("ТЕСТ: Несколько пополнений и списаний")
    print("=" * 60)

    RENTAL_ID = "rental-003"
    now = datetime.now()

    balance_before_rental = 5_000.0

    txs = [
        FakeTx("tx-d1", 10_000, now + timedelta(minutes=1), None, "DEPOSIT"),
        FakeTx("tx-c1", -8_000, now + timedelta(minutes=2), RENTAL_ID, "RENT_BASE_CHARGE"),
        FakeTx("tx-d2", 15_000, now + timedelta(minutes=3), None, "DEPOSIT"),
        FakeTx("tx-c2", -12_000, now + timedelta(minutes=4), RENTAL_ID, "RENT_MINUTE_CHARGE"),
    ]

    all_period_txs = sorted(txs, key=lambda t: (t.created_at, t.id))
    result = simulate_new_logic(balance_before_rental, all_period_txs, [])

    print(f"\n  balance_before_rental: {balance_before_rental:.0f}")
    print(f"  Цепочка:")
    for tx in all_period_txs:
        print(f"    {tx.transaction_type:25s} | before={tx.balance_before:>10.0f} | amount={tx.amount:>+8.0f} | after={tx.balance_after:>10.0f}")
    print(f"  expected_balance:      {result:.0f}")
    print(f"  CORRECT?               {'✅' if result == 10_000 else '❌ НЕВЕРНО (ожидалось 10000)'}")

    assert result == 10_000, f"FAIL: expected 10000, got {result}"
    print(f"\n✅ ТЕСТ ПРОЙДЕН")
    return True


def test_same_timestamp_determinism():
    """
    Сценарий: транзакции с одинаковым timestamp.
    Порядок должен быть детерминированным (по id).
    """
    print("\n" + "=" * 60)
    print("ТЕСТ: Одинаковый timestamp (детерминированность)")
    print("=" * 60)

    RENTAL_ID = "rental-004"
    now = datetime.now()
    same_time = now + timedelta(minutes=5)

    balance_before_rental = 10_000.0

    txs = [
        FakeTx("tx-aaa", 20_000, same_time, None, "DEPOSIT"),
        FakeTx("tx-bbb", -5_000, same_time, RENTAL_ID, "RENT_BASE_CHARGE"),
    ]

    all_period_txs = sorted(txs, key=lambda t: (t.created_at, t.id))
    result = simulate_new_logic(balance_before_rental, all_period_txs, [])

    print(f"\n  balance_before_rental: {balance_before_rental:.0f}")
    print(f"  Цепочка (sorted by created_at, id):")
    for tx in all_period_txs:
        print(f"    {tx.transaction_type:25s} id={tx.id:10s} | before={tx.balance_before:>10.0f} | amount={tx.amount:>+8.0f} | after={tx.balance_after:>10.0f}")
    print(f"  expected_balance:      {result:.0f}")
    expected = 10_000 + 20_000 - 5_000
    print(f"  CORRECT?               {'✅' if result == expected else f'❌ НЕВЕРНО (ожидалось {expected})'}")

    assert result == expected, f"FAIL: expected {expected}, got {result}"
    print(f"\n✅ ТЕСТ ПРОЙДЕН")
    return True


def test_no_transactions():
    """Сценарий: нет транзакций вообще."""
    print("\n" + "=" * 60)
    print("ТЕСТ: Нет транзакций")
    print("=" * 60)

    balance_before_rental = 10_000.0
    result = simulate_new_logic(balance_before_rental, [], [])

    print(f"\n  balance_before_rental: {balance_before_rental:.0f}")
    print(f"  expected_balance:      {result:.0f}")
    print(f"  CORRECT?               {'✅' if result == 10_000 else '❌'}")

    assert result == 10_000
    print(f"\n✅ ТЕСТ ПРОЙДЕН")
    return True


def test_post_rental_chain():
    """
    Сценарий: транзакции во время И после аренды.
      Старт: 10 000
      Во время: +20 000, -10 000
      После: +5 000

    Ожидаемый: 10000 + 20000 - 10000 + 5000 = 25 000
    """
    print("\n" + "=" * 60)
    print("ТЕСТ: Цепочка running_balance через период + пост-аренда")
    print("=" * 60)

    RENTAL_ID = "rental-005"
    now = datetime.now()
    rental_end = now + timedelta(hours=1)

    balance_before_rental = 10_000.0

    period_txs = [
        FakeTx("tx-d1", 20_000, now + timedelta(minutes=5), None, "DEPOSIT"),
        FakeTx("tx-c1", -10_000, now + timedelta(minutes=30), RENTAL_ID, "RENT_BASE_CHARGE"),
    ]
    post_txs = [
        FakeTx("tx-d2", 5_000, rental_end + timedelta(minutes=10), None, "DEPOSIT"),
    ]

    period_sorted = sorted(period_txs, key=lambda t: (t.created_at, t.id))
    post_sorted = sorted(post_txs, key=lambda t: (t.created_at, t.id))

    result = simulate_new_logic(balance_before_rental, period_sorted, post_sorted)

    print(f"\n  balance_before_rental: {balance_before_rental:.0f}")
    print(f"  Цепочка периода аренды:")
    for tx in period_sorted:
        print(f"    {tx.transaction_type:25s} | before={tx.balance_before:>10.0f} | amount={tx.amount:>+8.0f} | after={tx.balance_after:>10.0f}")
    print(f"  Цепочка пост-аренда:")
    for tx in post_sorted:
        print(f"    {tx.transaction_type:25s} | before={tx.balance_before:>10.0f} | amount={tx.amount:>+8.0f} | after={tx.balance_after:>10.0f}")
    print(f"  expected_balance:      {result:.0f}")
    print(f"  CORRECT?               {'✅' if result == 25_000 else '❌ НЕВЕРНО (ожидалось 25000)'}")

    assert result == 25_000, f"FAIL: expected 25000, got {result}"
    print(f"\n✅ ТЕСТ ПРОЙДЕН")
    return True


if __name__ == "__main__":
    tests = [
        test_deposit_during_rental,
        test_no_deposit_during_rental,
        test_multiple_deposits_and_charges,
        test_same_timestamp_determinism,
        test_no_transactions,
        test_post_rental_chain,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except AssertionError as e:
            print(f"\n❌ ТЕСТ ПРОВАЛЕН: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"ИТОГО: {passed} passed, {failed} failed из {len(tests)}")
    print("=" * 60)

    if failed > 0:
        exit(1)
    else:
        print("\n🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")
        exit(0)
