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
    APPLICATION_REJECTED_FINANCIER = "application_rejected_financier"  # Заявка отклонена финансистом
    APPLICATION_REJECTED_MVD = "application_rejected_mvd"  # Заявка отклонена МВД
    APPLICATION_APPROVED_FINANCIER = "application_approved_financier"  # Заявка одобрена финансистом
    APPLICATION_APPROVED_MVD = "application_approved_mvd"  # Заявка одобрена МВД
