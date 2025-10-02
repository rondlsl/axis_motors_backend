from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.auth.dependencies.save_documents import save_file
import os
from app.models.user_model import User, UserRole
from app.models.guarantor_model import GuarantorRequest
from app.models.application_model import Application
from app.models.car_model import Car, CarStatus, CarBodyType, TransmissionType
from app.models.car_comment_model import CarComment
from app.models.history_model import RentalHistory, RentalStatus, RentalReview
from app.guarantor.sms_utils import send_user_rejection_with_guarantor_sms
from app.guarantor.schemas import (
    GuarantorRequestAdminSchema, 
    AdminApproveGuarantorSchema, 
    AdminRejectGuarantorSchema
)
from pydantic import BaseModel
from datetime import datetime, timedelta
from sqlalchemy import or_, func

# New imports for admin car endpoints
from app.admin.schemas import (
    CarFilterSchema,
    CarMapItemSchema,
    CarMapResponseSchema,
    CarListItemSchema,
    CarListResponseSchema,
    CarStatusUpdateSchema,
    CarStatisticsSchema,
    CarDetailSchema,
    CarEditSchema,
    CarCommentSchema,
    CarCommentCreateSchema,
    CarCommentUpdateSchema,
    UserProfileSchema,
    CarAvailabilityTimerSchema,
    CarCurrentUserSchema,
)
from app.admin.utils import car_to_detail_schema

admin_router = APIRouter(prefix="/admin", tags=["Admin"])
# === Car edit ===
@admin_router.patch("/cars/{car_id}", response_model=CarDetailSchema)
async def edit_car(
    car_id: int,
    body: CarEditSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    # Применяем частичные обновления
    update_fields = body.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        if field == "status" and value is not None:
            setattr(car, "status", value.value)
        else:
            setattr(car, field, value)

    db.commit()
    db.refresh(car)

    return car_to_detail_schema(car)


# === Car comments CRUD ===
@admin_router.get("/cars/{car_id}/comments", response_model=List[CarCommentSchema])
async def get_car_comments(
    car_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    comments = db.query(CarComment).filter(CarComment.car_id == car_id).order_by(CarComment.created_at.desc()).all()
    result: List[CarCommentSchema] = []
    for c in comments:
        author = db.query(User).filter(User.id == c.author_id).first()
        result.append(CarCommentSchema(
            id=c.id,
            car_id=c.car_id,
            author_id=c.author_id,
            author_first_name=author.first_name if author else "",
            author_last_name=author.last_name if author else "",
            author_phone=author.phone_number if author else "",
            author_role=str(author.role) if author and author.role else "",
            comment=c.comment,
            created_at=c.created_at.isoformat() if c.created_at else "",
            is_internal=c.is_internal if hasattr(c, "is_internal") else True,
        ))
    return result


@admin_router.post("/cars/{car_id}/comments", response_model=CarCommentSchema)
async def create_car_comment(
    car_id: int,
    body: CarCommentCreateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    comment = CarComment(
        car_id=car_id,
        author_id=current_user.id,
        comment=body.comment,
        is_internal=body.is_internal,
        created_at=datetime.utcnow(),
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return CarCommentSchema(
        id=comment.id,
        car_id=comment.car_id,
        author_id=comment.author_id,
        author_first_name=current_user.first_name or "",
        author_last_name=current_user.last_name or "",
        author_phone=current_user.phone_number or "",
        author_role=str(current_user.role) if current_user.role else "",
        comment=comment.comment,
        created_at=comment.created_at.isoformat() if comment.created_at else "",
        is_internal=comment.is_internal,
    )


@admin_router.patch("/cars/{car_id}/comments/{comment_id}", response_model=CarCommentSchema)
async def update_car_comment(
    car_id: int,
    comment_id: int,
    body: CarCommentUpdateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    comment = db.query(CarComment).filter(CarComment.id == comment_id, CarComment.car_id == car_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Комментарий не найден")
    if comment.author_id != current_user.id and current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Можно редактировать только свои комментарии")
    comment.comment = body.comment
    db.commit()
    db.refresh(comment)
    author = db.query(User).filter(User.id == comment.author_id).first()
    return CarCommentSchema(
        id=comment.id,
        car_id=comment.car_id,
        author_id=comment.author_id,
        author_first_name=author.first_name if author else "",
        author_last_name=author.last_name if author else "",
        author_phone=author.phone_number if author else "",
        author_role=str(author.role) if author and author.role else "",
        comment=comment.comment,
        created_at=comment.created_at.isoformat() if comment.created_at else "",
        is_internal=comment.is_internal if hasattr(comment, "is_internal") else True,
    )


@admin_router.delete("/cars/{car_id}/comments/{comment_id}")
async def delete_car_comment(
    car_id: int,
    comment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    comment = db.query(CarComment).filter(CarComment.id == comment_id, CarComment.car_id == car_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Комментарий не найден")
    if comment.author_id != current_user.id and current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Можно удалять только свои комментарии")
    db.delete(comment)
    db.commit()
    return {"message": "Комментарий удален"}


# === Car current user (owner / renter) ===
@admin_router.get("/cars/{car_id}/current-user")
async def get_car_current_user(
    car_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Информация о пользователе автомобиля:
    - Если у владельца: профиль владельца
    - Если в аренде: профиль арендатора
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    # Определяем пользователя в контексте авто
    is_owner_ctx = car.status == CarStatus.OWNER.value and car.owner_id is not None
    is_rented_ctx = car.current_renter_id is not None and car.status in [CarStatus.IN_USE.value, CarStatus.DELIVERING.value, CarStatus.RESERVED.value, CarStatus.SCHEDULED.value]

    if is_owner_ctx:
        owner = db.query(User).filter(User.id == car.owner_id).first()
        return {
            "user_type": "owner",
            "user_info": {
                "id": owner.id if owner else None,
                "first_name": owner.first_name if owner else None,
                "last_name": owner.last_name if owner else None,
                "phone_number": owner.phone_number if owner else None,
                "selfie": owner.selfie_with_license_url if owner else None,
            },
            "rental_info": None,
        }

    if is_rented_ctx:
        renter = db.query(User).filter(User.id == car.current_renter_id).first()
        # Найдём активную/последнюю аренду этого авто у пользователя
        rental = (
            db.query(RentalHistory)
            .filter(
                RentalHistory.car_id == car.id,
                RentalHistory.user_id == (renter.id if renter else None),
                RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE, RentalStatus.DELIVERING, RentalStatus.DELIVERING_IN_PROGRESS])
            )
            .order_by(RentalHistory.reservation_time.desc())
            .first()
        )
        return {
            "user_type": "renter",
            "user_info": {
                "id": renter.id if renter else None,
                "first_name": renter.first_name if renter else None,
                "last_name": renter.last_name if renter else None,
                "phone_number": renter.phone_number if renter else None,
                "selfie": renter.selfie_with_license_url if renter else None,
            },
            "rental_info": {
                "rental_id": rental.id if rental else None,
                "status": rental.rental_status.value if rental else None,
                "start_time": rental.start_time.isoformat() if rental and rental.start_time else None,
                "end_time": rental.end_time.isoformat() if rental and rental.end_time else None,
            } if rental else None,
        }

    return {
        "user_type": "none",
        "user_info": None,
        "rental_info": None,
    }


@admin_router.get("/cars/{car_id}/availability-timer", response_model=CarAvailabilityTimerSchema)
async def get_car_availability_timer(
    car_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> CarAvailabilityTimerSchema:
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    now = datetime.utcnow()

    # Найти последний момент завершения аренды этой машины
    last_completed = (
        db.query(RentalHistory)
        .filter(
            RentalHistory.car_id == car.id,
            RentalHistory.rental_status == RentalStatus.COMPLETED,
            RentalHistory.end_time.isnot(None),
        )
        .order_by(RentalHistory.end_time.desc())
        .first()
    )

    # Период доступности начинается с момента последнего завершения аренды
    period_from_dt = last_completed.end_time if last_completed and last_completed.end_time else now
    period_to_dt = now

    # Если машина свободна — считаем доступные секунды с момента period_from_dt, иначе 0
    is_free_like = car.status in [CarStatus.FREE.value, CarStatus.PENDING.value, CarStatus.SERVICE.value]
    total_available_seconds = int((period_to_dt - period_from_dt).total_seconds()) if is_free_like and period_to_dt > period_from_dt else 0

    # Доступные минуты/секунды (для секундомера)
    available_minutes = total_available_seconds // 60
    available_seconds = total_available_seconds % 60

    # Процент доступности за последние 24 часа (наивная оценка)
    window_start = now - timedelta(hours=24)
    # Если период доступности начался до окна, берем пересечение
    overlap_start = max(window_start, period_from_dt)
    available_in_window = int((now - overlap_start).total_seconds()) if is_free_like and now > overlap_start else 0
    availability_percentage = round(min(max(available_in_window / 86400 * 100, 0), 100), 2)

    return CarAvailabilityTimerSchema(
        car_id=car.id,
        car_name=car.name,
        plate_number=car.plate_number,
        available_minutes=available_minutes,
        available_seconds=available_seconds,
        total_available_seconds=total_available_seconds,
        period_from=period_from_dt.isoformat(),
        period_to=period_to_dt.isoformat(),
        availability_percentage=availability_percentage,
        statistics={},
    )


# === Car trips summary statistics ===
@admin_router.get("/cars/{car_id}/history/summary")
async def get_car_history_summary(
    car_id: int,
    month: Optional[int] = None,
    year: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    # Окно дат для календарного фильтра (если задано)
    date_filter = []
    if month and year:
        from calendar import monthrange
        start_dt = datetime(year, month, 1)
        end_dt = datetime(year, month, monthrange(year, month)[1], 23, 59, 59)
        date_filter = [RentalHistory.end_time >= start_dt, RentalHistory.end_time <= end_dt]

    # Доход = total_price по завершённым арендам
    q = db.query(RentalHistory).filter(
        RentalHistory.car_id == car.id,
        RentalHistory.rental_status == RentalStatus.COMPLETED,
        *date_filter
    )
    rentals = q.all()
    total_income = sum(int(r.total_price or 0) for r in rentals)

    # Заработок владельца без доставки и открытия дверей: base + waiting + overtime + distance
    owner_income = sum(
        int((r.base_price or 0) + (r.waiting_fee or 0) + (r.overtime_fee or 0) + (r.distance_fee or 0))
        for r in rentals
    )

    # Доступные минуты из текущего статуса и последней завершённой аренды
    now = datetime.utcnow()
    last_completed = (
        db.query(RentalHistory)
        .filter(RentalHistory.car_id == car.id, RentalHistory.rental_status == RentalStatus.COMPLETED, RentalHistory.end_time.isnot(None))
        .order_by(RentalHistory.end_time.desc())
        .first()
    )
    period_from_dt = last_completed.end_time if last_completed and last_completed.end_time else now
    is_free_like = car.status in [CarStatus.FREE.value, CarStatus.PENDING.value, CarStatus.SERVICE.value]
    total_available_seconds = int((now - period_from_dt).total_seconds()) if is_free_like and now > period_from_dt else 0

    return {
        "car_id": car.id,
        "car_name": car.name,
        "plate_number": car.plate_number,
        "total_income": total_income,
        "owner_income": owner_income,
        "available_minutes": total_available_seconds // 60,
        "available_seconds": total_available_seconds % 60,
        "month": month,
        "year": year,
    }


# === Car trips list ===
@admin_router.get("/cars/{car_id}/history/trips")
async def get_car_trips_list(
    car_id: int,
    month: Optional[int] = None,
    year: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    date_filter = []
    if month and year:
        from calendar import monthrange
        start_dt = datetime(year, month, 1)
        end_dt = datetime(year, month, monthrange(year, month)[1], 23, 59, 59)
        date_filter = [RentalHistory.end_time >= start_dt, RentalHistory.end_time <= end_dt]

    rentals = (
        db.query(RentalHistory, User)
        .join(User, User.id == RentalHistory.user_id)
        .filter(
            RentalHistory.car_id == car.id,
            RentalHistory.rental_status == RentalStatus.COMPLETED,
            *date_filter
        )
        .order_by(RentalHistory.end_time.desc())
        .all()
    )

    items = []
    for r, renter in rentals:
        duration_minutes = 0
        if r.start_time and r.end_time:
            duration_minutes = int((r.end_time - r.start_time).total_seconds() // 60)
        items.append({
            "rental_id": r.id,
            "start_date": r.start_time.isoformat() if r.start_time else None,
            "end_date": r.end_time.isoformat() if r.end_time else None,
            "duration_minutes": duration_minutes,
            "tariff": r.rental_type.value,
            "total_price": r.total_price,
            "renter": {
                "id": renter.id,
                "first_name": renter.first_name,
                "last_name": renter.last_name,
                "phone_number": renter.phone_number,
            }
        })

    return {"trips": items}


# === Trip detail ===
@admin_router.get("/cars/{car_id}/history/trips/{rental_id}")
async def get_trip_detail(
    car_id: int,
    rental_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_id, RentalHistory.car_id == car_id).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Поездка не найдена")
    car = db.query(Car).filter(Car.id == car_id).first()
    renter = db.query(User).filter(User.id == rental.user_id).first()

    # Группы фотографий
    photos = {
        "client_before": rental.photos_before or [],
        "client_after": rental.photos_after or [],
        "mechanic_before": rental.mechanic_photos_before or [],
        "mechanic_after": rental.mechanic_photos_after or [],
    }

    # Отзыв клиента / механика
    review = db.query(RentalReview).filter(RentalReview.rental_id == rental.id).first()

    result = {
        "rental_id": rental.id,
        "car_id": rental.car_id,
        "tariff": rental.rental_type.value,
        "start_time": rental.start_time.isoformat() if rental.start_time else None,
        "end_time": rental.end_time.isoformat() if rental.end_time else None,
        "duration_minutes": int(((rental.end_time - rental.start_time).total_seconds() // 60) if rental.start_time and rental.end_time else 0),
        "prices": {
            "base_price": rental.base_price or 0,
            "open_fee": rental.open_fee or 0,
            "delivery_fee": rental.delivery_fee or 0,
            "waiting_fee": rental.waiting_fee or 0,
            "overtime_fee": rental.overtime_fee or 0,
            "distance_fee": rental.distance_fee or 0,
            "total_price": rental.total_price or 0,
        },
        "fuel": {
            "before": rental.fuel_before,
            "after": rental.fuel_after,
        },
        "client": {
            "id": renter.id if renter else None,
            "first_name": renter.first_name if renter else None,
            "last_name": renter.last_name if renter else None,
            "phone_number": renter.phone_number if renter else None,
        },
        "photos": photos,
        "route": {
            "start": {"latitude": rental.start_latitude, "longitude": rental.start_longitude},
            "end": {"latitude": rental.end_latitude, "longitude": rental.end_longitude},
        },
        "mechanic_route": {
            "start": None,
            "end": None,
        },
        "reviews": {
            "client": {
                "rating": review.rating if review else None,
                "comment": review.comment if review else None,
            },
            "mechanic": {
                "rating": review.mechanic_rating if review else None,
                "comment": review.mechanic_comment if review else None,
                "reaction": None,
            },
            "delivery_mechanic": {
                "rating": review.delivery_mechanic_rating if review else None,
                "comment": review.delivery_mechanic_comment if review else None,
            },
        },
    }

    return result


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


class UpdateUserRoleSchema(BaseModel):
    role: UserRole


@admin_router.get("/pending-users", response_model=List[UserListItemSchema])
async def get_pending_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка пользователей, ожидающих одобрения"""
    
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    pending_users = db.query(User).filter(
        User.role.in_([UserRole.PENDING, UserRole.PENDINGTOFIRST]),
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


@admin_router.get("/clients", response_model=List[UserListItemSchema])
async def get_all_clients(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка всех клиентов (role == CLIENT)"""
    
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    clients = db.query(User).filter(
        User.is_active == True,
        User.role == UserRole.CLIENT
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
        for user in clients
    ]


@admin_router.put("/users/{user_id}/role")
async def update_employee_role(
    user_id: int,
    data: UpdateUserRoleSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Изменение роли сотрудника"""

    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    old_role = user.role.value if user.role else None
    user.role = data.role
    db.commit()
    db.refresh(user)

    return {
        "message": "Роль пользователя обновлена",
        "user_id": user.id,
        "old_role": old_role,
        "new_role": user.role.value
    }


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
            "SERVICE": "На тех обслуживании",
            "DELIVERING": "Доставляется",
            "DELIVERING_IN_PROGRESS": "Доставлено",
            "DELIVERING": "В доставке",
            "COMPLETED": "Завершено",
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
    else:
        # По умолчанию исключаем занятые и забронированные машины
        base_query = base_query.filter(Car.status.notin_([CarStatus.OCCUPIED, CarStatus.SCHEDULED]))

    if search_query:
        like = f"%{search_query}%"
        base_query = base_query.filter(or_(Car.plate_number.ilike(like), Car.name.ilike(like)))

    cars = base_query.all()

    def _status_display(s: Optional[str]) -> str:
        return {
            "FREE": "Свободно",
            "PENDING": "Ожидает механика",
            "IN_USE": "В аренде",
            "SERVICE": "На тех обслуживании",
            "DELIVERING": "В доставке",
            "DELIVERING_IN_PROGRESS": "Доставлено",
            "DELIVERING": "В доставке",
            "COMPLETED": "Завершено",
            "SERVICE": "На обслуживании",
            "RESERVED": "Зарезервирована",
            "SCHEDULED": "Забронирована заранее",
            "OWNER": "У владельца",
            "OCCUPIED": "Занята",
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
    else:
        # По умолчанию исключаем занятые и забронированные машины
        query = query.filter(Car.status.notin_([CarStatus.OCCUPIED, CarStatus.SCHEDULED]))
    if search_query:
        like = f"%{search_query}%"
        query = query.filter(or_(Car.plate_number.ilike(like), Car.name.ilike(like)))

    filtered_cars = query.all()

    def _status_display(s: Optional[str]) -> str:
        return {
            "FREE": "Свободно",
            "PENDING": "Ожидает механика",
            "IN_USE": "В аренде",
            "SERVICE": "На тех обслуживании",
            "DELIVERING": "В доставке",
            "DELIVERING_IN_PROGRESS": "Доставлено",
            "DELIVERING": "В доставке",
            "COMPLETED": "Завершено",
            "SERVICE": "На обслуживании",
            "RESERVED": "Зарезервирована",
            "SCHEDULED": "Забронирована заранее",
            "OWNER": "У владельца",
            "OCCUPIED": "Занята",
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
    service_cars = cars_by_status.get("SERVICE", 0)

    return CarStatisticsSchema(
        total_cars=int(total_cars),
        cars_by_status=cars_by_status,
        cars_by_class=cars_by_class,
        cars_by_body_type=cars_by_body_type,
        active_rentals=int(active_rentals),
        available_cars=int(available_cars),
        service_cars=int(service_cars),
    )

def _get_drive_type_display(drive_type: Optional[int]) -> Optional[str]:
    """Возвращает отображаемое название типа привода"""
    if drive_type is None:
        return None
    drive_map = {
        1: "FWD",  # Передний привод
        2: "RWD",  # Задний привод
        3: "4WD",  # Полный привод
    }
    return drive_map.get(drive_type)


@admin_router.get("/cars/{car_id}/details", response_model=CarDetailSchema)
async def get_car_details(
    car_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> CarDetailSchema:
    """
    Получить детальную информацию об автомобиле
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    # Рассчитываем доступные минуты для текущего месяца
    from app.owner.utils import calculate_month_availability_minutes, ALMATY_TZ
    now = datetime.now(ALMATY_TZ)
    available_minutes = calculate_month_availability_minutes(
        car_id=car.id,
        year=now.year,
        month=now.month,
        owner_id=car.owner_id,
        db=db
    )

    return CarDetailSchema(
        id=car.id,
        name=car.name,
        plate_number=car.plate_number,
        engine_volume=car.engine_volume,
        year=car.year,
        drive_type=car.drive_type,
        drive_type_display=_get_drive_type_display(car.drive_type),
        body_type=car.body_type.value if car.body_type else "UNKNOWN",
        body_type_display=car.body_type.value if car.body_type else "Не указан",
        transmission_type=car.transmission_type.value if car.transmission_type else None,
        transmission_type_display=car.transmission_type.value if car.transmission_type else None,
        status=car.status or CarStatus.FREE,
        status_display={
            "FREE": "Свободно",
            "PENDING": "Ожидает механика",
            "IN_USE": "В аренде",
            "SERVICE": "На обслуживании",
            "DELIVERING": "В доставке",
            "RESERVED": "Зарезервирована",
            "SCHEDULED": "Забронирована заранее",
            "OWNER": "У владельца",
            "OCCUPIED": "Занята",
        }.get(car.status or "FREE", car.status or "Свободно"),
        photos=car.photos or [],
        description=car.description,
        latitude=car.latitude,
        longitude=car.longitude,
        fuel_level=car.fuel_level,
        mileage=car.mileage,
        course=car.course,
        auto_class=car.auto_class.value if car.auto_class else "UNKNOWN",
        price_per_minute=car.price_per_minute,
        price_per_hour=car.price_per_hour,
        price_per_day=car.price_per_day,
        owner_id=car.owner_id,
        current_renter_id=car.current_renter_id,
        available_minutes=available_minutes,
        gps_id=car.gps_id,
        gps_imei=car.gps_imei,
    )


@admin_router.put("/cars/{car_id}")
async def update_car(
    car_id: int,
    car_data: CarEditSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Редактировать автомобиль
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    # Обновляем поля
    update_data = car_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        if hasattr(car, field):
            setattr(car, field, value)

    db.commit()
    db.refresh(car)

    return {
        "message": "Автомобиль успешно обновлен",
        "car_id": car.id,
        "updated_fields": list(update_data.keys())
    }


@admin_router.post("/cars/{car_id}/photos")
async def upload_car_photos(
    car_id: int,
    photos: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Загрузка фотографий автомобиля (append к существующим car.photos).
    multipart/form-data, поле: photos (можно несколько).
    Доступно только администратору.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    saved_paths: List[str] = []
    base_dir = os.path.join("uploads", "cars", str(car.id))
    os.makedirs(base_dir, exist_ok=True)

    for f in photos:
        path = await save_file(f, user_id=car.id, UPLOAD_DIR=base_dir)
        saved_paths.append(path.replace("\\", "/"))

    existing = car.photos or []
    car.photos = existing + saved_paths
    db.commit()
    db.refresh(car)

    return {
        "message": "Фотографии добавлены",
        "car_id": car.id,
        "added": saved_paths,
        "total_photos": len(car.photos or [])
    }

@admin_router.get("/cars/{car_id}/comments", response_model=List[CarCommentSchema])
async def get_car_comments(
    car_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[CarCommentSchema]:
    """
    Получить комментарии к автомобилю
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    comments = (
        db.query(CarComment)
        .filter(CarComment.car_id == car_id)
        .order_by(CarComment.created_at.desc())
        .all()
    )

    result = []
    for comment in comments:
        result.append(CarCommentSchema(
            id=comment.id,
            car_id=comment.car_id,
            author_id=comment.author_id,
            author_first_name=comment.author.first_name or "",
            author_last_name=comment.author.last_name or "",
            author_phone=comment.author.phone_number or "",
            author_role=comment.author.role.value,
            comment=comment.comment,
            created_at=comment.created_at.isoformat(),
            is_internal=comment.is_internal
        ))

    return result


@admin_router.post("/cars/{car_id}/comments", response_model=CarCommentSchema)
async def create_car_comment(
    car_id: int,
    comment_data: CarCommentCreateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> CarCommentSchema:
    """
    Добавить комментарий к автомобилю
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    comment = CarComment(
        car_id=car_id,
        author_id=current_user.id,
        comment=comment_data.comment,
        is_internal=comment_data.is_internal
    )

    db.add(comment)
    db.commit()
    db.refresh(comment)

    author_name = f"{current_user.first_name or ''} {current_user.last_name or ''}".strip()
    if not author_name:
        author_name = current_user.phone_number

    return CarCommentSchema(
        id=comment.id,
        car_id=comment.car_id,
        author_id=comment.author_id,
        author_name=author_name,
        author_role=current_user.role.value,
        comment=comment.comment,
        created_at=comment.created_at.isoformat(),
        is_internal=comment.is_internal
    )


@admin_router.put("/cars/{car_id}/comments/{comment_id}", response_model=CarCommentSchema)
async def update_car_comment(
    car_id: int,
    comment_id: int,
    comment_data: CarCommentUpdateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> CarCommentSchema:
    """
    Обновить комментарий к автомобилю
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    comment = db.query(CarComment).filter(
        CarComment.id == comment_id,
        CarComment.car_id == car_id,
        CarComment.author_id == current_user.id  # Только автор может редактировать
    ).first()

    if not comment:
        raise HTTPException(status_code=404, detail="Комментарий не найден")

    comment.comment = comment_data.comment
    comment.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(comment)

    author_name = f"{current_user.first_name or ''} {current_user.last_name or ''}".strip()
    if not author_name:
        author_name = current_user.phone_number

    return CarCommentSchema(
        id=comment.id,
        car_id=comment.car_id,
        author_id=comment.author_id,
        author_name=author_name,
        author_role=current_user.role.value,
        comment=comment.comment,
        created_at=comment.created_at.isoformat(),
        is_internal=comment.is_internal
    )


@admin_router.delete("/cars/{car_id}/comments/{comment_id}")
async def delete_car_comment(
    car_id: int,
    comment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Удалить комментарий к автомобилю
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    comment = db.query(CarComment).filter(
        CarComment.id == comment_id,
        CarComment.car_id == car_id
    ).first()

    if not comment:
        raise HTTPException(status_code=404, detail="Комментарий не найден")

    # Только автор или админ может удалить
    if comment.author_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав для удаления комментария")

    db.delete(comment)
    db.commit()

    return {"message": "Комментарий успешно удален"}


@admin_router.get("/users/{user_id}/profile", response_model=UserProfileSchema)
async def get_user_profile(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> UserProfileSchema:
    """
    Получить профиль пользователя
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Обработка auto_class
    auto_class_list = []
    if user.auto_class:
        if isinstance(user.auto_class, list):
            auto_class_list = user.auto_class
        elif isinstance(user.auto_class, str):
            raw = user.auto_class.strip()
            if raw.startswith("{") and raw.endswith("}"):
                raw = raw[1:-1]
            auto_class_list = [part.strip() for part in raw.split(",") if part.strip()]

    return UserProfileSchema(
        id=user.id,
        phone_number=user.phone_number,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role.value,
        documents_verified=user.documents_verified,
        auto_class=auto_class_list,
        wallet_balance=float(user.wallet_balance or 0),
        selfie_with_license_url=user.selfie_with_license_url,
        created_at=user.created_at.isoformat() if hasattr(user, 'created_at') else None,
        is_active=user.is_active
    )


@admin_router.get("/cars/{car_id}/current-user", response_model=CarCurrentUserSchema)
async def get_car_current_user(
    car_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> CarCurrentUserSchema:
    """
    Получить информацию о текущем пользователе автомобиля
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    result = CarCurrentUserSchema(user_type="none", user_info=None, rental_info=None)

    if car.status == CarStatus.OWNER and car.owner_id:
        # Автомобиль у владельца
        owner = db.query(User).filter(User.id == car.owner_id).first()
        if owner:
            result.user_type = "owner"
            result.user_info = {
                "id": owner.id,
                "first_name": owner.first_name,
                "last_name": owner.last_name,
                "phone_number": owner.phone_number,
                "selfie_url": owner.selfie_with_license_url,
                "role": owner.role.value
            }
    elif car.current_renter_id:
        # Автомобиль в аренде
        renter = db.query(User).filter(User.id == car.current_renter_id).first()
        if renter:
            result.user_type = "renter"
            result.user_info = {
                "id": renter.id,
                "first_name": renter.first_name,
                "last_name": renter.last_name,
                "phone_number": renter.phone_number,
                "selfie_url": renter.selfie_with_license_url,
                "role": renter.role.value
            }

            # Получаем информацию об активной аренде
            active_rental = db.query(RentalHistory).filter(
                RentalHistory.car_id == car_id,
                RentalHistory.user_id == renter.id,
                RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE, RentalStatus.DELIVERING])
            ).order_by(RentalHistory.start_time.desc()).first()

            if active_rental:
                result.rental_info = {
                    "rental_id": active_rental.id,
                    "rental_type": active_rental.rental_type.value,
                    "start_time": active_rental.start_time.isoformat() if active_rental.start_time else None,
                    "reservation_time": active_rental.reservation_time.isoformat(),
                    "rental_status": active_rental.rental_status.value
                }

    return result


@admin_router.get("/cars/{car_id}/availability-timer", response_model=CarAvailabilityTimerSchema)
async def get_car_availability_timer(
    car_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> CarAvailabilityTimerSchema:
    """
    Получить статистику доступности автомобиля
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    # Используем существующую функцию из owner utils
    from app.owner.utils import calculate_month_availability_minutes, ALMATY_TZ
    now = datetime.now(ALMATY_TZ)
    available_minutes = calculate_month_availability_minutes(
        car_id=car.id,
        year=now.year,
        month=now.month,
        owner_id=car.owner_id,
        db=db
    )

    # Начало текущего месяца
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total_seconds = int((now - month_start).total_seconds())
    available_seconds = available_minutes * 60

    return CarAvailabilityTimerSchema(
        car_id=car.id,
        car_name=car.name,
        plate_number=car.plate_number,
        available_minutes=available_minutes,
        available_seconds=available_seconds % 60,
        total_available_seconds=available_seconds,
        period_from=month_start.isoformat(),
        period_to=now.isoformat(),
        availability_percentage=round((available_seconds / total_seconds * 100) if total_seconds > 0 else 0, 2),
        statistics={
            "total_seconds_in_period": total_seconds,
            "unavailable_seconds": total_seconds - available_seconds,
            "availability_percentage": round((available_seconds / total_seconds * 100) if total_seconds > 0 else 0, 2)
        }
    )


@admin_router.put("/cars/{car_id}/status")
async def update_car_status(
    car_id: int,
    new_status: str,
    reason: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Изменить статус автомобиля
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    # Сохраняем старый статус
    old_status = car.status
    
    # Обновляем статус
    car.status = new_status
    db.commit()
    db.refresh(car)

    # Если это изменение связано с арендой, записываем в rental_history
    if new_status in ["IN_USE", "DELIVERING", "DELIVERING_IN_PROGRESS", "COMPLETED"]:
        # Находим активную аренду для этого автомобиля
        active_rental = (
            db.query(RentalHistory)
            .filter(
                RentalHistory.car_id == car_id,
                RentalHistory.rental_status.in_([
                    RentalStatus.RESERVED,
                    RentalStatus.IN_USE,
                    RentalStatus.DELIVERING,
                    RentalStatus.DELIVERING_IN_PROGRESS
                ])
            )
            .order_by(RentalHistory.reservation_time.desc())
            .first()
        )
        
        if active_rental:
            # Обновляем статус аренды
            status_mapping = {
                "IN_USE": RentalStatus.IN_USE,
                "DELIVERING": RentalStatus.DELIVERING,
                "DELIVERING_IN_PROGRESS": RentalStatus.DELIVERING_IN_PROGRESS,
                "DELIVERING": RentalStatus.DELIVERING,
                "COMPLETED": RentalStatus.COMPLETED
            }
            
            if new_status in status_mapping:
                active_rental.rental_status = status_mapping[new_status]
                db.commit()

    return {
        "message": "Статус автомобиля обновлен",
        "car_id": car_id,
        "old_status": old_status,
        "new_status": new_status,
        "reason": reason
    }


@admin_router.get("/cars/{car_id}/rental-history")
async def get_car_rental_history(
    car_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получить историю аренды автомобиля (включая изменения статуса)
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.MECHANIC]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    # Получаем историю аренды
    rentals = (
        db.query(RentalHistory)
        .filter(RentalHistory.car_id == car_id)
        .order_by(RentalHistory.reservation_time.desc())
        .all()
    )

    result = []
    for rental in rentals:
        # Получаем отзыв для этой аренды
        review = db.query(RentalReview).filter(RentalReview.rental_id == rental.id).first()
        
        # Доставка: данные механика доставки (если есть)
        delivery_mechanic = getattr(rental, "delivery_mechanic", None)
        delivery_mechanic_info = None
        if delivery_mechanic:
            delivery_mechanic_info = {
                "id": delivery_mechanic.id,
                "first_name": delivery_mechanic.first_name or "",
                "last_name": delivery_mechanic.last_name or "",
                "phone_number": delivery_mechanic.phone_number or "",
            }

        # Осмотр: данные механика-инспектора (если есть)
        inspection_mechanic = None
        inspection_mechanic_info = None
        if rental.mechanic_inspector_id:
            inspection_mechanic = db.query(User).filter(User.id == rental.mechanic_inspector_id).first()
            if inspection_mechanic:
                inspection_mechanic_info = {
                    "id": inspection_mechanic.id,
                    "first_name": inspection_mechanic.first_name or "",
                    "last_name": inspection_mechanic.last_name or "",
                    "phone_number": inspection_mechanic.phone_number or "",
                }

        result.append({
            "id": rental.id,
            "user_id": rental.user_id,
            "user_name": f"{rental.user.first_name or ''} {rental.user.last_name or ''}".strip() or rental.user.phone_number,
            "rental_status": rental.rental_status.value,
            "start_time": rental.start_time.isoformat() if rental.start_time else None,
            "end_time": rental.end_time.isoformat() if rental.end_time else None,
            "reservation_time": rental.reservation_time.isoformat(),
            "total_price": rental.total_price,
            "client_photos_before": rental.photos_before or [],
            "client_photos_after": rental.photos_after or [],
            "delivery_photos_before": rental.delivery_photos_before or [],
            "delivery_photos_after": rental.delivery_photos_after or [],
            "delivery_mechanic": delivery_mechanic_info,
            "mechanic_photos_before": rental.mechanic_photos_before or [],
            "mechanic_photos_after": rental.mechanic_photos_after or [],
            "inspection_mechanic": inspection_mechanic_info,
            "inspection_start_time": rental.mechanic_inspection_start_time.isoformat() if rental.mechanic_inspection_start_time else None,
            "inspection_end_time": rental.mechanic_inspection_end_time.isoformat() if rental.mechanic_inspection_end_time else None,
            "inspection_status": rental.mechanic_inspection_status,
            "inspection_comment": rental.mechanic_inspection_comment,
            # Отзывы
            "client_rating": review.rating if review else None,
            "client_comment": review.comment if review else None,
            "mechanic_rating": review.mechanic_rating if review else None,
            "mechanic_comment": review.mechanic_comment if review else None,
            "delivery_mechanic_rating": review.delivery_mechanic_rating if review else None,
            "delivery_mechanic_comment": review.delivery_mechanic_comment if review else None,
        })

    return result


router = admin_router
