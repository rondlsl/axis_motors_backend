from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_

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
            "speed": car.speed if hasattr(car, 'speed') else None,
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
