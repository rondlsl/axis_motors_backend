"""
Support endpoints для просмотра истории осмотров механика.

GET /support/mechanics/{mechanic_id}/inspections/summary?page=1&limit=60
GET /support/mechanics/{mechanic_id}/inspections?page=1&limit=50
"""

from collections import defaultdict
from math import ceil
from calendar import monthrange
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.dependencies.database.database import get_db
from app.models.user_model import User
from app.models.car_model import Car
from app.models.history_model import RentalHistory
from app.support.deps import require_support_role
from app.utils.short_id import safe_sid_to_uuid, uuid_to_sid
from app.utils.time_utils import get_local_time

support_mechanics_router = APIRouter(tags=["Support Mechanics"])


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

@support_mechanics_router.get("/{mechanic_id}/inspections/summary")
async def get_mechanic_inspections_summary(
    mechanic_id: str,
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(60, ge=1, le=60, description="Количество месяцев на странице"),
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """
    Агрегированные данные по месяцам для механика (support).
    Возвращает количество осмотров, завершённых / в процессе и т.д.
    """
    mechanic = _get_mechanic_user(db, mechanic_id)

    rentals = (
        db.query(RentalHistory)
        .filter(RentalHistory.mechanic_inspector_id == mechanic.id)
        .all()
    )

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
        elif status == "CANCELLED":
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
# 2. List: список осмотров (с пагинацией)
# ──────────────────────────────────────────────────────────────────────

@support_mechanics_router.get("/{mechanic_id}/inspections")
async def get_mechanic_inspections_list(
    mechanic_id: str,
    month: Optional[int] = Query(None, ge=1, le=12, description="Месяц (1-12). Если не указан — все"),
    year: Optional[int] = Query(None, description="Год. Если не указан — все"),
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(50, ge=1, le=200, description="Элементов на странице"),
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """
    Список осмотров механика (support, с пагинацией).
    Если указаны month/year — фильтрация по месяцу.
    """
    mechanic = _get_mechanic_user(db, mechanic_id)

    base_q = (
        db.query(RentalHistory, User, Car)
        .outerjoin(User, User.id == RentalHistory.user_id)
        .outerjoin(Car, Car.id == RentalHistory.car_id)
        .filter(RentalHistory.mechanic_inspector_id == mechanic.id)
    )

    if month is not None and year is not None:
        start_dt = datetime(year, month, 1)
        end_dt = datetime(year, month, monthrange(year, month)[1], 23, 59, 59)
        base_q = base_q.filter(
            or_(
                and_(
                    RentalHistory.mechanic_inspection_start_time >= start_dt,
                    RentalHistory.mechanic_inspection_start_time <= end_dt,
                ),
                and_(
                    RentalHistory.mechanic_inspection_end_time >= start_dt,
                    RentalHistory.mechanic_inspection_end_time <= end_dt,
                ),
                and_(
                    RentalHistory.reservation_time >= start_dt,
                    RentalHistory.reservation_time <= end_dt,
                ),
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
