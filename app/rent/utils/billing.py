import asyncio
import math
import re
from datetime import datetime
import uuid
from math import ceil, floor

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.dependencies.database.database import SessionLocal
from app.models.car_model import Car, CarBodyType, CarStatus
from app.models.history_model import RentalHistory, RentalStatus, RentalType
from app.models.user_model import User, UserRole
from app.wallet.utils import record_wallet_transaction
from app.models.wallet_transaction_model import WalletTransactionType, WalletTransaction
from app.push.utils import send_push_to_user_by_id, send_localized_notification_to_user
from app.core.config import TELEGRAM_BOT_TOKEN, TELEGRAM_BOT_TOKEN_2, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD
from app.gps_api.utils.auth_api import get_auth_token
from app.gps_api.utils.car_data import send_lock_engine
from app.utils.telegram_logger import telegram_error_logger
from app.websocket.notifications import notify_user_status_update
from app.utils.time_utils import get_local_time

FUEL_PRICE_PER_LITER = 350
ELECTRIC_FUEL_PRICE_PER_LITER = 100

# Кэш флагов уведомлений: rental_id -> flags (в т.ч. timestamp нулевого баланса)
_notification_flags: dict[int, dict[str, object]] = {}


async def billing_job():
    """
    Periodic billing job:
      1) Process rentals sync to get push and telegram alerts.
      2) Send push notifications by user_id (fire-and-forget).
      3) Send telegram alerts.
      4) Yield control to event loop.
    """
    # 1) Run sync processing in thread pool
    push_notifications, telegram_alerts, lock_requests = await asyncio.to_thread(process_rentals_sync)

    # 2) Open one DB session
    db = SessionLocal()

    # 3) Fire-and-forget push notifications
    for notification in push_notifications:
        if len(notification) == 4:  # (user_id, translation_key, status, kwargs)
            user_id, translation_key, status, kwargs = notification
            asyncio.create_task(send_localized_notification_to_user(db, user_id, translation_key, status, **kwargs))
        elif len(notification) == 3:  # (user_id, title, body) - для обратной совместимости
            user_id, title, body = notification
            asyncio.create_task(send_push_to_user_by_id(db, user_id, title, body))
        else:  # Неожиданный формат
            print(f"Unexpected notification format: {notification}")

    # 4) Fire-and-forget Telegram alerts - ОБА БОТА
    async def _send_telegram(text: str, chat_id: int, bot_token: str):
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text}
            )

    # Отправка в первый бот
    for text in telegram_alerts:
        for chat_id in (965048905, 5941825713, 860991388, 1594112444, 808277096):
            asyncio.create_task(_send_telegram(text, chat_id, TELEGRAM_BOT_TOKEN))
    
    # Отправка во второй бот
    for text in telegram_alerts:
        for chat_id in (965048905, 5941825713, 860991388, 1594112444, 808277096):
            asyncio.create_task(_send_telegram(text, chat_id, TELEGRAM_BOT_TOKEN_2))

    # 5) Выполняем блокировки двигателя для просроченных (10+ минут) нулевых балансов
    try:
        if lock_requests:
            auth_token = await get_auth_token("https://regions.glonasssoft.ru", GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
            for imei, car_name, user_id in lock_requests:
                try:
                    await send_lock_engine(imei, auth_token)
                    # Уведомим пользователя в приложение
                    asyncio.create_task(send_localized_notification_to_user(db, user_id, "engine_locked_due_to_balance", "engine_locked_due_to_balance", car_name=car_name))
                    # И в телеграм
                    user = db.query(User).filter(User.id == user_id).first()
                    user_info = f"user_id={user_id}"
                    if user:
                        user_info = f"тел.: {user.phone_number}"
                        if user.email:
                            user_info += f", email: {user.email}"
                        user_info += f", user_id={user_id}"
                    note = f"🛑 Двигатель заблокирован из-за нулевого баланса. Авто: {car_name} (IMEI {imei}), {user_info}"
                    # Отправка в первый бот
                    for chat_id in (965048905, 5941825713, 860991388, 1594112444, 808277096):
                        asyncio.create_task(_send_telegram(note, chat_id, TELEGRAM_BOT_TOKEN))
                    # Отправка во второй бот
                    for chat_id in (965048905, 5941825713, 860991388, 1594112444, 808277096):
                        asyncio.create_task(_send_telegram(note, chat_id, TELEGRAM_BOT_TOKEN_2))
                except Exception as e:
                    err = f"⚠️ Ошибка блокировки двигателя (IMEI {imei}): {e}"
                    # Отправка в первый бот
                    for chat_id in (965048905, 5941825713, 860991388, 1594112444, 808277096):
                        asyncio.create_task(_send_telegram(err, chat_id, TELEGRAM_BOT_TOKEN))
                    # Отправка во второй бот
                    for chat_id in (965048905, 5941825713, 860991388, 1594112444, 808277096):
                        asyncio.create_task(_send_telegram(err, chat_id, TELEGRAM_BOT_TOKEN_2))
                    
                    # Логируем критическую ошибку в Telegram Monitor
                    user = db.query(User).filter(User.id == user_id).first()
                    asyncio.create_task(telegram_error_logger.send_error(
                        error=e,
                        user_info={
                            "id": user_id,
                            "name": f"{user.first_name} {user.last_name}" if user else None,
                            "phone": user.phone_number if user else None,
                            "role": user.role.value if user else None
                        } if user else {"id": user_id},
                        request_info=None,
                        additional_context={
                            "job": "billing_job",
                            "action": "lock_engine",
                            "imei": imei,
                            "car_name": car_name
                        }
                    ))
    except Exception as e:
        error_msg = f"⚠️ Ошибка при обработке блокировок двигателя: {e}"
        
        # Отправка в первый бот
        for chat_id in (965048905, 5941825713, 860991388, 1594112444, 808277096):
            asyncio.create_task(_send_telegram(error_msg, chat_id, TELEGRAM_BOT_TOKEN))
        # Отправка во второй бот
        for chat_id in (965048905, 5941825713, 860991388, 1594112444, 808277096):
            asyncio.create_task(_send_telegram(error_msg, chat_id, TELEGRAM_BOT_TOKEN_2))
        
        # Логируем критическую ошибку в Telegram Monitor
        asyncio.create_task(telegram_error_logger.send_error(
            error=e,
            user_info=None,
            request_info=None,
            additional_context={
                "job": "billing_job",
                "action": "process_lock_requests",
                "lock_requests_count": len(lock_requests) if lock_requests else 0
            }
        ))

    try:
        active_rentals = db.query(RentalHistory).filter(
            RentalHistory.rental_status.in_([
                RentalStatus.RESERVED,
                RentalStatus.IN_USE,
                RentalStatus.DELIVERING,
                RentalStatus.DELIVERY_RESERVED,
                RentalStatus.DELIVERING_IN_PROGRESS
            ])
        ).all()
        
        user_ids = set()
        for rental in active_rentals:
            if rental.user_id:
                user_ids.add(str(rental.user_id))
            car = db.query(Car).filter(Car.id == rental.car_id).first()
            if car and car.owner_id:
                user_ids.add(str(car.owner_id))
        
        for user_id in user_ids:
            asyncio.create_task(notify_user_status_update(user_id))
    except Exception as e:
        print(f"Error sending WebSocket notifications in billing_job: {e}")

    await asyncio.sleep(0)


def process_rentals_sync() -> tuple[list[tuple[int, str, str]], list[str], list[tuple[str, str, int]]]:
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
    now = get_local_time()
    push_notifications: list[tuple[uuid.UUID, str, str]] = []
    telegram_alerts: list[str] = []
    lock_requests: list[tuple[str, str, uuid.UUID]] = []  # (imei, car_name, user_id)

    rental_count = db.query(RentalHistory).count()
    if rental_count == 0:
        print("ℹ️ Таблица rental_history пуста, пропускаем billing_job")
        return [], [], []
    
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
                "telegram_10min_alert": False,
                "low_fuel_alert": False,
            })

            if rental.rental_status == RentalStatus.RESERVED:
                if rental.delivery_end_time:
                    base_time = rental.delivery_end_time
                    waited = (now - base_time).total_seconds() / 60
                elif rental.delivery_start_time:
                    waited = 0
                elif rental.delivery_latitude and rental.delivery_longitude:
                    waited = 0
                else:
                    base_time = rental.reservation_time or rental.start_time
                    waited = (now - base_time).total_seconds() / 60

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

                if waited > 15:
                    if (rental.delivery_start_time and not rental.delivery_end_time) or \
                       (rental.delivery_latitude and rental.delivery_longitude and not rental.delivery_end_time):
                        pass
                    elif rental.delivery_end_time:
                        extra = math.ceil(waited - 15)
                        fee_total_wait = math.ceil(extra * car.price_per_minute * 0.5)
                        prev_wait = rental.waiting_fee or 0
                        charge = fee_total_wait - prev_wait
                        
                        if charge != 0:
                            existing_tx = db.query(WalletTransaction).filter(
                                WalletTransaction.user_id == user.id,
                                WalletTransaction.transaction_type == WalletTransactionType.RENT_WAITING_FEE,
                                WalletTransaction.related_rental_id == rental.id
                            ).first()
                            
                            if existing_tx:
                                current_balance = float(user.wallet_balance or 0)
                                new_balance_after = current_balance - charge
                                
                                existing_tx.amount = -fee_total_wait
                                existing_tx.description = f"Платное ожидание за {extra} мин"
                                existing_tx.balance_after = new_balance_after
                                
                                user.wallet_balance = new_balance_after
                            else:
                                balance_before = float(user.wallet_balance or 0)
                                new_balance = balance_before - fee_total_wait
                                
                                tx = WalletTransaction(
                                    user_id=user.id,
                                    amount=-fee_total_wait,
                                    transaction_type=WalletTransactionType.RENT_WAITING_FEE,
                                    description=f"Платное ожидание за {extra} мин",
                                    balance_before=balance_before,
                                    balance_after=new_balance,
                                    related_rental_id=rental.id,
                                    created_at=get_local_time(),
                                )
                                db.add(tx)
                                user.wallet_balance = new_balance
                            
                            rental.waiting_fee = fee_total_wait
                            rental.total_price = (
                                    (rental.base_price or 0) +
                                    (rental.open_fee or 0) +
                                    (rental.delivery_fee or 0) +
                                    rental.waiting_fee +
                                    (rental.overtime_fee or 0) +
                                    (rental.distance_fee or 0)
                            )
                            db.commit()
                            if user.wallet_balance >= 0:
                                if rental.rental_type in (RentalType.HOURS, RentalType.DAYS):
                                    rental.already_payed = (
                                        (rental.base_price or 0) +
                                        (rental.open_fee or 0) +
                                        (rental.delivery_fee or 0) +
                                        rental.waiting_fee +
                                        (rental.overtime_fee or 0)
                                    )
                                elif rental.rental_type == RentalType.MINUTES:
                                    rental.already_payed = (
                                        (rental.open_fee or 0) +
                                        (rental.delivery_fee or 0) +
                                        rental.waiting_fee +
                                        (rental.overtime_fee or 0)
                                    )
                                db.commit()

                            if 0 < user.wallet_balance <= 1000 and not flags["low_balance_1000"] and user.fcm_token:
                                flags["low_balance_1000"] = True
                                push_notifications.append((
                                    user.id,
                                    "low_balance",
                                    "low_balance",
                                    {
                                        "balance": int(user.wallet_balance)
                                    }
                                ))

                            if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
                                flags["low_balance_zero"] = True
                                push_notifications.append((
                                    user.id,
                                    "balance_exhausted",
                                    "balance_exhausted"
                                ))
                                telegram_alerts.append(
                                    f"🔔 У клиента (тел.: {user.phone_number}" + 
                                    (f", email: {user.email}" if user.email else "") + 
                                    f") на авто ID {car.id} баланс исчерпан."
                                )

                            if prev_wait == 0 and not flags["waiting"] and user.fcm_token:
                                push_notifications.append((
                                    user.id,
                                    "waiting_started",
                                    "paid_waiting_started",
                                    {
                                        "charge": fee_total_wait,
                                        "extra": extra
                                    }
                                ))
                                flags["waiting"] = True
                    else:
                        extra = math.ceil(waited - 15)
                        fee_total_wait = math.ceil(extra * car.price_per_minute * 0.5)
                        prev_wait = rental.waiting_fee or 0
                        charge = fee_total_wait - prev_wait
                        
                        if charge != 0:
                            existing_tx = db.query(WalletTransaction).filter(
                                WalletTransaction.user_id == user.id,
                                WalletTransaction.transaction_type == WalletTransactionType.RENT_WAITING_FEE,
                                WalletTransaction.related_rental_id == rental.id
                            ).first()
                            
                            if existing_tx:
                                current_balance = float(user.wallet_balance or 0)
                                new_balance_after = current_balance - charge
                                
                                existing_tx.amount = -fee_total_wait
                                existing_tx.description = f"Платное ожидание за {extra} мин"
                                existing_tx.balance_after = new_balance_after
                                
                                user.wallet_balance = new_balance_after
                            else:
                                balance_before = float(user.wallet_balance or 0)
                                new_balance = balance_before - fee_total_wait
                                
                                tx = WalletTransaction(
                                    user_id=user.id,
                                    amount=-fee_total_wait,
                                    transaction_type=WalletTransactionType.RENT_WAITING_FEE,
                                    description=f"Платное ожидание за {extra} мин",
                                    balance_before=balance_before,
                                    balance_after=new_balance,
                                    related_rental_id=rental.id,
                                    created_at=get_local_time(),
                                )
                                db.add(tx)
                                user.wallet_balance = new_balance
                            
                            rental.waiting_fee = fee_total_wait
                            rental.total_price = (
                                    (rental.base_price or 0) +
                                    (rental.open_fee or 0) +
                                    (rental.delivery_fee or 0) +
                                    rental.waiting_fee +
                                    (rental.overtime_fee or 0) +
                                    (rental.distance_fee or 0)
                            )
                            db.commit()
                            if user.wallet_balance >= 0:
                                if rental.rental_type in (RentalType.HOURS, RentalType.DAYS):
                                    rental.already_payed = (
                                        (rental.base_price or 0) +
                                        (rental.open_fee or 0) +
                                        (rental.delivery_fee or 0) +
                                        rental.waiting_fee +
                                        (rental.overtime_fee or 0)
                                    )
                                elif rental.rental_type == RentalType.MINUTES:
                                    rental.already_payed = (
                                        (rental.open_fee or 0) +
                                        (rental.delivery_fee or 0) +
                                        rental.waiting_fee +
                                        (rental.overtime_fee or 0)
                                    )
                                db.commit()
            

            elif rental.rental_status in [RentalStatus.DELIVERING, RentalStatus.DELIVERY_RESERVED, RentalStatus.DELIVERING_IN_PROGRESS]:
                if rental.delivery_end_time:
                    base_time = rental.delivery_end_time
                    waited = (now - base_time).total_seconds() / 60
                else:
                    waited = 0

                if rental.delivery_end_time and 14 <= waited < 15 and not flags["pre_waiting"] and user.fcm_token:
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

                if rental.delivery_end_time and waited > 15:
                    extra = math.ceil(waited - 15)
                    fee_total_wait = math.ceil(extra * car.price_per_minute * 0.5)
                    prev_wait = rental.waiting_fee or 0
                    charge = fee_total_wait - prev_wait
                    
                    if charge > 0 and prev_wait == 0:
                        rental.waiting_fee = fee_total_wait
                        rental.total_price = (
                                (rental.base_price or 0) +
                                (rental.open_fee or 0) +
                                (rental.delivery_fee or 0) +
                                rental.waiting_fee +
                                (rental.overtime_fee or 0) +
                                (rental.distance_fee or 0)
                        )
                        record_wallet_transaction(db, user=user, amount=-charge, ttype=WalletTransactionType.RENT_WAITING_FEE, description=f"Платное ожидание {extra} мин", related_rental=rental)
                        user.wallet_balance -= charge
                        db.commit()
                        if user.wallet_balance >= 0:
                            if rental.rental_type in (RentalType.HOURS, RentalType.DAYS):
                                rental.already_payed = (
                                    (rental.base_price or 0) +
                                    (rental.open_fee or 0) +
                                    (rental.delivery_fee or 0) +
                                    rental.waiting_fee
                                )
                            elif rental.rental_type == RentalType.MINUTES:
                                rental.already_payed = (
                                    (rental.open_fee or 0) +
                                    (rental.delivery_fee or 0) +
                                    rental.waiting_fee
                                )
                        db.commit()

                        # Low balance ≤1000 - уведомления отправляются через локализованную функцию
                        if 0 < user.wallet_balance <= 1000 and not flags["low_balance_1000"] and user.fcm_token:
                            flags["low_balance_1000"] = True
                            push_notifications.append((
                                user.id,
                                "low_balance",
                                "low_balance",
                                {
                                    "balance": int(user.wallet_balance)
                                }
                            ))
                            # Дополнительное уведомление "Заканчиваются деньги на аккаунте"
                            push_notifications.append((
                                user.id,
                                "account_balance_low",
                                "account_balance_low"
                            ))

                        # Balance zero - уведомления отправляются через локализованную функцию
                        if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
                            flags["low_balance_zero"] = True
                            push_notifications.append((
                                user.id,
                                "balance_exhausted",
                                "balance_exhausted"
                            ))
                            telegram_alerts.append(
                                f"🔔 У клиента (тел.: {user.phone_number}" + 
                                (f", email: {user.email}" if user.email else "") + 
                                f") на авто ID {car.id} баланс исчерпан."
                            )

                        # First paid waiting
                        if not flags["waiting"] and user.fcm_token:
                            push_notifications.append((
                                user.id,
                                "waiting_started",
                                "paid_waiting_started",
                                {
                                    "charge": extra * car.price_per_minute * 0.5,
                                    "extra": extra
                                }
                            ))
                            flags["waiting"] = True

            # === IN_USE stage ===
            elif rental.rental_status == RentalStatus.IN_USE:
                # Для поминутного списания используем start_time (время начала аренды)
                # start_time устанавливается только при вызове /start/{car_id}
                if not rental.start_time:
                    # Если start_time не установлен, пропускаем расчет (не должно происходить)
                    continue
                elapsed = (now - rental.start_time).total_seconds() / 60

                # Проверка уровня топлива и отправка уведомления в Telegram (для всех активных аренд)
                if car.fuel_level is not None and not flags["low_fuel_alert"]:
                    is_low_fuel = False
                    fuel_message = ""
                    
                    if car.body_type == CarBodyType.ELECTRIC:
                        # Для электрических: <= 10%
                        if car.fuel_level <= 10:
                            is_low_fuel = True
                            fuel_message = (
                                f"⚡ Низкий уровень заряда у электромобиля!\n"
                                f"Автомобиль: {car.name} (ID {car.id}, гос. номер: {car.plate_number})\n"
                                f"Уровень заряда: {car.fuel_level:.1f}%\n"
                                f"Клиент: {user.phone_number}" + 
                                (f" ({user.first_name or ''} {user.last_name or ''})" if user.first_name or user.last_name else "") +
                                f"\nАренда ID: {rental.id}"
                            )
                    else:
                        # Для бензиновых: <= 5 литров
                        if car.fuel_level <= 5:
                            is_low_fuel = True
                            fuel_message = (
                                f"⛽ Низкий уровень топлива!\n"
                                f"Автомобиль: {car.name} (ID {car.id}, гос. номер: {car.plate_number})\n"
                                f"Остаток топлива: {car.fuel_level:.1f} л\n"
                                f"Клиент: {user.phone_number}" + 
                                (f" ({user.first_name or ''} {user.last_name or ''})" if user.first_name or user.last_name else "") +
                                f"\nАренда ID: {rental.id}"
                            )
                    
                    if is_low_fuel:
                        flags["low_fuel_alert"] = True
                        telegram_alerts.append(fuel_message)

                if rental.rental_type == RentalType.MINUTES:
                    # Получаем уже списанные минуты из существующей транзакции
                    existing_tx = db.query(WalletTransaction).filter(
                        WalletTransaction.related_rental_id == rental.id,
                        WalletTransaction.transaction_type == WalletTransactionType.RENT_MINUTE_CHARGE
                    ).order_by(WalletTransaction.created_at.desc()).first()
                    
                    # Рассчитываем уже списанные минуты из суммы транзакции (более надежно, чем парсить описание)
                    prev_minutes_charged = 0
                    if existing_tx and existing_tx.amount and car.price_per_minute > 0:
                        # amount отрицательный, берем модуль и делим на цену за минуту
                        prev_minutes_charged = int(abs(float(existing_tx.amount)) / car.price_per_minute)
                    
                    # Рассчитываем прошедшее время от start_time
                    elapsed_min = math.ceil(elapsed)
                    new_minutes = elapsed_min - prev_minutes_charged
                    
                    if new_minutes > 0:
                        balance_before_charge = user.wallet_balance
                        charge_per_minute = car.price_per_minute
                        user.wallet_balance -= charge_per_minute
                        new_minutes_charged = prev_minutes_charged + 1
                        flags["minutes_charged"] = new_minutes_charged
                        due = new_minutes_charged * car.price_per_minute
                        rental.overtime_fee = due
                        rental.total_price = (
                                (rental.base_price or 0) +
                                (rental.open_fee or 0) +
                                (rental.delivery_fee or 0) +
                                (rental.waiting_fee or 0) +
                                rental.overtime_fee +
                                (rental.distance_fee or 0)
                        )
                        
                        if existing_tx:
                            existing_tx.amount = -due
                            existing_tx.description = f"Поминутное списание {new_minutes_charged} мин"
                            existing_tx.balance_after = user.wallet_balance
                        else:
                            tx = WalletTransaction(
                                user_id=user.id,
                                amount=-due,
                                transaction_type=WalletTransactionType.RENT_MINUTE_CHARGE,
                                description=f"Поминутное списание {new_minutes_charged} мин",
                                balance_before=balance_before_charge,
                                balance_after=user.wallet_balance,
                                related_rental_id=rental.id,
                                created_at=get_local_time()
                            )
                            db.add(tx)
                        
                        db.commit()
                        if user.wallet_balance >= 0:
                            rental.already_payed = (
                                (rental.open_fee or 0) +
                                (rental.delivery_fee or 0) +
                                rental.overtime_fee
                            )
                            db.commit()
                    
                    # Проверка баланса и уведомления (выполняется всегда, не только при списании)
                        ten_minutes_cost = 10 * car.price_per_minute
                        if car.price_per_minute > 0:
                            minutes_left = user.wallet_balance / car.price_per_minute
                            
                            if 0 < user.wallet_balance <= ten_minutes_cost and not flags["low_balance_1000"] and user.fcm_token:
                                flags["low_balance_1000"] = True
                                push_notifications.append((
                                    user.id,
                                    "account_balance_low",
                                    "account_balance_low",
                                    {
                                        "balance": int(user.wallet_balance),
                                        "minutes_left": int(minutes_left)
                                    }
                                ))
                            
                            if 0 < minutes_left <= 10 and not flags["telegram_10min_alert"]:
                                flags["telegram_10min_alert"] = True
                                telegram_alerts.append(
                                    f"⏰ За 10 минут до окончания аренды. Клиент {user.phone_number} ({user.first_name or ''} {user.last_name or ''}), "
                                    f"авто {car.name} (ID {car.id}). Баланс: {int(user.wallet_balance)}₸, осталось минут: {int(minutes_left)}. "
                                    f"Аренда будет автоматически завершена при нулевом балансе."
                                )

                        if user.wallet_balance <= 0:
                            if not flags.get("balance_zero_at"):
                                flags["balance_zero_at"] = now
                                flags["low_balance_zero"] = True
                                telegram_alerts.append(
                                    f"🔔 Баланс исчерпан. Клиент {user.phone_number}, авто {car.name} (ID {car.id}). Через 10 минут будет блокировка двигателя, если баланс не пополнится."
                                )
                            else:
                                zero_at = flags.get("balance_zero_at")
                                try:
                                    elapsed_from_zero = (now - zero_at).total_seconds() / 60  # type: ignore[arg-type]
                                except Exception:
                                    elapsed_from_zero = 0
                                if elapsed_from_zero >= 10 and not flags.get("engine_lock_scheduled"):
                                    flags["engine_lock_scheduled"] = True
                                    if car.gps_imei:
                                        lock_requests.append((car.gps_imei, car.name, user.id))
                                        telegram_alerts.append(
                                            f"⏱️ 10 минут с нулевого баланса истекли. Планируется блокировка двигателя. Авто: {car.name} (IMEI {car.gps_imei})."
                                        )

                elif rental.rental_type in (RentalType.HOURS, RentalType.DAYS):
                    factor = 60 if rental.rental_type == RentalType.HOURS else 1440
                    planned_minutes = rental.duration * factor
                    remaining = planned_minutes - elapsed

                    if elapsed > planned_minutes and flags.get("fuel_finalized") is None:
                        # Записываем топливо на момент окончания основного тарифа
                        if car.fuel_level is not None and rental.fuel_after is None:
                            rental.fuel_after = car.fuel_level
                            db.commit()
                        
                        existing_tx = db.query(WalletTransaction).filter(
                            WalletTransaction.related_rental_id == rental.id,
                            WalletTransaction.transaction_type == WalletTransactionType.RENT_FUEL_FEE
                        ).first()
                        
                        if not existing_tx and rental.fuel_before is not None and car.fuel_level is not None:
                            if car.fuel_level < rental.fuel_before:
                                fuel_before_rounded = ceil(rental.fuel_before)
                                fuel_at_end_main_rounded = floor(car.fuel_level)
                                fuel_consumed_main = fuel_before_rounded - fuel_at_end_main_rounded
                                
                                if fuel_consumed_main > 0:
                                    flags["fuel_finalized"] = True
                                    
                                    if car.body_type == CarBodyType.ELECTRIC:
                                        price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
                                    else:
                                        price_per_liter = FUEL_PRICE_PER_LITER
                                    
                                    total_fuel_fee = int(fuel_consumed_main * price_per_liter)
                                    
                                    balance_before = float(user.wallet_balance)
                                    user.wallet_balance = balance_before - total_fuel_fee
                                    tx = WalletTransaction(
                                        user_id=user.id,
                                        amount=-total_fuel_fee,
                                        transaction_type=WalletTransactionType.RENT_FUEL_FEE,
                                        description=f"Оплата топлива: {int(fuel_consumed_main)} л × {price_per_liter}₸ = {total_fuel_fee:,}₸" if car.body_type != CarBodyType.ELECTRIC else f"Оплата заряда: {int(fuel_consumed_main)}% × {price_per_liter}₸ = {total_fuel_fee:,}₸",
                                        balance_before=balance_before,
                                        balance_after=float(user.wallet_balance),
                                        related_rental_id=rental.id,
                                        created_at=get_local_time()
                                    )
                                    db.add(tx)
                                    db.commit()
                                    if user.wallet_balance >= 0:
                                        rental.already_payed = (
                                            (rental.base_price or 0) +
                                            (rental.open_fee or 0) +
                                            (rental.delivery_fee or 0) +
                                            (rental.waiting_fee or 0) +
                                            (rental.overtime_fee or 0) +
                                            total_fuel_fee
                                        )
                                        db.commit()

                    if 0 < remaining <= 10 and not flags["pre_overtime"] and user.fcm_token:
                        flags["pre_overtime"] = True
                        push_notifications.append((
                            user.id,
                            "basic_tariff_ending",
                            "basic_tariff_ending",
                            {
                                "remaining": math.ceil(remaining)
                            }
                        ))

                    overtime = max(0, elapsed - planned_minutes)
                    if overtime > 0:
                        extra_minutes = math.ceil(overtime)
                        prev_ov_minutes_charged = flags.get("overtime_minutes_charged", 0)
                        new_ov_minutes = extra_minutes - prev_ov_minutes_charged
                        
                        if new_ov_minutes > 0:
                            balance_before_charge = user.wallet_balance
                            charge_ov_per_minute = car.price_per_minute
                            user.wallet_balance -= charge_ov_per_minute
                            new_ov_minutes_charged = prev_ov_minutes_charged + 1
                            flags["overtime_minutes_charged"] = new_ov_minutes_charged
                            fee_total_ov = new_ov_minutes_charged * car.price_per_minute
                            rental.overtime_fee = fee_total_ov
                            rental.total_price = (
                                (rental.base_price or 0)
                                + (rental.open_fee or 0)
                                + (rental.delivery_fee or 0)
                                + (rental.waiting_fee or 0)
                                + rental.overtime_fee
                                + (rental.distance_fee or 0)
                            )
                            existing_tx = db.query(WalletTransaction).filter(
                                WalletTransaction.related_rental_id == rental.id,
                                WalletTransaction.transaction_type == WalletTransactionType.RENT_OVERTIME_FEE
                            ).order_by(WalletTransaction.created_at.desc()).first()
                            
                            if existing_tx:
                                existing_tx.amount = -fee_total_ov
                                existing_tx.description = f"Сверхтариф {new_ov_minutes_charged} мин"
                                existing_tx.balance_after = user.wallet_balance
                            else:
                                tx = WalletTransaction(
                                    user_id=user.id,
                                    amount=-fee_total_ov,
                                    transaction_type=WalletTransactionType.RENT_OVERTIME_FEE,
                                    description=f"Сверхтариф {new_ov_minutes_charged} мин",
                                    balance_before=balance_before_charge,
                                    balance_after=user.wallet_balance,
                                    related_rental_id=rental.id,
                                    created_at=get_local_time()
                                )
                                db.add(tx)
                            
                            db.commit()
                            existing_fuel_tx = db.query(WalletTransaction).filter(
                                WalletTransaction.related_rental_id == rental.id,
                                WalletTransaction.transaction_type == WalletTransactionType.RENT_FUEL_FEE
                            ).first()
                            fuel_fee = abs(existing_fuel_tx.amount) if existing_fuel_tx else 0
                            if user.wallet_balance >= 0:
                                rental.already_payed = (
                                    (rental.base_price or 0) +
                                    (rental.open_fee or 0) +
                                    (rental.delivery_fee or 0) +
                                    (rental.waiting_fee or 0) +
                                    rental.overtime_fee +
                                    fuel_fee
                                )
                                db.commit()
                            ten_minutes_cost = 10 * car.price_per_minute
                            if car.price_per_minute > 0:
                                minutes_left = user.wallet_balance / car.price_per_minute
                                
                                if 0 < user.wallet_balance <= ten_minutes_cost and not flags["low_balance_1000"] and user.fcm_token:
                                    flags["low_balance_1000"] = True
                                    push_notifications.append((
                                        user.id,
                                        "account_balance_low",
                                        "account_balance_low",
                                        {
                                            "balance": int(user.wallet_balance),
                                            "minutes_left": int(minutes_left)
                                        }
                                    ))
                                
                                if 0 < minutes_left <= 10 and not flags["telegram_10min_alert"]:
                                    flags["telegram_10min_alert"] = True
                                    telegram_alerts.append(
                                        f"⏰ За 10 минут до окончания аренды. Клиент {user.phone_number} ({user.first_name or ''} {user.last_name or ''}), "
                                        f"авто {car.name} (ID {car.id}). Баланс: {int(user.wallet_balance)}₸, осталось минут: {int(minutes_left)}. "
                                        f"Аренда будет автоматически завершена при нулевом балансе."
                                    )

                            if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
                                flags["low_balance_zero"] = True
                                telegram_alerts.append(
                                    f"🔔 У клиента (тел.: {user.phone_number}" + 
                                (f", email: {user.email}" if user.email else "") + 
                                f") на авто ID {car.id} баланс исчерпан."
                                )

                            if not flags["overtime"] and user.fcm_token:
                                push_notifications.append((
                                    user.id,
                                    "overtime_charges",
                                    "out_of_tariff_charges",
                                    {
                                        "charge": fee_total_ov,
                                        "extra": new_ov_minutes_charged
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
                        record_wallet_transaction(db, user=mechanic, amount=-penalty_fee, ttype=WalletTransactionType.DELIVERY_PENALTY, description=f"Штраф за задержку доставки {penalty_minutes:.1f} мин", related_rental=rental)
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
                        mechanic_info = f"тел.: {mechanic.phone_number}"
                        if mechanic.email:
                            mechanic_info += f", email: {mechanic.email}"
                        telegram_alerts.append(
                            f"⚠️ Механик ({mechanic_info}) получил штраф {penalty_fee}₸ "
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
    return push_notifications, telegram_alerts, lock_requests
