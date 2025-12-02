import asyncio
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from app.models.user_model import User, UserRole
from app.models.car_model import Car, CarStatus, CarAutoClass
from app.models.history_model import RentalHistory, RentalStatus, RentalType
from app.utils.short_id import uuid_to_sid
from app.rent.utils.user_utils import get_user_available_auto_classes
from app.admin.cars.utils import sort_car_photos
from app.rent.utils.calculate_price import get_open_price
from app.utils.user_data import get_user_me_data
from app.gps_api.utils.glonassoft_client import glonassoft_client
from app.gps_api.utils.telemetry_processor import process_glonassoft_data


async def get_vehicles_data_for_user(user: User, db: Session) -> Dict[str, Any]:
    """Получить данные списка машин для пользователя."""
    try:
        if user.role == UserRole.MECHANIC:
            query = db.query(Car)
            if user.phone_number not in ["71011111111", "71234567890", "77057726400"]:
                query = query.filter(Car.plate_number != "666AZV02")
        else:
            active_rental = db.query(RentalHistory).filter(
                RentalHistory.user_id == user.id,
                RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
            ).first()
            
            if active_rental:
                query = db.query(Car).filter(Car.id == active_rental.car_id)
            else:
                query = db.query(Car).filter(Car.status.in_([CarStatus.FREE, CarStatus.OCCUPIED]))
                if user.phone_number not in ["71011111111", "71234567890", "77057726400"]:
                    query = query.filter(Car.plate_number != "666AZV02")

        if user.role == UserRole.USER and bool(user.documents_verified):
            available_classes = get_user_available_auto_classes(user, db)
            
            if not available_classes:
                allowed_classes: list[str] = []
                if isinstance(user.auto_class, list):
                    allowed_classes = [str(c).strip().upper() for c in user.auto_class if c]
                elif isinstance(user.auto_class, str):
                    raw = user.auto_class.strip()
                    if raw.startswith("{") and raw.endswith("}"):
                        raw = raw[1:-1]
                    raw = raw.replace('""', '').replace('"', '').replace("'", "")
                    allowed_classes = [part.strip().upper() for part in raw.split(",") if part.strip()]
                
                available_classes = allowed_classes
            
            allowed_enum: list[CarAutoClass] = []
            for cls in available_classes:
                try:
                    allowed_enum.append(CarAutoClass(cls))
                except Exception:
                    pass

            if len(allowed_enum) == 0:
                cars = []
            else:
                cars = query.filter(Car.auto_class.in_(allowed_enum)).all()
        elif user.role in [UserRole.REJECTFIRST, UserRole.REJECTFIRSTCERT, UserRole.REJECTFIRSTDOC]:
            available_classes = get_user_available_auto_classes(user, db)
            
            if available_classes:
                allowed_enum: list[CarAutoClass] = []
                for cls in available_classes:
                    try:
                        allowed_enum.append(CarAutoClass(cls))
                    except Exception:
                        pass
                
                if allowed_enum:
                    cars = query.filter(Car.auto_class.in_(allowed_enum)).all()
                else:
                    cars = query.all()
            else:
                cars = query.all()
        else:
            cars = query.all()

        async def get_car_speed(car: Car) -> Optional[float]:
            """Получить скорость машины из телеметрии"""
            try:
                vehicle_imei = (
                    getattr(car, 'gps_imei', None)
                    or getattr(car, 'imei', None)
                    or getattr(car, 'vehicle_imei', None)
                )
                if not vehicle_imei:
                    return None
                
                glonassoft_data = await glonassoft_client.get_vehicle_data(vehicle_imei)
                if glonassoft_data:
                    telemetry = process_glonassoft_data(glonassoft_data, car.name)
                    return telemetry.speed if hasattr(telemetry, 'speed') else None
                return None
            except Exception:
                return None
        
        speed_tasks = [get_car_speed(car) for car in cars]
        speeds = await asyncio.gather(*speed_tasks, return_exceptions=True)
        car_speeds = {}
        for i, car in enumerate(cars):
            speed = speeds[i]
            if isinstance(speed, Exception) or speed is None:
                car_speeds[car.id] = None
            else:
                car_speeds[car.id] = speed

        vehicles_data = []
        for car in cars:
            photo_before_selfie_uploaded = False
            photo_before_car_uploaded = False
            photo_before_interior_uploaded = False
            photo_after_selfie_uploaded = False
            photo_after_car_uploaded = False
            photo_after_interior_uploaded = False
            
            active_rental = db.query(RentalHistory).filter(
                RentalHistory.user_id == user.id,
                RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
            ).first()
            
            if active_rental and active_rental.car_id != car.id:
                active_rental = None
            
            # Получаем информацию о текущем арендаторе и активной аренде
            current_renter_info = None
            current_rental_info = None
            
            if car.current_renter_id:
                current_renter = db.query(User).filter(User.id == car.current_renter_id).first()
                if current_renter:
                    # Ищем активную аренду для этой машины
                    active_rental_for_car = (
                        db.query(RentalHistory)
                        .filter(
                            RentalHistory.car_id == car.id,
                            RentalHistory.user_id == current_renter.id,
                            RentalHistory.rental_status.in_([
                                RentalStatus.RESERVED,
                                RentalStatus.IN_USE,
                                RentalStatus.DELIVERING,
                                RentalStatus.DELIVERY_RESERVED,
                                RentalStatus.DELIVERING_IN_PROGRESS
                            ])
                        )
                        .order_by(RentalHistory.reservation_time.desc())
                        .first()
                    )
                    
                    current_renter_info = {
                        "id": uuid_to_sid(current_renter.id),
                        "first_name": current_renter.first_name,
                        "last_name": current_renter.last_name,
                        "middle_name": current_renter.middle_name,
                        "phone_number": current_renter.phone_number,
                        "selfie_url": current_renter.selfie_with_license_url
                    }
                    
                    if active_rental_for_car:
                        before_rental_selfie_url = None
                        if active_rental_for_car.photos_before:
                            for photo in active_rental_for_car.photos_before:
                                if ("/before/selfie/" in photo) or ("\\before\\selfie\\" in photo):
                                    before_rental_selfie_url = photo
                                    break
                        
                        rental_tariff_type = active_rental_for_car.rental_type.value if active_rental_for_car.rental_type else None
                        
                        rental_duration_time = None
                        if active_rental_for_car.rental_type in [RentalType.HOURS, RentalType.DAYS] and active_rental_for_car.duration:
                            rental_duration_time = active_rental_for_car.duration
                        
                        current_rental_info = {
                            "rental_id": uuid_to_sid(active_rental_for_car.id),
                            "rental_status": active_rental_for_car.rental_status.value if active_rental_for_car.rental_status else None,
                            "rental_type": rental_tariff_type,
                            "reservation_time": active_rental_for_car.reservation_time.isoformat() if active_rental_for_car.reservation_time else None,
                            "start_time": active_rental_for_car.start_time.isoformat() if active_rental_for_car.start_time else None,
                            "end_time": active_rental_for_car.end_time.isoformat() if active_rental_for_car.end_time else None,
                            "before_rental_selfie_url": before_rental_selfie_url,
                            "rental_duration_time": rental_duration_time
                        }
            
            if active_rental and active_rental.photos_before:
                photos_before = active_rental.photos_before
                photo_before_selfie_uploaded = any(
                    ("/before/selfie/" in photo) or ("\\before\\selfie\\" in photo) 
                    for photo in photos_before
                )
                photo_before_car_uploaded = any(
                    ("/before/car/" in photo) or ("\\before\\car\\" in photo) 
                    for photo in photos_before
                )
                photo_before_interior_uploaded = any(
                    ("/before/interior/" in photo) or ("\\before\\interior\\" in photo) 
                    for photo in photos_before
                )
            
            if active_rental and active_rental.photos_after:
                photos_after = active_rental.photos_after
                photo_after_selfie_uploaded = any(
                    ("/after/selfie/" in photo) or ("\\after\\selfie\\" in photo) 
                    for photo in photos_after
                )
                photo_after_car_uploaded = any(
                    ("/after/car/" in photo) or ("\\after\\car\\" in photo) 
                    for photo in photos_after
                )
                photo_after_interior_uploaded = any(
                    ("/after/interior/" in photo) or ("\\after\\interior\\" in photo) 
                    for photo in photos_after
                )
            
            vehicles_data.append({
                "id": uuid_to_sid(car.id),
                "name": car.name,
                "plate_number": car.plate_number,
                "latitude": car.latitude,
                "longitude": car.longitude,
                "course": car.course,
                "speed": car_speeds.get(car.id),
                "fuel_level": car.fuel_level,
                "price_per_minute": car.price_per_minute,
                "price_per_hour": car.price_per_hour,
                "price_per_day": car.price_per_day,
                "engine_volume": car.engine_volume,
                "year": car.year,
                "drive_type": car.drive_type,
                "transmission_type": car.transmission_type,
                "body_type": car.body_type,
                "auto_class": car.auto_class,
                "photos": sort_car_photos(car.photos or []),
                "owner_id": uuid_to_sid(car.owner_id),
                "current_renter_id": uuid_to_sid(car.current_renter_id) if car.current_renter_id else None,
                "current_renter": current_renter_info,
                "current_rental": current_rental_info,
                "status": car.status,
                "open_price": get_open_price(car),
                "owned_car": True if car.owner_id == user.id else False,
                "vin": car.vin,
                "color": car.color,
                "description": car.description,
                "photo_before_selfie_uploaded": photo_before_selfie_uploaded,
                "photo_before_car_uploaded": photo_before_car_uploaded,
                "photo_before_interior_uploaded": photo_before_interior_uploaded,
                "photo_after_selfie_uploaded": photo_after_selfie_uploaded,
                "photo_after_car_uploaded": photo_after_car_uploaded,
                "photo_after_interior_uploaded": photo_after_interior_uploaded
            })

        return {
            "vehicles": vehicles_data,
            "fcm_token": user.fcm_token
        }
    except Exception as e:
        return {"vehicles": [], "error": str(e)}


async def get_user_status_data(user: User, db: Session) -> Dict[str, Any]:
    """Получить данные статуса пользователя."""
    try:
        return await get_user_me_data(db, user)
    except Exception as e:
        return {"error": str(e)}

