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
from app.push.utils import send_push_notification_async

from app.core.config import TELEGRAM_BOT_TOKEN

# Кэш флагов уведомлений: rental_id -> flags
_notification_flags: dict[int, dict[str, bool]] = {}


async def billing_job():
    # 1) синхронную часть всё так же в пул потоков
    push_notifications, telegram_alerts = await anyio.to_thread.run_sync(process_rentals_sync)

    # 2) шлём пуши параллельно без последовательного await
    async with anyio.create_task_group() as tg:
        for token, title, body in push_notifications:
            tg.start_soon(send_push_notification_async, token, title, body)

        # 3) шлём телеграм-уведомления тоже параллельно
        async with httpx.AsyncClient() as client:
            for text in telegram_alerts:
                for chat_id in (965048905, 5941825713):
                    tg.start_soon(
                        client.post,
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                        json={"chat_id": chat_id, "text": text}
                    )


def process_rentals_sync() -> tuple[list[tuple[str, str, str]], list[str]]:
    """
    Синхронная часть биллинга:
      1) RESERVED → за 1 мин до ожидания + первое платное списание
      2) IN_USE:
         - MINUTES → списание каждую минуту
         - HOURS/DAYS → пред-уведомление за 10 мин + списание сверхлимита
      3) Уведомления о низком и нулевом балансе
    """
    db = SessionLocal()
    now = datetime.utcnow()
    push_notifications: list[tuple[str, str, str]] = []
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

            # инициализация флагов (если ещё нет)
            flags = _notification_flags.setdefault(rid, {
                "pre_waiting": False,
                "waiting": False,
                "pre_overtime": False,
                "overtime": False,
                "low_balance_1000": False,
                "low_balance_zero": False,
            })

            # === RESERVED: бесплатное ожидание → платное ожидание 0.5*₸/мин ===
            if rental.rental_status == RentalStatus.RESERVED:
                waited = (now - (rental.reservation_time or rental.start_time)).total_seconds() / 60

                # за 1 мин до конца бесплатного ожидания
                if 14 <= waited < 15 and not flags["pre_waiting"] and user.fcm_token:
                    mins_left = math.ceil(15 - waited)
                    push_notifications.append((
                        user.fcm_token,
                        "Скоро начнётся платное ожидание",
                        f"Через {mins_left} мин бесплатного ожидания начнётся списание "
                        f"{math.ceil(car.price_per_minute * 0.5)}₸/мин."
                    ))
                    flags["pre_waiting"] = True

                # списание после 15 мин свободного ожидания
                if waited > 15:
                    extra = math.ceil(waited - 15)
                    fee_total_wait = math.ceil(extra * car.price_per_minute * 0.5)
                    prev_wait = rental.waiting_fee or 0
                    charge = fee_total_wait - prev_wait
                    if charge > 0:
                        rental.waiting_fee = fee_total_wait
                        # пересчет total_price
                        rental.total_price = (
                                (rental.base_price or 0) +
                                (rental.open_fee or 0) +
                                (rental.delivery_fee or 0) +
                                rental.waiting_fee +
                                (rental.overtime_fee or 0) +
                                (rental.distance_fee or 0)
                        )
                        # накапливаем списание
                        rental.already_payed = (rental.already_payed or 0) + charge
                        user.wallet_balance -= charge
                        db.commit()

                        # низкий баланс ≤1000
                        if 0 < user.wallet_balance <= 1000 and not flags["low_balance_1000"] and user.fcm_token:
                            push_notifications.append((
                                user.fcm_token,
                                "Низкий баланс",
                                f"На балансе {int(user.wallet_balance)}₸ — осталось менее 1000₸."
                            ))
                            flags["low_balance_1000"] = True

                        # баланс исчерпан
                        if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
                            push_notifications.append((
                                user.fcm_token,
                                "Баланс исчерпан",
                                "Ваш баланс 0₸ — завершите аренду, чтобы избежать штрафов."
                            ))
                            flags["low_balance_zero"] = True
                            telegram_alerts.append(
                                f"🔔 У клиента (тел.: {user.phone_number}) на авто ID {car.id} баланс исчерпан."
                            )

                        # первое платное списание ожидания
                        if not flags["waiting"] and user.fcm_token:
                            push_notifications.append((
                                user.fcm_token,
                                "Началось платное ожидание",
                                f"Списано за ожидание: {charge}₸ за {extra} мин."
                            ))
                            flags["waiting"] = True

            # === IN_USE: списание по времени аренды ===
            elif rental.rental_status == RentalStatus.IN_USE:
                elapsed = (now - rental.start_time).total_seconds() / 60

                # минуты — ежеминутное списание
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
                                user.fcm_token,
                                "Низкий баланс",
                                f"На балансе {int(user.wallet_balance)}₸ — осталось менее 1000₸."
                            ))
                            flags["low_balance_1000"] = True

                        if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
                            push_notifications.append((
                                user.fcm_token,
                                "Баланс исчерпан",
                                "Ваш баланс 0₸ — завершите аренду."
                            ))
                            flags["low_balance_zero"] = True
                            telegram_alerts.append(
                                f"🔔 У клиента (тел.: {user.phone_number}) на авто ID {car.id} баланс исчерпан."
                            )

                # часы/дни — пред-уведомление за 10 мин + списание сверхлимита
                else:
                    factor = 60 if rental.rental_type == RentalType.HOURS else 1440
                    planned = rental.duration * factor
                    remaining = planned - elapsed

                    # пред-уведомление
                    if 0 < remaining <= 10 and not flags["pre_overtime"] and user.fcm_token:
                        push_notifications.append((
                            user.fcm_token,
                            "Скоро закончится базовый тариф",
                            f"Через {math.ceil(remaining)} мин."
                        ))
                        flags["pre_overtime"] = True

                    # списание овертайма
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
                                    user.fcm_token,
                                    "Низкий баланс",
                                    f"На балансе {int(user.wallet_balance)}₸ — осталось менее 1000₸."
                                ))
                                flags["low_balance_1000"] = True

                            if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
                                push_notifications.append((
                                    user.fcm_token,
                                    "Баланс исчерпан",
                                    "Ваш баланс 0₸ — завершите аренду."
                                ))
                                flags["low_balance_zero"] = True
                                telegram_alerts.append(
                                    f"🔔 У клиента (тел.: {user.phone_number}) на авто ID {car.id} баланс исчерпан."
                                )

                            if not flags["overtime"] and user.fcm_token:
                                push_notifications.append((
                                    user.fcm_token,
                                    "Списания вне тарифа",
                                    f"Списано сверхлимита: {charge}₸ за {extra} мин."
                                ))
                                flags["overtime"] = True

        except Exception as e:
            db.rollback()
            print(f"[Billing error] rental={rental.id}: {e}")

    # очистка флагов для завершённых/отменённых
    for rid in list(_notification_flags):
        if rid not in active_ids:
            _notification_flags.pop(rid)

    db.close()
    return push_notifications, telegram_alerts
