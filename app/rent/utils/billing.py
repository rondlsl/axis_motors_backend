import asyncio
import math
from datetime import datetime

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.dependencies.database.database import SessionLocal
from app.models.car_model import Car
from app.models.history_model import RentalHistory, RentalStatus, RentalType
from app.models.user_model import User, UserRole
from app.push.utils import send_push_to_user_by_id, send_localized_notification_to_user
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
    push_notifications, telegram_alerts = await asyncio.to_thread(process_rentals_sync)

    # 2) Open one DB session
    db = SessionLocal()

    # 3) Fire-and-forget push notifications
    for notification in push_notifications:
        if len(notification) == 5:  # (user_id, translation_key, status, **kwargs)
            user_id, translation_key, status, kwargs = notification
            asyncio.create_task(send_localized_notification_to_user(db, user_id, translation_key, status, **kwargs))
        elif len(notification) == 4:  # (user_id, title, body, status) - для обратной совместимости
            user_id, title, body, status = notification
            asyncio.create_task(send_push_to_user_by_id(db, user_id, title, body, status))
        else:  # (user_id, title, body) - для обратной совместимости
            user_id, title, body = notification
            asyncio.create_task(send_push_to_user_by_id(db, user_id, title, body))

    # 4) Fire-and-forget Telegram alerts
    async def _send_telegram(text: str, chat_id: int):
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text}
            )

    for text in telegram_alerts:
        for chat_id in (965048905, 5941825713):
            asyncio.create_task(_send_telegram(text, chat_id))

    await send_localized_billing_notifications(db)
    
    # 6) Yield back to event loop
    await asyncio.sleep(0)


async def send_localized_billing_notifications(db: Session):
    """
    Отправляет локализованные уведомления о биллинге всем пользователям
    """
    try:
        # Находим пользователей с низким балансом
        users_low_balance = (
            db.query(User)
            .filter(
                User.wallet_balance <= 1000,
                User.wallet_balance > 0,
                User.fcm_token.isnot(None),
                User.is_active == True
            )
            .all()
        )
        
        # Находим пользователей с нулевым балансом
        users_zero_balance = (
            db.query(User)
            .filter(
                User.wallet_balance <= 0,
                User.fcm_token.isnot(None),
                User.is_active == True
            )
            .all()
        )
        
        # Отправляем уведомления о низком балансе
        for user in users_low_balance:
            await send_localized_notification_to_user(
                db, 
                user.id, 
                "low_balance", 
                "low_balance",
                balance=int(user.wallet_balance)
            )
        
        # Отправляем уведомления о нулевом балансе
        for user in users_zero_balance:
            await send_localized_notification_to_user(
                db, 
                user.id, 
                "balance_exhausted", 
                "balance_exhausted"
            )
                        
    except Exception as e:
        print(f"[Billing notifications error]: {e}")


def process_rentals_sync() -> tuple[list[tuple[int, str, str]], list[str]]:
    """
    Синхронная часть биллинга:
      1) RESERVED → за 1 мин до ожидания + первое платное списание
      2) IN_USE:
         - MINUTES → списание каждую минуту
         - HOURS/DAYS → пред-уведомление за 10 мин + списание сверхлимита
      3) Уведомления о низком и нулевом балансе
      4) Штрафы механиков за задержку доставки

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
            RentalHistory.rental_status.in_([
                RentalStatus.RESERVED, 
                RentalStatus.IN_USE,
                RentalStatus.DELIVERING,
                RentalStatus.DELIVERY_RESERVED,
                RentalStatus.DELIVERING_IN_PROGRESS
            ]),
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
                # Исключаем время доставки из расчета waiting_fee
                base_time = rental.reservation_time or rental.start_time
                if rental.delivery_start_time and rental.delivery_end_time:
                    # Если доставка завершена, считаем время ожидания только до начала доставки
                    base_time = rental.delivery_end_time
                elif rental.delivery_start_time:
                    # Если доставка в процессе, считаем время ожидания только до начала доставки
                    base_time = rental.delivery_start_time
                
                waited = (now - base_time).total_seconds() / 60

                # Pre‑waiting alert
                if 14 <= waited < 15 and not flags["pre_waiting"] and user.fcm_token:
                    mins_left = math.ceil(15 - waited)
                    push_notifications.append((
                        user.id,
                        "pre_waiting_alert",
                        "paid_waiting_soon",
                        {
                            "mins_left": mins_left,
                            "price": math.ceil(car.price_per_minute * 0.5)
                        }
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

                        # Low balance ≤1000 - уведомления отправляются через локализованную функцию
                        if 0 < user.wallet_balance <= 1000 and not flags["low_balance_1000"] and user.fcm_token:
                            flags["low_balance_1000"] = True

                        # Balance zero - уведомления отправляются через локализованную функцию
                        if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
                            flags["low_balance_zero"] = True
                            telegram_alerts.append(
                                f"🔔 У клиента (тел.: {user.phone_number}) на авто ID {car.id} баланс исчерпан."
                            )

                        # First paid waiting
                        if not flags["waiting"] and user.fcm_token:
                            push_notifications.append((
                                user.id,
                                "waiting_started",
                                "paid_waiting_started",
                                {
                                    "charge": charge,
                                    "extra": extra
                                }
                            ))
                            flags["waiting"] = True

            # === DELIVERY stages ===
            elif rental.rental_status in [RentalStatus.DELIVERING, RentalStatus.DELIVERY_RESERVED, RentalStatus.DELIVERING_IN_PROGRESS]:
                # Во время доставки клиент не платит waiting_fee
                # Время доставки исключается из расчета waiting_fee
                base_time = rental.reservation_time or rental.start_time
                if rental.delivery_start_time and rental.delivery_end_time:
                    # Если доставка завершена, считаем время ожидания только до начала доставки
                    base_time = rental.delivery_end_time
                elif rental.delivery_start_time:
                    # Если доставка в процессе, считаем время ожидания только до начала доставки
                    base_time = rental.delivery_start_time
                
                waited = (now - base_time).total_seconds() / 60

                # Pre‑waiting alert (только если доставка еще не началась)
                if not rental.delivery_start_time and 14 <= waited < 15 and not flags["pre_waiting"] and user.fcm_token:
                    mins_left = math.ceil(15 - waited)
                    push_notifications.append((
                        user.id,
                        "pre_waiting_alert",
                        "paid_waiting_soon",
                        {
                            "mins_left": mins_left,
                            "price": math.ceil(car.price_per_minute * 0.5)
                        }
                    ))
                    flags["pre_waiting"] = True

                # Charge waiting fee after 15 min (только если доставка еще не началась)
                if not rental.delivery_start_time and waited > 15:
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
                        user.wallet_balance -= charge
                        db.commit()

                        # Low balance ≤1000 - уведомления отправляются через локализованную функцию
                        if 0 < user.wallet_balance <= 1000 and not flags["low_balance_1000"] and user.fcm_token:
                            flags["low_balance_1000"] = True

                        # Balance zero - уведомления отправляются через локализованную функцию
                        if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
                            flags["low_balance_zero"] = True
                            telegram_alerts.append(
                                f"🔔 У клиента (тел.: {user.phone_number}) на авто ID {car.id} баланс исчерпан."
                            )

                        # First paid waiting
                        if not flags["waiting"] and user.fcm_token:
                            push_notifications.append((
                                user.id,
                                "waiting_started",
                                "paid_waiting_started",
                                {
                                    "charge": charge,
                                    "extra": extra
                                }
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
                            flags["low_balance_1000"] = True

                        if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
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
                            "pre_overtime_alert",
                            "basic_tariff_ending_soon",
                            {
                                "remaining": math.ceil(remaining)
                            }
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
                                flags["low_balance_1000"] = True

                            if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
                                flags["low_balance_zero"] = True
                                telegram_alerts.append(
                                    f"🔔 У клиента (тел.: {user.phone_number}) на авто ID {car.id} баланс исчерпан."
                                )

                            if not flags["overtime"] and user.fcm_token:
                                push_notifications.append((
                                    user.id,
                                    "overtime_charges",
                                    "out_of_tariff_charges",
                                    {
                                        "charge": charge,
                                        "extra": extra
                                    }
                                ))
                                flags["overtime"] = True

        except Exception as e:
            db.rollback()
            print("[Billing error] rental={rental.id}: {e}")

    # Обработка штрафов механиков за задержку доставки
    try:
        # Находим доставки, которые превысили 1.5 часа
        overdue_deliveries = db.query(RentalHistory).filter(
            RentalHistory.rental_status == RentalStatus.DELIVERING_IN_PROGRESS,
            RentalHistory.delivery_start_time.isnot(None),
            RentalHistory.delivery_penalty_fee == 0  # Еще не начислен штраф
        ).all()
        
        for rental in overdue_deliveries:
            if rental.delivery_start_time:
                delivery_duration_minutes = (now - rental.delivery_start_time).total_seconds() / 60
                if delivery_duration_minutes > 90:  # 1.5 часа
                    # Рассчитываем штраф
                    penalty_minutes = delivery_duration_minutes - 90
                    penalty_fee = int(penalty_minutes * 1000)  # 1000 тенге за минуту
                    
                    # Находим механика
                    mechanic = db.query(User).filter(User.id == rental.delivery_mechanic_id).first()
                    if mechanic:
                        # Списываем штраф с механика
                        mechanic.wallet_balance -= penalty_fee
                        rental.delivery_penalty_fee = penalty_fee
                        
                        # Уведомляем механика о штрафе (будет отправлено через локализованную функцию)
                        push_notifications.append((
                            mechanic.id,
                            "delivery_delay_penalty",
                            "delivery_delay_penalty",
                            {
                                "penalty_fee": penalty_fee,
                                "penalty_minutes": f"{penalty_minutes:.1f}"
                            }
                        ))
                                        
                        # Уведомляем в Telegram
                        telegram_alerts.append(
                            f"⚠️ Механик {mechanic.phone_number} получил штраф {penalty_fee}₸ "
                            f"за задержку доставки автомобиля ID {rental.car_id} на {penalty_minutes:.1f} мин."
                        )
                        
                        print(f"Штраф за задержку доставки: {penalty_fee}₸ с механика {mechanic.phone_number}")
                        db.commit()
                        
    except Exception as e:
        print(f"[Delivery penalty error]: {e}")
        db.rollback()

    # Очистка флагов для завершённых/отменённых арен
    for rid in list(_notification_flags):
        if rid not in active_ids:
            _notification_flags.pop(rid)

    db.close()
    return push_notifications, telegram_alerts
