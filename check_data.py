#!/usr/bin/env python3
import sys
sys.path.append('/app')
from app.core.config import DATABASE_URL
from sqlalchemy import create_engine, text
from app.models.car_model import Car
from app.models.history_model import RentalHistory, RentalStatus
from app.models.user_model import User, UserRole
from sqlalchemy.orm import sessionmaker

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db = SessionLocal()

print('=== Проверка автомобилей ===')
cars = db.query(Car).all()
for car in cars:
    print(f'Car ID: {car.id}, Name: {car.name}, Owner: {car.owner_id}, Status: {car.status}')

print('\n=== Проверка поездок ===')
rentals = db.query(RentalHistory).all()
for rental in rentals:
    print(f'Rental ID: {rental.id}, Car ID: {rental.car_id}, Status: {rental.rental_status}, User ID: {rental.user_id}')

print('\n=== Проверка пользователей ===')
users = db.query(User).all()
for user in users:
    print(f'User ID: {user.id}, Role: {user.role}, Phone: {user.phone_number}')

print('\n=== Проверка завершенных поездок ===')
completed_rentals = db.query(RentalHistory).filter(RentalHistory.rental_status == RentalStatus.COMPLETED).all()
print(f'Количество завершенных поездок: {len(completed_rentals)}')
for rental in completed_rentals:
    print(f'Rental ID: {rental.id}, Car ID: {rental.car_id}, Status: {rental.rental_status}')

print('\n=== Проверка автомобилей в статусе FREE ===')
free_cars = db.query(Car).filter(Car.status == "FREE").all()
print(f'Количество автомобилей в статусе FREE: {len(free_cars)}')
for car in free_cars:
    print(f'Car ID: {car.id}, Name: {car.name}, Status: {car.status}')

db.close()
