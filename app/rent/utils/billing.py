import asyncio
import math
from datetime import datetime

import anyio
import httpx
from app.dependencies.database.database import SessionLocal
from app.models.car_model import Car
from app.models.history_model import RentalHistory, RentalStatus, RentalType
from app.models.user_model import User, UserRole
from app.push.utils import send_push_notification_async

from app.core.config import TELEGRAM_BOT_TOKEN

# Кэш флагов уведомлений:
# rental_id -> {
#   'pre_waiting': bool,
#   'waiting': bool,
#   'pre_overtime': bool,
#   'overtime': bool,
#   'low_balance_1000': bool,
#   'low_balance_zero': bool
# }
_notification_flags: dict[int, dict[str, bool]] = {}


async def rental_billing_loop():
    """
    Фон: каждые 10 секунд запускаем обработку и рассылаем накопленные пуши,
    а также отправляем телеграм-уведомления, если баланс нулевой.
    """
    while True:
        await asyncio.sleep(10)
        # process_rentals_sync вернёт два списка: push-уведомления и telegram-уведомления
        push_notifications, telegram_alerts = await anyio.to_thread.run_sync(process_rentals_sync)

        # 1) сначала отправляем все push-уведомления
        for token, title, body in push_notifications:
            await send_push_notification_async(token, title, body)

        # 2) затем отправляем все собранные telegram-сообщения
        if telegram_alerts:
            async with httpx.AsyncClient() as client:
                for text in telegram_alerts:
                    await client.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                        json={"chat_id": 965048905, "text": text}
                    )
                    await client.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                        json={"chat_id": 5941825713, "text": text}
                    )


def process_rentals_sync() -> tuple[
    list[tuple[str, str, str]],
    list[str]
]:
    """
    Синхронно обрабатываем аренды:
      1) RESERVED → за 1 мин до платного ожидания и при первом платном шаге
      2) IN_USE → за 10 мин до конца базового тарифа и при первом шаге сверх тарифа
      3) Low-balance → когда на балансе ≤ 1000 ₸ и когда баланс исчерпан
    Возвращает два списка:
      - push_notifications: список (fcm_token, title, body)
      - telegram_alerts: список текста сообщений для Telegram
    """
    db = SessionLocal()
    now = datetime.utcnow()
    push_notifications: list[tuple[str, str, str]] = []
    telegram_alerts: list[str] = []

    # получаем все активные аренды (кроме механиков)
    rentals = (
        db.query(RentalHistory)
        .join(User, RentalHistory.user_id == User.id)
        .join(Car, RentalHistory.car_id == Car.id)
        .filter(
            RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE]),
            User.role != UserRole.MECHANIC,
            RentalHistory.user_id != Car.owner_id
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
                    push_notifications.append((
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
                        rental.waiting_fee = fee_total
                        rental.total_price = (
                                (rental.base_price or 0)
                                + (rental.open_fee or 0)
                                + (rental.delivery_fee or 0)
                                + (rental.waiting_fee or 0)
                                + (rental.overtime_fee or 0)
                                + (rental.distance_fee or 0)
                        )
                        user.wallet_balance -= charge
                        db.commit()

                        # ── уведомление при низком балансе ≤ 1000 ₸ ────────────────
                        if (
                                user.wallet_balance <= 1000
                                and user.wallet_balance > 0
                                and not flags["low_balance_1000"]
                                and user.fcm_token
                        ):
                            push_notifications.append((
                                user.fcm_token,
                                "Низкий баланс",
                                f"На вашем балансе {int(user.wallet_balance)} ₸ — осталось менее 1000 ₸. Пополните баланс."
                            ))
                            flags["low_balance_1000"] = True

                        # ── уведомление при исчерпании баланса ─────────────────────
                        if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
                            # пуш
                            push_notifications.append((
                                user.fcm_token,
                                "Баланс исчерпан",
                                "Ваш баланс 0 ₸ – завершите аренду, чтобы избежать штрафов."
                            ))
                            flags["low_balance_zero"] = True

                            # формируем Telegram-сообщение об обнулении баланса
                            # предполагаем, в User есть поле phone_number
                            text = (
                                f"🔔 У клиента (телефон: {user.phone_number})\n"
                                f"на автомобиле ID {car.id} баланс исчерпан.\n"
                                "Нужно срочно связаться."
                            )
                            telegram_alerts.append(text)

                        # пуш только при первом платном списании
                        if not flags["waiting"] and user.fcm_token:
                            push_notifications.append((
                                user.fcm_token,
                                "Началось платное ожидание",
                                f"Первые {extra} мин платного ожидания — списано {charge} ₸."
                            ))
                            flags["waiting"] = True

            # 2) IN_USE: сверх тарифа
            elif rental.rental_status == RentalStatus.IN_USE:
                elapsed = (now - rental.start_time).total_seconds() / 60

                if rental.rental_type == RentalType.MINUTES:
                    # сколько уже прошло минут
                    elapsed_minutes = math.ceil(elapsed)
                    due_total = int(elapsed_minutes * car.price_per_minute)
                    already = rental.already_payed or 0
                    if due_total > already:
                        charge = due_total - already
                        rental.already_payed = due_total
                        rental.overtime_fee = due_total
                        rental.total_price = (
                                (rental.base_price or 0)
                                + (rental.open_fee or 0)
                                + (rental.delivery_fee or 0)
                                + (rental.waiting_fee or 0)
                                + (rental.overtime_fee or 0)
                                + (rental.distance_fee or 0)
                        )
                        user.wallet_balance -= charge
                        db.commit()

                        if (
                                user.wallet_balance <= 1000
                                and user.wallet_balance > 0
                                and not flags["low_balance_1000"]
                                and user.fcm_token
                        ):
                            push_notifications.append((
                                user.fcm_token,
                                "Низкий баланс",
                                f"На вашем балансе {int(user.wallet_balance)} ₸ — осталось менее 1000 ₸. Пополните баланс."
                            ))
                            flags["low_balance_1000"] = True

                        if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
                            # пуш
                            push_notifications.append((
                                user.fcm_token,
                                "Баланс исчерпан",
                                "Ваш баланс 0 ₸ – завершите аренду, чтобы избежать штрафов."
                            ))
                            flags["low_balance_zero"] = True

                            # Telegram-сообщение
                            text = (
                                f"🔔 У клиента (телефон: {user.phone_number})\n"
                                f"на автомобиле ID {car.id} баланс исчерпан.\n"
                                "Нужно срочно связаться."
                            )
                            telegram_alerts.append(text)

                # вычисляем минуты базового периода
                factor = 60 if rental.rental_type == RentalType.HOURS else 1440
                planned = rental.duration * factor
                remaining = planned - elapsed

                # за 10 мин до конца базового тарифа
                if remaining <= 10 and remaining > 0 and not flags["pre_overtime"] and user.fcm_token:
                    push_notifications.append((
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
                        rental.overtime_fee = due_total
                        rental.total_price = (
                                (rental.base_price or 0)
                                + (rental.open_fee or 0)
                                + (rental.delivery_fee or 0)
                                + (rental.waiting_fee or 0)
                                + (rental.overtime_fee or 0)
                                + (rental.distance_fee or 0)
                        )
                        user.wallet_balance -= charge
                        db.commit()

                        if (
                                user.wallet_balance <= 1000
                                and user.wallet_balance > 0
                                and not flags["low_balance_1000"]
                                and user.fcm_token
                        ):
                            push_notifications.append((
                                user.fcm_token,
                                "Низкий баланс",
                                f"На вашем балансе {int(user.wallet_balance)} ₸ — осталось менее 1000 ₸. Пополните баланс."
                            ))
                            flags["low_balance_1000"] = True

                        if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
                            # пуш
                            push_notifications.append((
                                user.fcm_token,
                                "Баланс исчерпан",
                                "Ваш баланс 0 ₸ – завершите аренду, чтобы избежать штрафов."
                            ))
                            flags["low_balance_zero"] = True

                            # Telegram-сообщение
                            text = (
                                f"🔔 У клиента (телефон: {user.phone_number})\n"
                                f"на автомобиле ID {car.id} баланс исчерпан.\n"
                                "Нужно срочно связаться."
                            )
                            telegram_alerts.append(text)

                        # пуш только при первом шаге сверх тарифа
                        if not flags["overtime"] and user.fcm_token:
                            push_notifications.append((
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
    return push_notifications, telegram_alerts
