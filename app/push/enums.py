from enum import Enum


class NotificationStatus(str, Enum):
    """Статусы уведомлений"""
    MECHANIC_ASSIGNED = "mechanic_assigned"  # Механик назначен
    CAR_DELIVERED = "car_delivered"  # Машина доставлена
    DELIVERY_NEW_ORDER = "delivery_new_order"  # Доставка: новый заказ
    DELIVERY_STARTED = "delivery_started"  # Доставка начата
    NEW_CAR_FOR_INSPECTION = "new_car_for_inspection"  # Новая машина для осмотра
    PAID_WAITING_SOON = "paid_waiting_soon"  # Скоро начнётся платное ожидание
    PAID_WAITING_STARTED = "paid_waiting_started"  # Началось платное ожидание
    LOW_BALANCE = "low_balance"  # Низкий баланс
    BASIC_TARIFF_ENDING_SOON = "basic_tariff_ending_soon"  # Скоро закончится базовый тариф
    OUT_OF_TARIFF_CHARGES = "out_of_tariff_charges"  # Списания вне тарифа
    DELIVERY_CANCELLED = "delivery_cancelled"  # Доставка отменена
    BALANCE_EXHAUSTED = "balance_exhausted"  # Баланс исчерпан
    DELIVERY_DELAY_PENALTY = "delivery_delay_penalty"  # Штраф за задержку доставки
    DOCUMENTS_RECHECK_REQUIRED = "documents_recheck_required"  # Требуется повторная проверка документов
    APPLICATION_REJECTED_FINANCIER = "application_rejected_financier"  # Заявка отклонена финансистом
    APPLICATION_REJECTED_MVD = "application_rejected_mvd"  # Заявка отклонена МВД
    APPLICATION_APPROVED_FINANCIER = "application_approved_financier"  # Заявка одобрена финансистом
    APPLICATION_APPROVED_MVD = "application_approved_mvd"  # Заявка одобрена МВД
    GUARANTOR_INVITATION = "guarantor_invitation"  # Приглашение стать гарантом
    GUARANTOR_ACCEPTED = "guarantor_accepted"  # Гарант принял заявку
    FUEL_EMPTY = "fuel_empty"  # Закончился бензин
    ACCOUNT_BALANCE_LOW = "account_balance_low"  # Заканчиваются деньги на аккаунте
    ZONE_EXIT = "zone_exit"  # Выезд за зону
    RPM_SPIKES = "rpm_spikes"  # Много резких скачков оборотов
    VERIFICATION_PASSED = "verification_passed"  # Прошёл проверку
    VERIFICATION_FAILED = "verification_failed"  # Не прошёл проверку
    PROMO_CODE_AVAILABLE = "promo_code_available"  # Вам доступен промокод
    GUARANTOR_CONNECTED = "guarantor_connected"  # Гарант подключён
    FUEL_REFILL_DETECTED = "fuel_refill_detected"  # Обнаружена заправка
    COURIER_FOUND = "courier_found"  # Нашёлся курьер
    COURIER_DELIVERED = "courier_delivered"  # Курьер доставил авто
    FINE_ISSUED = "fine_issued"  # Вам начислен штраф
    BALANCE_TOP_UP = "balance_top_up"  # Ваш баланс пополнен
    BASIC_TARIFF_ENDING = "basic_tariff_ending"  # Основной тариф заканчивается
    LOCKS_OPEN = "locks_open"  # Замки открыты
    IMPACT_WEAK = "impact_weak"  # Удар слабый
    IMPACT_MEDIUM = "impact_medium"  # Удар средний
    IMPACT_STRONG = "impact_strong"  # Удар сильный
    BIRTHDAY = "birthday"  # День рождения клиента
    FRIDAY_EVENING = "friday_evening"  # Пятница вечер
    MONDAY_MORNING = "monday_morning"  # Понедельник утро
    NEW_CAR_AVAILABLE = "new_car_available"  # Уведомление: новый авто
    CAR_NEARBY = "car_nearby"  # Машина рядом
    HOLIDAY_GREETING = "holiday_greeting"  # Поздравления с праздниками
    AIRPORT_LOCATION = "airport_location"  # Локация аэропорта
    CAR_VIEWED_EXIT = "car_viewed_exit"  # Пользователь смотрел авто и вышел
    DOCUMENTS_UPLOADED = "documents_uploaded"  # Документы загружены