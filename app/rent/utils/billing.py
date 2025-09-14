import asyncio
import math
from datetime import datetime

import anyio
import httpx
from sqlalchemy import or_

from app.dependencies.database.database import SessionLocal
from app.models.car_model import Car
from app.models.history_model import RentalHistory, RentalStatus, RentalType
from app.models.user_model import User, UserRole
from app.push.utils import send_push_to_user_by_id
from app.core.config import TELEGRAM_BOT_TOKEN

# Кэш флагов уведомлений: rental_id -> flags
_notification_flags: dict[int, dict[str, bool]] = {}


async def billing_job():
    """
    Periodic billing job:
      1) Process rentals sync to get push and telegram alerts.
      2) Send push notifications by user_id (fire-and-forget).
      3) Send telegram alerts.
      4) Yield control to event loop.
    """
    # 1) Run sync processing in thread pool
    push_notifications, telegram_alerts = await anyio.to_thread.run_sync(process_rentals_sync)

    # 2) Open one DB session
    db = SessionLocal()

    # 3) Fire-and-forget push notifications
    for user_id, title, body in push_notifications:
        anyio.start_soon(send_push_to_user_by_id, db, user_id, title, body)

    # 4) Fire-and-forget Telegram alerts
    async def _send_telegram(text: str, chat_id: int):
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text}
            )

    for text in telegram_alerts:
        for chat_id in (965048905, 5941825713):
            anyio.start_soon(_send_telegram, text, chat_id)

    # 5) Yield back to event loop
    await asyncio.sleep(0)


def process_rentals_sync() -> tuple[list[tuple[int, str, str]], list[str]]:
    """
    Синхронная часть биллинга:
      1) RESERVED → за 1 мин до ожидания + первое платное списание
      2) IN_USE:
         - MINUTES → списание каждую минуту
         - HOURS/DAYS → пред-уведомление за 10 мин + списание сверхлимита
      3) Уведомления о низком и нулевом балансе

    Returns:
      push_notifications: list of (user_id, title, body)
      telegram_alerts: list of telegram messages
    """
    db = SessionLocal()
    now = datetime.utcnow()
    push_notifications: list[tuple[int, str, str]] = []
    telegram_alerts: list[str] = []

    rentals = (
        db.query(RentalHistory)
        .join(User, RentalHistory.user_id == User.id)
        .join(Car, RentalHistory.car_id == Car.id)
        .filter(
            RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE]),
            User.role != UserRole.MECHANIC,
            or_(
                Car.owner_id.is_(None),
                RentalHistory.user_id != Car.owner_id
            ),
        )
        .all()
    )
    active_ids = {r.id for r in rentals}

    for rental in rentals:
        try:
            user = rental.user
            car = rental.car
            rid = rental.id

            flags = _notification_flags.setdefault(rid, {
                "pre_waiting": False,
                "waiting": False,
                "pre_overtime": False,
                "overtime": False,
                "low_balance_1000": False,
                "low_balance_zero": False,
            })

            # === RESERVED stage ===
            if rental.rental_status == RentalStatus.RESERVED:
                waited = (now - (rental.reservation_time or rental.start_time)).total_seconds() / 60

                # Pre‑waiting alert
                if 14 <= waited < 15 and not flags["pre_waiting"] and user.fcm_token:
                    mins_left = math.ceil(15 - waited)
                    push_notifications.append((
                        user.id,
                        "Скоро начнётся платное ожидание",
                        f"Через {mins_left} мин бесплатного ожидания начнётся списание "
                        f"{math.ceil(car.price_per_minute * 0.5)}₸/мин."
                    ))
                    flags["pre_waiting"] = True

                # Charge waiting fee after 15 min
                if waited > 15:
                    extra = math.ceil(waited - 15)
                    fee_total_wait = math.ceil(extra * car.price_per_minute * 0.5)
                    prev_wait = rental.waiting_fee or 0
                    charge = fee_total_wait - prev_wait
                    if charge > 0:
                        rental.waiting_fee = fee_total_wait
                        rental.total_price = (
                                (rental.base_price or 0) +
                                (rental.open_fee or 0) +
                                (rental.delivery_fee or 0) +
                                rental.waiting_fee +
                                (rental.overtime_fee or 0) +
                                (rental.distance_fee or 0)
                        )
                        rental.already_payed = (rental.already_payed or 0) + charge
                        user.wallet_balance -= charge
                        db.commit()

                        # Low balance ≤1000
                        if 0 < user.wallet_balance <= 1000 and not flags["low_balance_1000"] and user.fcm_token:
                            push_notifications.append((
                                user.id,
                                "Низкий баланс",
                                f"На балансе {int(user.wallet_balance)}₸ — осталось менее 1000₸."
                            ))
                            flags["low_balance_1000"] = True

                        # Balance zero
                        if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
                            push_notifications.append((
                                user.id,
                                "Баланс исчерпан",
                                "Ваш баланс 0₸ — завершите аренду, чтобы избежать штрафов."
                            ))
                            flags["low_balance_zero"] = True
                            telegram_alerts.append(
                                f"🔔 У клиента (тел.: {user.phone_number}) на авто ID {car.id} баланс исчерпан."
                            )

                        # First paid waiting
                        if not flags["waiting"] and user.fcm_token:
                            push_notifications.append((
                                user.id,
                                "Началось платное ожидание",
                                f"Списано за ожидание: {charge}₸ за {extra} мин."
                            ))
                            flags["waiting"] = True

            # === IN_USE stage ===
            elif rental.rental_status == RentalStatus.IN_USE:
                elapsed = (now - rental.start_time).total_seconds() / 60

                if rental.rental_type == RentalType.MINUTES:
                    elapsed_min = math.ceil(elapsed)
                    due = elapsed_min * car.price_per_minute
                    prev = rental.overtime_fee or 0
                    charge = due - prev
                    if charge > 0:
                        rental.overtime_fee = due
                        rental.total_price = (
                                (rental.base_price or 0) +
                                (rental.open_fee or 0) +
                                (rental.delivery_fee or 0) +
                                (rental.waiting_fee or 0) +
                                rental.overtime_fee +
                                (rental.distance_fee or 0)
                        )
                        rental.already_payed = (rental.already_payed or 0) + charge
                        user.wallet_balance -= charge
                        db.commit()

                        if 0 < user.wallet_balance <= 1000 and not flags["low_balance_1000"] and user.fcm_token:
                            push_notifications.append((
                                user.id,
                                "Низкий баланс",
                                f"На балансе {int(user.wallet_balance)}₸ — осталось менее 1000₸."
                            ))
                            flags["low_balance_1000"] = True

                        if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
                            push_notifications.append((
                                user.id,
                                "Баланс исчерпан",
                                "Ваш баланс 0₸ — завершите аренду."
                            ))
                            flags["low_balance_zero"] = True
                            telegram_alerts.append(
                                f"🔔 У клиента (тел.: {user.phone_number}) на авто ID {car.id} баланс исчерпан."
                            )

                else:
                    factor = 60 if rental.rental_type == RentalType.HOURS else 1440
                    planned = rental.duration * factor
                    remaining = planned - elapsed

                    # Pre-overtime alert
                    if 0 < remaining <= 10 and not flags["pre_overtime"] and user.fcm_token:
                        push_notifications.append((
                            user.id,
                            "Скоро закончится базовый тариф",
                            f"Через {math.ceil(remaining)} мин."
                        ))
                        flags["pre_overtime"] = True

                    # Overtime charges
                    overtime = max(0, elapsed - planned)
                    if overtime > 0:
                        extra = math.ceil(overtime)
                        fee_total_ov = math.ceil(extra * car.price_per_minute)
                        prev_ov = rental.overtime_fee or 0
                        charge = fee_total_ov - prev_ov
                        if charge > 0:
                            rental.overtime_fee = fee_total_ov
                            rental.total_price = (
                                    (rental.base_price or 0) +
                                    (rental.open_fee or 0) +
                                    (rental.delivery_fee or 0) +
                                    (rental.waiting_fee or 0) +
                                    rental.overtime_fee +
                                    (rental.distance_fee or 0)
                            )
                            rental.already_payed = (rental.already_payed or 0) + charge
                            user.wallet_balance -= charge
                            db.commit()

                            if 0 < user.wallet_balance <= 1000 and not flags["low_balance_1000"] and user.fcm_token:
                                push_notifications.append((
                                    user.id,
                                    "Низкий баланс",
                                    f"На балансе {int(user.wallet_balance)}₸ — осталось менее 1000₸."
                                ))
                                flags["low_balance_1000"] = True

                            if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
                                push_notifications.append((
                                    user.id,
                                    "Баланс исчерпан",
                                    "Ваш баланс 0₸ — завершите аренду."
                                ))
                                flags["low_balance_zero"] = True
                                telegram_alerts.append(
                                    f"🔔 У клиента (тел.: {user.phone_number}) на авто ID {car.id} баланс исчерпан."
                                )

                            if not flags["overtime"] and user.fcm_token:
                                push_notifications.append((
                                    user.id,
                                    "Списания вне тарифта",
                                    f"Списано сверхлимита: {charge}₸ за {extra} мин."
                                ))
                                flags["overtime"] = True

        except Exception as e:
            db.rollback()
            print("[Billing error] rental={rental.id}: {e}")

    # Очистка флагов для завершённых/отменённых арен
    for rid in list(_notification_flags):
        if rid not in active_ids:
            _notification_flags.pop(rid)

    db.close()
    return push_notifications, telegram_alerts
