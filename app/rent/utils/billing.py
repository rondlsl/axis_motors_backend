import asyncio
import math
from datetime import datetime
import uuid
from math import ceil, floor

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.dependencies.database.database import SessionLocal
from app.models.car_model import Car
from app.models.history_model import RentalHistory, RentalStatus, RentalType
from app.models.user_model import User, UserRole
from app.wallet.utils import record_wallet_transaction
from app.models.wallet_transaction_model import WalletTransactionType, WalletTransaction
from app.push.utils import send_push_to_user_by_id, send_localized_notification_to_user
from app.core.config import TELEGRAM_BOT_TOKEN, TELEGRAM_BOT_TOKEN_2, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD
from app.gps_api.utils.auth_api import get_auth_token
from app.gps_api.utils.car_data import send_lock_engine

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
        for chat_id in (965048905, 5941825713, 860991388):
            asyncio.create_task(_send_telegram(text, chat_id, TELEGRAM_BOT_TOKEN))
    
    # Отправка во второй бот
    for text in telegram_alerts:
        for chat_id in (965048905, 5941825713, 860991388):
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
                    for chat_id in (965048905, 5941825713, 860991388):
                        asyncio.create_task(_send_telegram(note, chat_id, TELEGRAM_BOT_TOKEN))
                    # Отправка во второй бот
                    for chat_id in (965048905, 5941825713, 860991388):
                        asyncio.create_task(_send_telegram(note, chat_id, TELEGRAM_BOT_TOKEN_2))
                except Exception as e:
                    err = f"⚠️ Ошибка блокировки двигателя (IMEI {imei}): {e}"
                    # Отправка в первый бот
                    for chat_id in (965048905, 5941825713, 860991388):
                        asyncio.create_task(_send_telegram(err, chat_id, TELEGRAM_BOT_TOKEN))
                    # Отправка во второй бот
                    for chat_id in (965048905, 5941825713, 860991388):
                        asyncio.create_task(_send_telegram(err, chat_id, TELEGRAM_BOT_TOKEN_2))
    except Exception as e:
        error_msg = f"⚠️ Ошибка при обработке блокировок двигателя: {e}"
        # Отправка в первый бот
        for chat_id in (965048905, 5941825713, 860991388):
            asyncio.create_task(_send_telegram(error_msg, chat_id, TELEGRAM_BOT_TOKEN))
        # Отправка во второй бот
        for chat_id in (965048905, 5941825713, 860991388):
            asyncio.create_task(_send_telegram(error_msg, chat_id, TELEGRAM_BOT_TOKEN_2))

    # 6) Yield back to event loop
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
    now = datetime.utcnow()
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
                    
                    # Создаем транзакцию только один раз за весь период ожидания
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
                        rental.already_payed = (rental.already_payed or 0) + charge
                        record_wallet_transaction(db, user=user, amount=-charge, ttype=WalletTransactionType.RENT_WAITING_FEE, description=f"Платное ожидание {extra} мин", related_rental=rental)
                        user.wallet_balance -= charge
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
                    
                    # Создаем транзакцию только один раз за весь период ожидания
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
                elapsed = (now - rental.start_time).total_seconds() / 60

                # Списываем топливо во время поездки (для всех тарифов кроме минутного, включая владельца)
                if rental.rental_type != RentalType.MINUTES and rental.fuel_before is not None and car.fuel_level is not None:
                    # Проверяем, что топливо уменьшилось
                    if car.fuel_level < rental.fuel_before:
                        # Получаем последнее списанное топливо из flags (начальное значение - fuel_before)
                        last_charged_fuel = flags.get("last_charged_fuel")
                        if last_charged_fuel is None:
                            last_charged_fuel = rental.fuel_before
                        
                        # Рассчитываем новое потребление топлива
                        fuel_before_rounded = ceil(rental.fuel_before)
                        fuel_current_rounded = floor(car.fuel_level)
                        
                        # Рассчитываем, сколько уже было списано (от fuel_before до last_charged_fuel)
                        last_charged_fuel_rounded = floor(last_charged_fuel)
                        fuel_already_charged_liters = fuel_before_rounded - last_charged_fuel_rounded
                        
                        # Рассчитываем общее потребление от начала до текущего момента
                        fuel_consumed_total_liters = fuel_before_rounded - fuel_current_rounded
                        
                        # Рассчитываем новое потребление для списания (разница между общим и уже списанным)
                        fuel_to_charge_liters = fuel_consumed_total_liters - fuel_already_charged_liters
                        
                        if fuel_to_charge_liters > 0:
                            # Определяем цену за литр в зависимости от типа автомобиля
                            if car.body_type == "ELECTRIC":
                                price_per_liter = ELECTRIC_FUEL_PRICE_PER_LITER
                            else:
                                price_per_liter = FUEL_PRICE_PER_LITER
                            
                            fuel_fee = int(fuel_to_charge_liters * price_per_liter)
                            
                            if fuel_fee > 0:
                                # Списываем топливо сразу (1 литр = сразу списание)
                                rental.already_payed = (rental.already_payed or 0) + fuel_fee
                                record_wallet_transaction(db, user=user, amount=-fuel_fee, ttype=WalletTransactionType.RENT_FUEL_FEE, description=f"Оплата топлива: {fuel_to_charge_liters} л × {price_per_liter} = {fuel_fee}₸", related_rental=rental)
                                user.wallet_balance -= fuel_fee
                                flags["last_charged_fuel"] = fuel_current_rounded
                                db.commit()
                                
                                # Уведомление когда остается сумма на 10 минут (для поминутного тарифа)
                                ten_minutes_cost = 10 * car.price_per_minute
                                if 0 < user.wallet_balance <= ten_minutes_cost and not flags["low_balance_1000"] and user.fcm_token:
                                    flags["low_balance_1000"] = True
                                    push_notifications.append((
                                        user.id,
                                        "low_balance_alert",
                                        "low_balance_warning",
                                        {
                                            "balance": int(user.wallet_balance),
                                            "minutes_left": int(user.wallet_balance / car.price_per_minute) if car.price_per_minute > 0 else 0
                                        }
                                    ))
                                
                                if user.wallet_balance <= 0 and not flags["low_balance_zero"] and user.fcm_token:
                                    flags["low_balance_zero"] = True
                                    telegram_alerts.append(
                                        f"🔔 Баланс исчерпан. Клиент {user.phone_number}, авто {car.name} (ID {car.id}). Через 10 минут будет блокировка двигателя, если баланс не пополнится."
                                    )

                if rental.rental_type == RentalType.MINUTES:
                    # Списываем строго по 1 минуте за раз с баланса
                    elapsed_min = math.ceil(elapsed)
                    # Сколько минут уже было списано с баланса
                    prev_minutes_charged = flags.get("minutes_charged", 0)
                    # Сколько новых минут прошло
                    new_minutes = elapsed_min - prev_minutes_charged
                    
                    # Списываем только если прошла хотя бы 1 новая минута
                    if new_minutes > 0:
                        # Сохраняем баланс до списания
                        balance_before_charge = user.wallet_balance
                        
                        # С баланса списываем только за 1 минуту (чтобы баланс не ушел в минус)
                        charge_per_minute = car.price_per_minute
                        user.wallet_balance -= charge_per_minute
                        
                        # Обновляем счетчик списанных минут
                        new_minutes_charged = prev_minutes_charged + 1
                        flags["minutes_charged"] = new_minutes_charged
                        
                        # Обновляем overtime_fee и total_price накопленной суммой
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
                        rental.already_payed = (rental.already_payed or 0) + charge_per_minute
                        
                        # Находим или создаем транзакцию для поминутного списания
                        existing_tx = db.query(WalletTransaction).filter(
                            WalletTransaction.related_rental_id == rental.id,
                            WalletTransaction.transaction_type == WalletTransactionType.RENT_MINUTE_CHARGE
                        ).order_by(WalletTransaction.created_at.desc()).first()
                        
                        if existing_tx:
                            # Обновляем существующую транзакцию
                            existing_tx.amount = -due  # накопленная сумма
                            existing_tx.description = f"Поминутное списание {new_minutes_charged} мин"
                            existing_tx.balance_after = user.wallet_balance
                        else:
                            # Создаем новую транзакцию вручную, т.к. баланс уже списан
                            tx = WalletTransaction(
                                user_id=user.id,
                                amount=-due,  # накопленная сумма
                                transaction_type=WalletTransactionType.RENT_MINUTE_CHARGE,
                                description=f"Поминутное списание {new_minutes_charged} мин",
                                balance_before=balance_before_charge,
                                balance_after=user.wallet_balance,
                                related_rental_id=rental.id
                            )
                            db.add(tx)
                        
                        db.commit()

                        # Уведомление когда остается сумма на 10 минут
                        ten_minutes_cost = 10 * car.price_per_minute
                        if 0 < user.wallet_balance <= ten_minutes_cost and not flags["low_balance_1000"] and user.fcm_token:
                            flags["low_balance_1000"] = True
                            push_notifications.append((
                                user.id,
                                "low_balance_alert",
                                "low_balance_warning",
                                {
                                    "balance": int(user.wallet_balance),
                                    "minutes_left": int(user.wallet_balance / car.price_per_minute) if car.price_per_minute > 0 else 0
                                }
                            ))

                        # Нулевой баланс → помечаем время и предупреждаем о предстоящей блокировке через 10 минут
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
                                    elapsed_min = (now - zero_at).total_seconds() / 60  # type: ignore[arg-type]
                                except Exception:
                                    elapsed_min = 0
                                if elapsed_min >= 10 and not flags.get("engine_lock_scheduled"):
                                    flags["engine_lock_scheduled"] = True
                                    if car.gps_imei:
                                        lock_requests.append((car.gps_imei, car.name, user.id))
                                        telegram_alerts.append(
                                            f"⏱️ 10 минут с нулевого баланса истекли. Планируется блокировка двигателя. Авто: {car.name} (IMEI {car.gps_imei})."
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

                    overtime = max(0, elapsed - planned)
                    if overtime > 0:
                        # Списываем строго по 1 минуте за раз с баланса после истечения основного тарифа
                        extra_minutes = math.ceil(overtime)
                        # Сколько минут сверхлимита уже было списано с баланса
                        prev_ov_minutes_charged = flags.get("overtime_minutes_charged", 0)
                        # Сколько новых минут сверхлимита прошло
                        new_ov_minutes = extra_minutes - prev_ov_minutes_charged
                        
                        if new_ov_minutes > 0:
                            # Сохраняем баланс до списания
                            balance_before_charge = user.wallet_balance
                            
                            # С баланса списываем только за 1 минуту (чтобы баланс не ушел в минус)
                            charge_ov_per_minute = car.price_per_minute
                            user.wallet_balance -= charge_ov_per_minute
                            
                            # Обновляем счетчик списанных минут сверхлимита
                            new_ov_minutes_charged = prev_ov_minutes_charged + 1
                            flags["overtime_minutes_charged"] = new_ov_minutes_charged
                            
                            # Обновляем overtime_fee и total_price накопленной суммой
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
                            rental.already_payed = (rental.already_payed or 0) + charge_ov_per_minute
                            
                            # Находим или создаем транзакцию для сверхтарифа
                            existing_tx = db.query(WalletTransaction).filter(
                                WalletTransaction.related_rental_id == rental.id,
                                WalletTransaction.transaction_type == WalletTransactionType.RENT_OVERTIME_FEE
                            ).order_by(WalletTransaction.created_at.desc()).first()
                            
                            if existing_tx:
                                # Обновляем существующую транзакцию
                                existing_tx.amount = -fee_total_ov  # накопленная сумма
                                existing_tx.description = f"Сверхтариф {new_ov_minutes_charged} мин"
                                existing_tx.balance_after = user.wallet_balance
                            else:
                                # Создаем новую транзакцию вручную, т.к. баланс уже списан
                                tx = WalletTransaction(
                                    user_id=user.id,
                                    amount=-fee_total_ov,  # накопленная сумма
                                    transaction_type=WalletTransactionType.RENT_OVERTIME_FEE,
                                    description=f"Сверхтариф {new_ov_minutes_charged} мин",
                                    balance_before=balance_before_charge,
                                    balance_after=user.wallet_balance,
                                    related_rental_id=rental.id
                                )
                                db.add(tx)
                            
                            db.commit()

                            # Уведомление когда остается сумма на 10 минут
                            ten_minutes_cost = 10 * car.price_per_minute
                            if 0 < user.wallet_balance <= ten_minutes_cost and not flags["low_balance_1000"] and user.fcm_token:
                                flags["low_balance_1000"] = True
                                push_notifications.append((
                                    user.id,
                                    "low_balance_alert",
                                    "low_balance_warning",
                                    {
                                        "balance": int(user.wallet_balance),
                                        "minutes_left": int(user.wallet_balance / car.price_per_minute) if car.price_per_minute > 0 else 0
                                    }
                                ))

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
