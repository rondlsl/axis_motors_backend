from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole, AutoClass
from app.models.guarantor_model import GuarantorRequest
from app.models.application_model import Application
from app.models.car_model import Car
from app.guarantor.sms_utils import send_user_rejection_with_guarantor_sms
from app.guarantor.schemas import (
    GuarantorRequestAdminSchema, 
    AdminApproveGuarantorSchema, 
    AdminRejectGuarantorSchema
)
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy import or_, func

# New imports for admin car endpoints
from app.admin.schemas import (
    CarFilterSchema,
    CarMapItemSchema,
    CarMapResponseSchema,
    CarListItemSchema,
    CarListResponseSchema,
    CarStatusUpdateSchema,
    CarStatus,
    CarStatisticsSchema,
)

admin_router = APIRouter(prefix="/admin", tags=["Admin"])


class UserApprovalSchema(BaseModel):
    user_id: int
    approved: bool
    rejection_reason: str = None


class UserListItemSchema(BaseModel):
    id: int
    phone_number: str
    first_name: str = None
    last_name: str = None
    role: str
    created_at: str = None
    documents_verified: bool
    
    class Config:
        from_attributes = True


@admin_router.get("/pending-users", response_model=List[UserListItemSchema])
async def get_pending_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка пользователей, ожидающих одобрения"""
    
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    pending_users = db.query(User).filter(
        User.role == UserRole.PENDING,
        User.is_active == True
    ).all()
    
    return [
        UserListItemSchema(
            id=user.id,
            phone_number=user.phone_number,
            first_name=user.first_name,
            last_name=user.last_name,
            role=user.role.value,
            documents_verified=user.documents_verified
        )
        for user in pending_users
    ]


@admin_router.post("/approve-user")
async def approve_or_reject_user(
    approval_data: UserApprovalSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Одобрение или отклонение пользователя с возможностью предложения гаранта"""
    
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user = db.query(User).filter(User.id == approval_data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    if approval_data.approved:
        user.documents_verified = True
        # Создаем заявку для проверки финансистом
        # Проверяем, есть ли уже заявка для этого пользователя
        existing_application = db.query(Application).filter(Application.user_id == user.id).first()
        
        if not existing_application:
            application = Application(
                user_id=user.id,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(application)
        
        db.commit()
        
        return {"message": "Документы одобрены. Заявка передана на рассмотрение финансисту."}
    else:
        # Отклоняем пользователя
        user.role = UserRole.REJECTED
        db.commit()
        
        # Отправляем SMS с предложением гаранта
        if approval_data.rejection_reason:
            # Формируем имя для SMS
            user_display_name = None
            if user.first_name and user.last_name:
                user_display_name = f"{user.first_name} {user.last_name}"
            elif user.first_name:
                user_display_name = user.first_name
            else:
                user_display_name = user.phone_number
                
            sms_result = await send_user_rejection_with_guarantor_sms(
                user.phone_number,
                user_display_name,
                approval_data.rejection_reason
            )
            
            return {
                "message": "Пользователь отклонен. SMS с предложением гаранта отправлено.",
                "sms_result": sms_result
            }
        else:
            return {"message": "Пользователь отклонен"}


@admin_router.get("/users", response_model=List[UserListItemSchema])
async def get_all_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка всех пользователей"""
    
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    users = db.query(User).filter(User.is_active == True).all()
    
    return [
        UserListItemSchema(
            id=user.id,
            phone_number=user.phone_number,
            first_name=user.first_name,
            last_name=user.last_name,
            role=user.role.value,
            documents_verified=user.documents_verified
        )
        for user in users
    ]


@admin_router.get("/guarantor-requests", response_model=List[GuarantorRequestAdminSchema])
async def get_guarantor_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    show_verified: bool = False
):
    """Получение списка заявок гарантов для проверки"""
    
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    query = db.query(GuarantorRequest)
    
    if not show_verified:
        query = query.filter(GuarantorRequest.verification_status == "not_verified")
    
    requests = query.all()
    
    result = []
    for request in requests:
        requestor = db.query(User).filter(User.id == request.requestor_id).first()
        guarantor = None
        if request.guarantor_id:
            guarantor = db.query(User).filter(User.id == request.guarantor_id).first()
        
        result.append(GuarantorRequestAdminSchema(
            id=request.id,
            requestor_id=request.requestor_id,
            requestor_first_name=requestor.first_name if requestor else None,
            requestor_last_name=requestor.last_name if requestor else None,
            requestor_phone=requestor.phone_number if requestor else "Unknown",
            guarantor_id=request.guarantor_id,
            guarantor_phone=guarantor.phone_number if guarantor else request.guarantor_phone,
            status=request.status.value,
            verification_status=request.verification_status,
            reason=request.reason,
            admin_notes=request.admin_notes,
            created_at=request.created_at,
            responded_at=request.responded_at,
            verified_at=request.verified_at
        ))
    
    return result


@admin_router.post("/guarantor-requests/{request_id}/approve")
async def approve_guarantor_request(
    request_id: int,
    approval_data: AdminApproveGuarantorSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Одобрение заявки гаранта администратором"""
    
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    request = db.query(GuarantorRequest).filter(GuarantorRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    # Обновляем статус заявки
    request.verification_status = "verified"
    request.admin_notes = approval_data.admin_notes
    request.verified_at = datetime.utcnow()
    
    # Присваиваем классы авто клиенту (requestor)
    requestor = db.query(User).filter(User.id == request.requestor_id).first()
    if requestor:
        # Конвертируем схемы в строки
        auto_classes_strings = [cls.value for cls in approval_data.auto_classes]
        requestor.auto_class = auto_classes_strings
    
    db.commit()
    
    return {
        "message": "Заявка одобрена",
        "assigned_classes": [cls.value for cls in approval_data.auto_classes]
    }


@admin_router.post("/guarantor-requests/{request_id}/reject")
async def reject_guarantor_request(
    request_id: int,
    rejection_data: AdminRejectGuarantorSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Отклонение заявки гаранта администратором"""
    
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    request = db.query(GuarantorRequest).filter(GuarantorRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    # Обновляем статус заявки
    request.verification_status = "rejected"
    request.admin_notes = rejection_data.admin_notes
    request.verified_at = datetime.utcnow()
    
    db.commit()
    
    return {"message": "Заявка отклонена"}


@admin_router.get("/cars", response_model=Dict[str, List[Dict[str, Any]]])
async def get_all_cars_for_admin(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение всех автомобилей для админ панели"""
    
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    cars = db.query(Car).all()
    
    vehicles_data = []
    for car in cars:
        # Определяем статус для отображения
        status_display = {
            "FREE": "Свободно",
            "IN_USE": "В аренде", 
            "MAINTENANCE": "На тех обслуживании",
            "DELIVERING": "Доставляется",
            "DELIVERED": "Доставлено",
            "RETURNING": "Возвращается",
            "RETURNED": "Возвращено",
            "OWNER": "У владельца"
        }.get(car.status, car.status)
        
        # Получаем данные арендатора если есть
        current_renter_details = None
        if car.current_renter_id:
            renter = db.query(User).filter(User.id == car.current_renter_id).first()
            if renter:
                current_renter_details = {
                    "first_name": renter.first_name,
                    "last_name": renter.last_name,
                    "selfie": renter.selfie_with_license_url
                }
        
        vehicle_data = {
            "id": car.id,
            "name": car.name,
            "status": status_display,
            "lat": car.latitude or 0.0,
            "lng": car.longitude or 0.0,
            "fuel": car.fuel_level or 0,  # Преобразуем fuel_level в fuel для frontend
            "plate": car.plate_number,
            "photos": car.photos or [],
            "course": car.course or 0,
            "user": current_renter_details
        }
        vehicles_data.append(vehicle_data)
    
    return {"cars": vehicles_data}

@admin_router.get("/cars/map", response_model=CarMapResponseSchema)
async def get_cars_map(
    status: Optional[CarStatus] = None,
    search_query: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> CarMapResponseSchema:
    """
    Карта автопарка: вернуть все машины с координатами и статусами.
    Фильтры: статус и поиск по госномеру/марке.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    base_query = db.query(Car)

    if status is not None:
        base_query = base_query.filter(Car.status == status.value)

    if search_query:
        like = f"%{search_query}%"
        base_query = base_query.filter(or_(Car.plate_number.ilike(like), Car.name.ilike(like)))

    cars = base_query.all()

    def _status_display(s: Optional[str]) -> str:
        return {
            "FREE": "Свободно",
            "IN_USE": "В аренде",
            "MAINTENANCE": "На тех обслуживании",
            "DELIVERING": "В доставке",
            "DELIVERED": "Доставлено",
            "RETURNING": "Возвращается",
            "RETURNED": "Возвращено",
            "OWNER": "У владельца",
        }.get(s or "", s or "")

    items: List[CarMapItemSchema] = []
    for car in cars:
        renter_info = None
        if car.current_renter_id:
            renter = db.query(User).filter(User.id == car.current_renter_id).first()
            if renter:
                renter_info = {
                    "first_name": renter.first_name,
                    "last_name": renter.last_name,
                    "selfie": renter.selfie_with_license_url,
                }
        items.append(CarMapItemSchema(
            id=car.id,
            name=car.name,
            plate_number=car.plate_number,
            status=car.status,
            status_display=_status_display(car.status),
            latitude=car.latitude,
            longitude=car.longitude,
            fuel_level=car.fuel_level,
            course=car.course,
            photos=car.photos or [],
            current_renter=renter_info,
        ))

    return CarMapResponseSchema(cars=items, total_count=len(items))


@admin_router.get("/cars/list", response_model=CarListResponseSchema)
async def get_cars_list(
    status: Optional[CarStatus] = None,
    search_query: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> CarListResponseSchema:
    """
    Список автомобилей с фильтрами/поиском для боковой панели.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    total_count = db.query(Car).count()

    query = db.query(Car)
    if status is not None:
        query = query.filter(Car.status == status.value)
    if search_query:
        like = f"%{search_query}%"
        query = query.filter(or_(Car.plate_number.ilike(like), Car.name.ilike(like)))

    filtered_cars = query.all()

    def _status_display(s: Optional[str]) -> str:
        return {
            "FREE": "Свободно",
            "IN_USE": "В аренде",
            "MAINTENANCE": "На тех обслуживании",
            "DELIVERING": "В доставке",
            "DELIVERED": "Доставлено",
            "RETURNING": "Возвращается",
            "RETURNED": "Возвращено",
            "OWNER": "У владельца",
        }.get(s or "", s or "")

    items: List[CarListItemSchema] = []
    for car in filtered_cars:
        owner_name = None
        if car.owner_id:
            owner = db.query(User).filter(User.id == car.owner_id).first()
            if owner:
                owner_name = f"{owner.first_name or ''} {owner.last_name or ''}".strip() or owner.phone_number
        current_renter_name = None
        if car.current_renter_id:
            renter = db.query(User).filter(User.id == car.current_renter_id).first()
            if renter:
                current_renter_name = f"{renter.first_name or ''} {renter.last_name or ''}".strip() or renter.phone_number

        items.append(CarListItemSchema(
            id=car.id,
            name=car.name,
            plate_number=car.plate_number,
            status=car.status,
            status_display=_status_display(car.status),
            latitude=car.latitude,
            longitude=car.longitude,
            fuel_level=car.fuel_level,
            mileage=car.mileage,
            auto_class=car.auto_class.value if car.auto_class else "",
            body_type=car.body_type.value if car.body_type else "",
            year=car.year,
            owner_name=owner_name,
            current_renter_name=current_renter_name,
            photos=car.photos or [],
        ))

    return CarListResponseSchema(
        cars=items,
        total_count=total_count,
        filtered_count=len(items),
    )


@admin_router.post("/cars/{car_id}/status")
async def update_car_status(
    car_id: int,
    payload: CarStatusUpdateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Обновить статус автомобиля. Доступно только из админки.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    car.status = payload.status.value
    db.commit()

    return {
        "message": "Статус обновлён",
        "car_id": car.id,
        "status": car.status,
        "reason": payload.reason,
    }


@admin_router.get("/cars/statistics", response_model=CarStatisticsSchema)
async def get_cars_statistics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> CarStatisticsSchema:
    """
    Статистика по автопарку: общее количество, по статусам, классам и типам кузова.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    total_cars = db.query(func.count(Car.id)).scalar() or 0

    # By status
    rows = db.query(Car.status, func.count(Car.id)).group_by(Car.status).all()
    cars_by_status: Dict[str, int] = {row[0] or "UNKNOWN": int(row[1] or 0) for row in rows}

    # By class
    rows_class = db.query(Car.auto_class, func.count(Car.id)).group_by(Car.auto_class).all()
    cars_by_class: Dict[str, int] = { (rc[0].value if rc[0] else "UNKNOWN"): int(rc[1] or 0) for rc in rows_class }

    # By body type
    rows_body = db.query(Car.body_type, func.count(Car.id)).group_by(Car.body_type).all()
    cars_by_body_type: Dict[str, int] = { (rb[0].value if rb[0] else "UNKNOWN"): int(rb[1] or 0) for rb in rows_body }

    active_rentals = cars_by_status.get("IN_USE", 0)
    available_cars = cars_by_status.get("FREE", 0)
    maintenance_cars = cars_by_status.get("MAINTENANCE", 0)

    return CarStatisticsSchema(
        total_cars=int(total_cars),
        cars_by_status=cars_by_status,
        cars_by_class=cars_by_class,
        cars_by_body_type=cars_by_body_type,
        active_rentals=int(active_rentals),
        available_cars=int(available_cars),
        maintenance_cars=int(maintenance_cars),
    )
