import asyncio
import math
from datetime import datetime

import anyio

from app.dependencies.database.database import SessionLocal
from app.models.car_model import Car
from app.models.history_model import RentalHistory, RentalStatus, RentalType
from app.models.user_model import User, UserRole
from app.push.utils import send_push_notification_async

# Кэш флагов уведомлений: rental_id -> {'waiting': bool, 'overtime': bool}
_notification_flags: dict[int, dict[str, bool]] = {}


async def rental_billing_loop():
    """
    Фон: каждые 10 секунд запускаем обработку и рассылаем все накопленные пуши.
    """
    while True:
        await asyncio.sleep(10)
        # process_rentals_sync возвращает список (token, title, body)
        notifications = await anyio.to_thread.run_sync(process_rentals_sync)
        for token, title, body in notifications:
            await send_push_notification_async(token, title, body)


def process_rentals_sync() -> list[tuple[str, str, str]]:
    """
    Синхронно:
      - вычисляет и списывает waiting fee и overtime fee
      - коммитит каждое списание
      - формирует список пушей, но шлёт их только один раз
    """
    db = SessionLocal()
    now = datetime.utcnow()
    notifications: list[tuple[str, str, str]] = []

    # Выбираем все активные аренды (RESERVED, IN_USE), не механиков
    rentals = (
        db.query(RentalHistory)
        .join(User, RentalHistory.user_id == User.id)
        .filter(
            RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE]),
            User.role != UserRole.MECHANIC
        )
        .all()
    )
    print("GORADE")
    active_ids = set(r.id for r in rentals)

    for rental in rentals:
        try:
            user = rental.user
            car = rental.car
            rental_id = rental.id

            # Инициализируем флаги
            flags = _notification_flags.setdefault(rental_id, {"waiting": False, "overtime": False})

            # ===== 1) RESERVED → платное ожидание =====
            if rental.rental_status == RentalStatus.RESERVED:
                waited = (now - (rental.reservation_time or rental.start_time)).total_seconds() / 60
                if waited > 15:
                    extra = math.ceil(waited - 15)
                    fee_total = int(extra * car.price_per_minute * 0.5)
                    already = rental.already_payed or 0
                    if fee_total > already:
                        to_charge = fee_total - already
                        # обновляем историю оплаты
                        rental.already_payed = fee_total
                        user.wallet_balance -= to_charge
                        db.commit()

                        # пуш только при первом списании ожидания
                        if not flags["waiting"] and user.fcm_token:
                            title = "Началось платное ожидание"
                            body = (
                                f"Первые {extra} мин платного ожидания — "
                                f"списано {to_charge} ₸ с вашего баланса."
                            )
                            notifications.append((user.fcm_token, title, body))
                            flags["waiting"] = True

                        print(
                            f"[Billing][WAIT] rental={rental_id} charged={to_charge} new_balance={user.wallet_balance}")

            # ===== 2) IN_USE → списание сверх тарифа =====
            elif rental.rental_status == RentalStatus.IN_USE:
                elapsed = (now - rental.start_time).total_seconds() / 60

                if rental.rental_type == RentalType.MINUTES:
                    minutes = math.ceil(elapsed)
                    due_total = int(minutes * car.price_per_minute)
                else:
                    factor = 60 if rental.rental_type == RentalType.HOURS else 1440
                    planned = rental.duration * factor
                    overtime = max(0, elapsed - planned)
                    if overtime <= 0:
                        continue
                    minutes = math.ceil(overtime)
                    due_total = int(minutes * car.price_per_minute)

                already = rental.already_payed or 0
                if due_total > already:
                    to_charge = due_total - already
                    rental.already_payed = already + to_charge
                    user.wallet_balance -= to_charge
                    db.commit()

                    # пуш только при первом пересечении лимита
                    if not flags["overtime"] and user.fcm_token:
                        title = "Списания вне тарифа"
                        body = (
                            f"Начали списывать сверх тарифа: {minutes} мин — "
                            f"{to_charge} ₸ с вашего баланса."
                        )
                        notifications.append((user.fcm_token, title, body))
                        flags["overtime"] = True

                    print(
                        f"[Billing][OVERTIME] rental={rental_id} charged={to_charge} new_balance={user.wallet_balance}")

        except Exception as e:
            db.rollback()
            print(f"[Billing error] rental={rental.id}: {e}")

    # Очищаем кэш для завершённых или отменённых аренд
    for rid in list(_notification_flags.keys()):
        if rid not in active_ids:
            _notification_flags.pop(rid, None)

    db.close()
    return notifications
