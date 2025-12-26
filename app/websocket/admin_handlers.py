from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_
import asyncio

from app.models.car_model import Car, CarStatus
from app.models.user_model import User
from app.utils.short_id import uuid_to_sid
from app.admin.cars.utils import sort_car_photos
from app.admin.cars.schemas import (
    CarListItemSchema, 
    CarListResponseSchema, 
    OwnerSchema, 
    CurrentRenterSchema
)
from app.gps_api.utils.glonassoft_client import glonassoft_client
from app.gps_api.utils.telemetry_processor import process_glonassoft_data

async def get_admin_cars_list_data(
    db: Session, 
    status: Optional[str] = None, 
    search_query: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get admin cars list data, mirroring the logic of GET /admin/cars/list
    """
    query = db.query(Car)
    
    if status is not None:
        query = query.filter(Car.status == status)
        
    if search_query:
        search_query = search_query.strip()
        if search_query:
            like = f"%{search_query}%"
            query = query.filter(or_(Car.plate_number.ilike(like), Car.name.ilike(like)))
    
    total_count = db.query(Car).count()
    filtered_cars = query.all()
    
    # Получаем скорости для всех машин из телеметрии
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
    
    speed_tasks = [get_car_speed(car) for car in filtered_cars]
    speeds = await asyncio.gather(*speed_tasks, return_exceptions=True)
    car_speeds = {}
    for i, car in enumerate(filtered_cars):
        speed = speeds[i]
        if isinstance(speed, Exception) or speed is None:
            car_speeds[car.id] = None
        else:
            car_speeds[car.id] = speed

    def _status_display(s: Optional[str]) -> str:
        return {
            "FREE": "Свободно",
            "PENDING": "Ожидает механика",
            "IN_USE": "В аренде",
            "SERVICE": "На тех обслуживании",
            "DELIVERING": "В доставке",
            "DELIVERY_RESERVED": "Доставка зарезервирована",
            "DELIVERING_IN_PROGRESS": "Доставлено",
            "COMPLETED": "Завершено",
            "RESERVED": "Зарезервирована",
            "SCHEDULED": "Забронирована заранее",
            "OWNER": "У владельца",
            "OCCUPIED": "Занята",
        }.get(s or "", s or "")

    items = []
    for car in filtered_cars:
        owner_obj = None
        if car.owner_id:
            owner = db.query(User).filter(User.id == car.owner_id).first()
            if owner:
                owner_obj = {
                    "owner_id": uuid_to_sid(owner.id),
                    "first_name": owner.first_name,
                    "last_name": owner.last_name,
                    "middle_name": owner.middle_name,
                    "phone_number": owner.phone_number,
                    "selfie": owner.selfie_url or owner.selfie_with_license_url
                }
        
        current_renter_obj = None
        if car.current_renter_id:
            renter = db.query(User).filter(User.id == car.current_renter_id).first()
            if renter:
                current_renter_obj = {
                    "current_renter_id": uuid_to_sid(renter.id),
                    "first_name": renter.first_name,
                    "last_name": renter.last_name,
                    "middle_name": renter.middle_name,
                    "phone_number": renter.phone_number,
                    "role": renter.role.value if renter.role else "client",
                    "selfie": renter.selfie_url or renter.selfie_with_license_url
                }

        car_status = car.status.value if isinstance(car.status, CarStatus) else str(car.status)
        
        if car.status == CarStatus.DELIVERING:
            car_status = "DELIVERY_RESERVED"
        elif car.status == "DELIVERING":
            car_status = "DELIVERY_RESERVED"
            
        if current_renter_obj and current_renter_obj.get("role") == "mechanic":
            car_status = "SERVICE"
        
        has_gps = car.gps_id is not None and str(car.gps_id).strip() != ""
        latitude = -1.0 if not has_gps else car.latitude
        longitude = -1.0 if not has_gps else car.longitude

        items.append({
            "id": uuid_to_sid(car.id),
            "name": car.name,
            "plate_number": car.plate_number,
            "status": car_status,
            "status_display": _status_display(car_status),
            "latitude": latitude,
            "longitude": longitude,
            "fuel_level": car.fuel_level,
            "mileage": car.mileage,
            "speed": car_speeds.get(car.id),
            "auto_class": car.auto_class.value if car.auto_class else "",
            "body_type": car.body_type.value if car.body_type else "",
            "year": car.year,
            "owner": owner_obj,
            "current_renter": current_renter_obj,
            "photos": sort_car_photos(car.photos or []),
            "vin": car.vin,
            "color": car.color,
            "rating": car.rating,
        })

    return {
        "cars": items,
        "total_count": total_count,
        "filtered_count": len(items),
    }


async def get_admin_users_list_data(
    db: Session,
    role: Optional[str] = None,
    search_query: Optional[str] = None,
    has_active_rental: Optional[bool] = None,
    is_blocked: Optional[bool] = None,
    car_status_filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get admin users list data with coordinates, mirroring GET /admin/users/list (оптимизировано)
    """
    from app.models.user_model import UserRole
    from app.models.history_model import RentalHistory, RentalStatus
    from sqlalchemy import func, case
    
    active_statuses = [
        RentalStatus.IN_USE, 
        RentalStatus.DELIVERING, 
        RentalStatus.DELIVERING_IN_PROGRESS,
        RentalStatus.RESERVED,
        RentalStatus.SCHEDULED,
        RentalStatus.DELIVERY_RESERVED
    ]
    
    active_rental_subq = (
        db.query(
            RentalHistory.user_id,
            RentalHistory.rental_status,
            RentalHistory.car_id
        )
        .filter(RentalHistory.rental_status.in_(active_statuses))
        .subquery()
    )
    
    query = (
        db.query(
            User,
            active_rental_subq.c.rental_status,
            active_rental_subq.c.car_id,
            Car.id.label("car_id_real"),
            Car.name.label("car_name"),
            Car.plate_number.label("car_plate"),
            Car.photos.label("car_photos"),
            Car.latitude.label("car_lat"),
            Car.longitude.label("car_lon"),
            Car.fuel_level.label("car_fuel")
        )
        .outerjoin(active_rental_subq, User.id == active_rental_subq.c.user_id)
        .outerjoin(Car, Car.id == active_rental_subq.c.car_id)
    )
    
    if role:
        try:
            role_enum = UserRole(role)
            query = query.filter(User.role == role_enum)
        except ValueError:
            pass
    
    if is_blocked is not None:
        query = query.filter(User.is_active == (not is_blocked))
    
    if search_query:
        search_query = search_query.strip()
        if search_query:
            search_filter = or_(
                func.lower(User.first_name).contains(search_query.lower()),
                func.lower(User.last_name).contains(search_query.lower()),
                User.phone_number.contains(search_query),
                User.iin.contains(search_query),
                User.passport_number.contains(search_query)
            )
            query = query.filter(search_filter)
    
    if has_active_rental is True:
        query = query.filter(active_rental_subq.c.user_id.isnot(None))
    elif has_active_rental is False:
        query = query.filter(active_rental_subq.c.user_id.is_(None))
    
    query = query.order_by(
        case(
            (active_rental_subq.c.user_id.isnot(None), 0),
            else_=1
        ),
        User.id
    )
    
    rows = query.all()
    
    result = []
    seen_user_ids = set()
    
    for row in rows:
        user = row[0]
        rental_status = row[1]
        car_id = row[2]
        car_name = row[4]
        car_plate = row[5]
        car_photos = row[6]
        car_lat = row[7]
        car_lon = row[8]
        car_fuel = row[9]
        
        if user.id in seen_user_ids:
            continue
        seen_user_ids.add(user.id)
        
        current_car = None
        if car_id and car_name:
            current_car = {
                "id": uuid_to_sid(car_id),
                "name": car_name,
                "plate_number": car_plate,
                "photos": car_photos,
                "latitude": car_lat,
                "longitude": car_lon,
                "fuel_level": car_fuel
            }
        
        has_active = current_car is not None
        
        auto_class_list = []
        if user.auto_class:
            if isinstance(user.auto_class, list):
                auto_class_list = user.auto_class
            elif isinstance(user.auto_class, str):
                raw = user.auto_class.strip()
                if raw.startswith("{") and raw.endswith("}"):
                    raw = raw[1:-1]
                auto_class_list = [p.strip() for p in raw.split(",") if p.strip()]
        
        car_status = "FREE"
        if rental_status:
            if rental_status == RentalStatus.IN_USE:
                car_status = "IN_USE"
            elif rental_status == RentalStatus.RESERVED:
                car_status = "RESERVED"
            elif rental_status == RentalStatus.SCHEDULED:
                car_status = "SCHEDULED"
            elif rental_status in [RentalStatus.DELIVERING, RentalStatus.DELIVERING_IN_PROGRESS]:
                car_status = "DELIVERING_IN_PROGRESS"
            elif rental_status == RentalStatus.DELIVERY_RESERVED:
                car_status = "DELIVERY_RESERVED"
        
        if car_status == "FREE":
            if user.owned_cars:
                car_status = "OWNER"
            elif user.role in [UserRole.PENDING, UserRole.PENDINGTOFIRST, UserRole.PENDINGTOSECOND] or user.role.value.startswith("PENDING") or user.role.value.startswith("REJECT"):
                if user.role.value.startswith("PENDING"):
                    car_status = "PENDING"
        
        if car_status_filter is not None and car_status != car_status_filter:
            continue
        
        user_data = {
            "id": uuid_to_sid(user.id),
            "first_name": user.first_name,
            "last_name": user.last_name,
            "middle_name": user.middle_name,
            "phone_number": user.phone_number,
            "iin": user.iin,
            "passport_number": user.passport_number,
            "role": user.role.value,
            "auto_class": auto_class_list,
            "selfie_url": user.selfie_url,
            "is_blocked": not user.is_active,
            "current_rental_car": current_car,
            "rating": float(user.rating) if user.rating else None,
            "carStatus": car_status
        }
        
        result.append(user_data)
    
    return {
        "users": result,
        "total_count": len(result)
    }
