import asyncio
import math
from datetime import datetime

import anyio

from app.dependencies.database.database import SessionLocal
from app.models.car_model import Car
from app.models.history_model import RentalHistory, RentalStatus, RentalType
from app.models.user_model import User, UserRole
from app.push.utils import send_push_notification_async

# Кэш флагов уведомлений:
# rental_id -> {
#   'pre_waiting': bool,
#   'waiting': bool,
#   'pre_overtime': bool,
#   'overtime': bool
# }
_notification_flags: dict[int, dict[str, bool]] = {}


async def rental_billing_loop():
    """
    Фон: каждые 10 секунд запускаем обработку и рассылаем накопленные пуши.
    """
    while True:
        await asyncio.sleep(10)
        notifications = await anyio.to_thread.run_sync(process_rentals_sync)
        for token, title, body in notifications:
            await send_push_notification_async(token, title, body)


def process_rentals_sync() -> list[tuple[str, str, str]]:
    """
    Синхронно обрабатываем аренды:
      1) RESERVED → за 1 мин до платного ожидания и при первом платном шаге
      2) IN_USE → за 10 мин до конца базового тарифа и при первом шаге сверх тарифа
      3) Low-balance → когда на балансе ≤ 1000 ₸ и когда баланс исчерпан
    Списания и commit выполняются сразу, пуши собираются и отдаются в loop.
    """
    db = SessionLocal()
    now = datetime.utcnow()
    notifications: list[tuple[str, str, str]] = []

    # получаем все активные аренды (кроме механиков)
    rentals = (
        db.query(RentalHistory)
        .join(User, RentalHistory.user_id == User.id)
        .filter(
            RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE]),
            User.role != UserRole.MECHANIC
        )
        .all()
    )
    active_ids = {r.id for r in rentals}

    for rental in rentals:
        try:
            user = rental.user
            car = rental.car
            rid = rental.id

            # инициализация флагов
            if rid not in _notification_flags:
                _notification_flags[rid] = {
                    "pre_waiting": False,
                    "waiting": False,
                    "pre_overtime": False,
                    "overtime": False,
                    "low_balance_1000": False,
                    "low_balance_zero": False,
                }
            flags = _notification_flags[rid]

            # 1) RESERVED: ожидание
            if rental.rental_status == RentalStatus.RESERVED:
                waited = (now - (rental.reservation_time or rental.start_time)).total_seconds() / 60

                # за 1 минуту до конца бесплатного ожидания
                if waited >= 14 and waited < 15 and not flags["pre_waiting"] and user.fcm_token:
                    mins_left = math.ceil(15 - waited)
                    notifications.append((
                        user.fcm_token,
                        "Скоро начнётся платное ожидание",
                        f"Через {mins_left} мин бесплатного ожидания начнётся списание {int(car.price_per_minute * 0.5)} ₸/мин."
                    ))
                    flags["pre_waiting"] = True

                # после 15 мин: списание
                if waited > 15:
                    extra = math.ceil(waited - 15)
                    fee_total = int(extra * car.price_per_minute * 0.5)
                    already = rental.already_payed or 0
                    if fee_total > already:
                        charge = fee_total - already
                        rental.already_payed = fee_total
                        user.wallet_balance -= charge
                        db.commit()

                        # ── уведомление при низком балансе ≤ 1000 ₸ ────────────────
                        if (
                                user.wallet_balance <= 1000
                                and user.wallet_balance > 0
                                and not flags["low_balance_1000"]
                                and user.fcm_token
                        ):
                            notifications.append((
                                user.fcm_token,
                                "Низкий баланс",
                                f"На вашем балансе {int(user.wallet_balance)} ₸ — осталось менее 1000 ₸. Пополните баланс."
                            ))
                            flags["low_balance_1000"] = True

                        # ── уведомление при исчерпании баланса ─────────────────────
                        if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
                            notifications.append((
                                user.fcm_token,
                                "Баланс исчерпан",
                                "Ваш баланс 0 ₸ – завершите аренду, чтобы избежать штрафов."
                            ))
                            flags["low_balance_zero"] = True

                        # пуш только при первом платном списании
                        if not flags["waiting"] and user.fcm_token:
                            notifications.append((
                                user.fcm_token,
                                "Началось платное ожидание",
                                f"Первые {extra} мин платного ожидания — списано {charge} ₸."
                            ))
                            flags["waiting"] = True

            # 2) IN_USE: сверх тарифа
            elif rental.rental_status == RentalStatus.IN_USE:
                elapsed = (now - rental.start_time).total_seconds() / 60

                if rental.rental_type == RentalType.MINUTES:
                    # поминутный тариф без базового периода — списание в момент старта не нужно
                    continue

                # вычисляем минуты базового периода
                factor = 60 if rental.rental_type == RentalType.HOURS else 1440
                planned = rental.duration * factor
                remaining = planned - elapsed

                # за 10 мин до конца базового тарифа
                if remaining <= 10 and remaining > 0 and not flags["pre_overtime"] and user.fcm_token:
                    notifications.append((
                        user.fcm_token,
                        "Скоро закончится базовый тариф",
                        f"Через {math.ceil(remaining)} мин закончится базовый тариф. Далее плата {car.price_per_minute} ₸/мин."
                    ))
                    flags["pre_overtime"] = True

                # списываем сверх лимита
                overtime = max(0, elapsed - planned)
                if overtime > 0:
                    extra = math.ceil(overtime)
                    due_total = int(extra * car.price_per_minute)
                    already = rental.already_payed or 0
                    if due_total > already:
                        charge = due_total - already
                        rental.already_payed = due_total
                        user.wallet_balance -= charge
                        db.commit()

                        # ── уведомление при низком балансе ≤ 1000 ₸ ────────────────
                        if (
                                user.wallet_balance <= 1000
                                and user.wallet_balance > 0
                                and not flags["low_balance_1000"]
                                and user.fcm_token
                        ):
                            notifications.append((
                                user.fcm_token,
                                "Низкий баланс",
                                f"На вашем балансе {int(user.wallet_balance)} ₸ — осталось менее 1000 ₸. Пополните баланс."
                            ))
                            flags["low_balance_1000"] = True

                        # ── уведомление при исчерпании баланса ─────────────────────
                        if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
                            notifications.append((
                                user.fcm_token,
                                "Баланс исчерпан",
                                "Ваш баланс 0 ₸ – завершите аренду, чтобы избежать штрафов."
                            ))
                            flags["low_balance_zero"] = True

                        # пуш только при первом шаге сверх тарифа
                        if not flags["overtime"] and user.fcm_token:
                            notifications.append((
                                user.fcm_token,
                                "Списания вне тарифа",
                                f"Списываем сверх тарифа: {extra} мин — {charge} ₸."
                            ))
                            flags["overtime"] = True

        except Exception as e:
            db.rollback()
            print(f"[Billing error] rental={rental.id}: {e}")

    # очищаем флаги для завершённых/отменённых аренд
    for rid in list(_notification_flags):
        if rid not in active_ids:
            _notification_flags.pop(rid, None)

    db.close()
    return notifications
