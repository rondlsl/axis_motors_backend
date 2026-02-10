"""
Endpoints для просмотра истории осмотров механика (admin).

GET /admin/mechanics/{mechanic_id}/inspections/summary
GET /admin/mechanics/{mechanic_id}/inspections
GET /admin/mechanics/{mechanic_id}/inspections/{rental_id}
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from math import ceil
from collections import defaultdict
from datetime import datetime
from calendar import monthrange
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import Optional

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.car_model import Car
from app.models.history_model import RentalHistory, RentalReview
from app.utils.short_id import safe_sid_to_uuid, uuid_to_sid
from app.utils.time_utils import get_local_time
from app.core.logging_config import get_logger

logger = get_logger(__name__)

mechanics_router = APIRouter(tags=["Admin Mechanics"])


def _get_mechanic_user(db: Session, mechanic_id: str) -> User:
    """Получить пользователя-механика по short id."""
    mechanic_uuid = safe_sid_to_uuid(mechanic_id)
    user = db.query(User).filter(User.id == mechanic_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Механик не найден")
    return user


def _inspection_status_display(status: Optional[str]) -> str:
    return {
        "PENDING": "Ожидает осмотра",
        "IN_PROGRESS": "Осмотр в процессе",
        "IN_USE": "Осмотр в процессе",
        "COMPLETED": "Осмотр завершён",
        "CANCELLED": "Осмотр отменён",
    }.get(status or "", status or "—")


# ──────────────────────────────────────────────────────────────────────
# 1. Summary: агрегация по месяцам
# ──────────────────────────────────────────────────────────────────────

@mechanics_router.get("/{mechanic_id}/inspections/summary")
async def get_mechanic_inspections_summary(
    mechanic_id: str,
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(12, ge=1, le=60, description="Количество месяцев на странице"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Агрегированные данные по месяцам для механика.
    Возвращает количество осмотров, завершённых / в процессе и т.д.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    mechanic = _get_mechanic_user(db, mechanic_id)

    # Все аренды, где этот механик был инспектором
    rentals = (
        db.query(RentalHistory)
        .filter(RentalHistory.mechanic_inspector_id == mechanic.id)
        .all()
    )

    # Группировка по месяцам
    monthly_data = defaultdict(lambda: {
        "inspections_count": 0,
        "completed_count": 0,
        "cancelled_count": 0,
        "in_progress_count": 0,
    })

    for r in rentals:
        date_key = (
            r.mechanic_inspection_end_time
            or r.mechanic_inspection_start_time
            or r.end_time
            or r.start_time
            or r.reservation_time
        )
        if not date_key:
            continue
        month_key = (date_key.year, date_key.month)
        monthly_data[month_key]["inspections_count"] += 1
        status = (r.mechanic_inspection_status or "").upper()
        if status == "COMPLETED":
            monthly_data[month_key]["completed_count"] += 1
        elif status in ("CANCELLED",):
            monthly_data[month_key]["cancelled_count"] += 1
        else:
            monthly_data[month_key]["in_progress_count"] += 1

    sorted_months = sorted(monthly_data.keys(), reverse=True)
    total_months = len(sorted_months)
    paginated = sorted_months[(page - 1) * limit : page * limit]

    now = get_local_time()
    current_month_key = (now.year, now.month)

    months_result = []
    for year, month in paginated:
        d = monthly_data[(year, month)]
        months_result.append({
            "year": year,
            "month": month,
            "inspections_count": d["inspections_count"],
            "completed_count": d["completed_count"],
            "cancelled_count": d["cancelled_count"],
            "in_progress_count": d["in_progress_count"],
            "is_current_month": (year, month) == current_month_key,
        })

    return {
        "mechanic_id": uuid_to_sid(mechanic.id),
        "mechanic_name": f"{mechanic.first_name or ''} {mechanic.last_name or ''}".strip(),
        "phone_number": mechanic.phone_number,
        "current_month": {"year": now.year, "month": now.month},
        "months": months_result,
        "total": total_months,
        "page": page,
        "limit": limit,
        "pages": ceil(total_months / limit) if limit > 0 else 0,
    }


# ──────────────────────────────────────────────────────────────────────
# 2. List: осмотры за выбранный месяц (или все)
# ──────────────────────────────────────────────────────────────────────

@mechanics_router.get("/{mechanic_id}/inspections")
async def get_mechanic_inspections_list(
    mechanic_id: str,
    month: Optional[int] = Query(None, ge=1, le=12, description="Месяц (1-12). Если не указан — все"),
    year: Optional[int] = Query(None, description="Год. Если не указан — все"),
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(50, ge=1, le=200, description="Элементов на странице"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Список осмотров механика (с пагинацией).
    Если указаны month/year — фильтрация по месяцу.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    mechanic = _get_mechanic_user(db, mechanic_id)

    base_q = (
        db.query(RentalHistory, User, Car)
        .outerjoin(User, User.id == RentalHistory.user_id)
        .outerjoin(Car, Car.id == RentalHistory.car_id)
        .filter(RentalHistory.mechanic_inspector_id == mechanic.id)
    )

    # Фильтр по месяцу
    if month is not None and year is not None:
        start_dt = datetime(year, month, 1)
        end_dt = datetime(year, month, monthrange(year, month)[1], 23, 59, 59)
        base_q = base_q.filter(
            or_(
                and_(RentalHistory.mechanic_inspection_start_time >= start_dt,
                     RentalHistory.mechanic_inspection_start_time <= end_dt),
                and_(RentalHistory.mechanic_inspection_end_time >= start_dt,
                     RentalHistory.mechanic_inspection_end_time <= end_dt),
                and_(RentalHistory.reservation_time >= start_dt,
                     RentalHistory.reservation_time <= end_dt),
            )
        )

    base_q = base_q.order_by(RentalHistory.mechanic_inspection_start_time.desc().nullslast())

    total = base_q.count()
    rows = base_q.offset((page - 1) * limit).limit(limit).all()

    items = []
    for rental, renter, car in rows:
        duration_minutes = 0
        if rental.mechanic_inspection_start_time and rental.mechanic_inspection_end_time:
            duration_minutes = int(
                (rental.mechanic_inspection_end_time - rental.mechanic_inspection_start_time).total_seconds() // 60
            )

        items.append({
            "rental_id": uuid_to_sid(rental.id),
            "inspection_status": rental.mechanic_inspection_status,
            "inspection_status_display": _inspection_status_display(rental.mechanic_inspection_status),
            "inspection_start_time": (
                rental.mechanic_inspection_start_time.isoformat()
                if rental.mechanic_inspection_start_time else None
            ),
            "inspection_end_time": (
                rental.mechanic_inspection_end_time.isoformat()
                if rental.mechanic_inspection_end_time else None
            ),
            "inspection_duration_minutes": duration_minutes,
            "inspection_comment": rental.mechanic_inspection_comment,
            "car": {
                "id": uuid_to_sid(car.id) if car else None,
                "name": car.name if car else None,
                "plate_number": car.plate_number if car else None,
                "photos": (car.photos[:1] if car and car.photos else []),
            } if car else None,
            "renter": {
                "id": uuid_to_sid(renter.id) if renter else None,
                "first_name": renter.first_name if renter else None,
                "last_name": renter.last_name if renter else None,
                "phone_number": renter.phone_number if renter else None,
                "selfie": renter.selfie_url if renter else None,
            } if renter else None,
            "reservation_time": rental.reservation_time.isoformat() if rental.reservation_time else None,
            "rental_start_time": rental.start_time.isoformat() if rental.start_time else None,
            "rental_end_time": rental.end_time.isoformat() if rental.end_time else None,
        })

    return {
        "inspections": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": ceil(total / limit) if limit > 0 else 0,
    }


# ──────────────────────────────────────────────────────────────────────
# 3. Detail: детальная информация об одном осмотре
# ──────────────────────────────────────────────────────────────────────

@mechanics_router.get("/{mechanic_id}/inspections/{rental_id}")
async def get_mechanic_inspection_detail(
    mechanic_id: str,
    rental_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Детальная информация об осмотре механика для конкретной аренды."""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    mechanic = _get_mechanic_user(db, mechanic_id)
    rental_uuid = safe_sid_to_uuid(rental_id)

    rental = (
        db.query(RentalHistory)
        .filter(
            RentalHistory.id == rental_uuid,
            RentalHistory.mechanic_inspector_id == mechanic.id,
        )
        .first()
    )
    if not rental:
        raise HTTPException(status_code=404, detail="Осмотр не найден")

    car = db.query(Car).filter(Car.id == rental.car_id).first()
    renter = db.query(User).filter(User.id == rental.user_id).first()
    review = db.query(RentalReview).filter(RentalReview.rental_id == rental.id).first()

    # Длительность осмотра
    inspection_duration_minutes = 0
    if rental.mechanic_inspection_start_time and rental.mechanic_inspection_end_time:
        inspection_duration_minutes = int(
            (rental.mechanic_inspection_end_time - rental.mechanic_inspection_start_time).total_seconds() // 60
        )

    # Длительность аренды
    rental_duration_minutes = 0
    if rental.start_time and rental.end_time:
        rental_duration_minutes = int(
            (rental.end_time - rental.start_time).total_seconds() // 60
        )

    # Тариф
    tariff_display = ""
    if rental.rental_type:
        tariff_value = rental.rental_type.value if hasattr(rental.rental_type, "value") else str(rental.rental_type)
        tariff_display = {"minutes": "Минутный", "hours": "Часовой", "days": "Суточный"}.get(
            tariff_value, tariff_value
        )

    return {
        "rental_id": uuid_to_sid(rental.id),

        # ── Осмотр ──
        "inspection": {
            "status": rental.mechanic_inspection_status,
            "status_display": _inspection_status_display(rental.mechanic_inspection_status),
            "start_time": (
                rental.mechanic_inspection_start_time.isoformat()
                if rental.mechanic_inspection_start_time else None
            ),
            "end_time": (
                rental.mechanic_inspection_end_time.isoformat()
                if rental.mechanic_inspection_end_time else None
            ),
            "duration_minutes": inspection_duration_minutes,
            "comment": rental.mechanic_inspection_comment,
            "photos_before": rental.mechanic_photos_before or [],
            "photos_after": rental.mechanic_photos_after or [],
            "route": {
                "start_latitude": rental.mechanic_inspection_start_latitude,
                "start_longitude": rental.mechanic_inspection_start_longitude,
                "end_latitude": rental.mechanic_inspection_end_latitude,
                "end_longitude": rental.mechanic_inspection_end_longitude,
            },
        },

        # ── Механик ──
        "mechanic": {
            "id": uuid_to_sid(mechanic.id),
            "first_name": mechanic.first_name,
            "last_name": mechanic.last_name,
            "phone_number": mechanic.phone_number,
            "selfie": mechanic.selfie_url,
        },

        # ── Машина ──
        "car": {
            "id": uuid_to_sid(car.id) if car else None,
            "name": car.name if car else None,
            "plate_number": car.plate_number if car else None,
            "status": car.status.value if car and car.status else None,
            "photos": car.photos or [] if car else [],
        } if car else None,

        # ── Арендатор ──
        "renter": {
            "id": uuid_to_sid(renter.id) if renter else None,
            "first_name": renter.first_name if renter else None,
            "last_name": renter.last_name if renter else None,
            "phone_number": renter.phone_number if renter else None,
            "selfie": renter.selfie_url if renter else None,
        } if renter else None,

        # ── Аренда (краткая информация) ──
        "rental": {
            "reservation_time": rental.reservation_time.isoformat() if rental.reservation_time else None,
            "start_time": rental.start_time.isoformat() if rental.start_time else None,
            "end_time": rental.end_time.isoformat() if rental.end_time else None,
            "duration_minutes": rental_duration_minutes,
            "rental_status": rental.rental_status.value if rental.rental_status else None,
            "tariff": rental.rental_type.value if rental.rental_type else None,
            "tariff_display": tariff_display,
            "total_price": rental.total_price,
            "fuel_before": rental.fuel_before,
            "fuel_after": rental.fuel_after,
            "mileage_before": rental.mileage_before,
            "mileage_after": rental.mileage_after,
        },

        # ── Фотографии клиента (для сравнения) ──
        "client_photos": {
            "before": rental.photos_before or [],
            "after": rental.photos_after or [],
        },

        # ── Отзыв механика ──
        "review": {
            "mechanic_rating": review.mechanic_rating if review else None,
            "mechanic_comment": review.mechanic_comment if review else None,
        },
    }
