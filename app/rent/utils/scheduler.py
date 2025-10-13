"""
Утилиты для работы с забронированными заранее автомобилями
"""
from datetime import datetime, timedelta
import uuid
from sqlalchemy.orm import Session
from app.models.history_model import RentalHistory, RentalStatus
from app.models.car_model import CarStatus
from app.models.car_model import Car


def process_scheduled_bookings(db: Session) -> dict:
    """
    Обрабатывает забронированные заранее автомобили:
    - Переводит в статус RESERVED когда наступает время
    - Отменяет просроченные бронирования
    """
    now = datetime.utcnow()
    
    # 1) Находим бронирования, которые должны начаться сейчас
    bookings_to_activate = db.query(RentalHistory).filter(
        RentalHistory.rental_status == RentalStatus.SCHEDULED,
        RentalHistory.scheduled_start_time <= now,
        RentalHistory.scheduled_start_time >= now - timedelta(minutes=15)  # Даем 15 минут на активацию
    ).all()
    
    activated_count = 0
    for booking in bookings_to_activate:
        # Обновляем статус бронирования
        booking.rental_status = RentalStatus.RESERVED
        
        # Обновляем статус автомобиля
        car = db.query(Car).get(booking.car_id)
        if car:
            car.status = CarStatus.RESERVED
        
        activated_count += 1
    
    # 2) Находим просроченные бронирования (не активировались в течение 15 минут)
    expired_bookings = db.query(RentalHistory).filter(
        RentalHistory.rental_status == RentalStatus.SCHEDULED,
        RentalHistory.scheduled_start_time < now - timedelta(minutes=15)
    ).all()
    
    cancelled_count = 0
    for booking in expired_bookings:
        # Отменяем просроченное бронирование
        booking.rental_status = RentalStatus.CANCELLED
        
        # Освобождаем автомобиль
        car = db.query(Car).get(booking.car_id)
        if car:
            car.status = CarStatus.FREE
            car.current_renter_id = None
        
        cancelled_count += 1
    
    # 3) Находим бронирования, которые должны завершиться
    bookings_to_complete = db.query(RentalHistory).filter(
        RentalHistory.rental_status == RentalStatus.RESERVED,
        RentalHistory.scheduled_end_time <= now,
        RentalHistory.is_advance_booking == "true"
    ).all()
    
    completed_count = 0
    for booking in bookings_to_complete:
        # Автоматически завершаем бронирование
        booking.rental_status = RentalStatus.COMPLETED
        booking.end_time = now
        
        # Освобождаем автомобиль
        car = db.query(Car).get(booking.car_id)
        if car:
            car.status = CarStatus.FREE
            car.current_renter_id = None
        
        completed_count += 1
    
    # Сохраняем изменения
    db.commit()
    
    return {
        "activated_bookings": activated_count,
        "cancelled_bookings": cancelled_count,
        "completed_bookings": completed_count,
        "processed_at": now.isoformat()
    }


def get_upcoming_bookings(db: Session, user_id: uuid.UUID, limit: int = 10) -> list:
    """
    Получает предстоящие бронирования пользователя
    """
    now = datetime.utcnow()
    
    bookings = db.query(RentalHistory).filter(
        RentalHistory.user_id == user_id,
        RentalHistory.rental_status == RentalStatus.SCHEDULED,
        RentalHistory.scheduled_start_time > now
    ).order_by(RentalHistory.scheduled_start_time.asc()).limit(limit).all()
    
    return bookings


def check_booking_conflicts(
    db: Session, 
    car_id: int, 
    start_time: datetime, 
    end_time: datetime,
    exclude_rental_id: uuid.UUID = None
) -> bool:
    """
    Проверяет конфликты бронирования для автомобиля
    """
    query = db.query(RentalHistory).filter(
        RentalHistory.car_id == car_id,
        RentalHistory.rental_status.in_([
            RentalStatus.RESERVED,
            RentalStatus.IN_USE,
            RentalStatus.SCHEDULED
        ]),
        RentalHistory.scheduled_start_time <= end_time,
        RentalHistory.scheduled_end_time >= start_time
    )
    
    if exclude_rental_id:
        query = query.filter(RentalHistory.id != exclude_rental_id)
    
    conflicting_booking = query.first()
    return conflicting_booking is not None
