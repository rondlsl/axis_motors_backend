"""
Error Logs API for monitoring and analytics
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import Optional, List
from datetime import datetime, timedelta
from pydantic import BaseModel
from uuid import UUID

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.error_log_model import ErrorLog


router = APIRouter(prefix="/error-logs", tags=["Error Logs"])


class ErrorLogSchema(BaseModel):
    id: UUID
    error_type: str
    message: Optional[str]
    endpoint: Optional[str]
    method: Optional[str]
    user_id: Optional[UUID]
    user_phone: Optional[str]
    source: str
    created_at: datetime

    class Config:
        from_attributes = True


class ErrorLogDetailSchema(ErrorLogSchema):
    traceback: Optional[str]
    context: Optional[dict]


class ErrorStatsSchema(BaseModel):
    total_errors: int
    type: dict
    endpoint: dict
    day: List[dict]


@router.get("/list", response_model=List[ErrorLogSchema])
async def get_error_logs(
    period: str = Query("day", regex="^(day|week|month|all)$"),
    error_type: Optional[str] = None,
    endpoint: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get error logs with filtering by period"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        return []
    
    query = db.query(ErrorLog)
    
    # Filter by period
    now = datetime.utcnow()
    if period == "day":
        query = query.filter(ErrorLog.created_at >= now - timedelta(days=1))
    elif period == "week":
        query = query.filter(ErrorLog.created_at >= now - timedelta(weeks=1))
    elif period == "month":
        query = query.filter(ErrorLog.created_at >= now - timedelta(days=30))
    
    # Filter by error type
    if error_type:
        query = query.filter(ErrorLog.error_type == error_type)
    
    # Filter by endpoint
    if endpoint:
        query = query.filter(ErrorLog.endpoint.ilike(f"%{endpoint}%"))
    
    # Paginate
    offset = (page - 1) * per_page
    logs = query.order_by(desc(ErrorLog.created_at)).offset(offset).limit(per_page).all()
    
    return logs


@router.get("/stats", response_model=ErrorStatsSchema)
async def get_error_stats(
    period: str = Query("day", regex="^(day|week|month|all)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get error statistics for dashboard"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        return {"total_errors": 0, "type": {}, "endpoint": {}, "day": []}
    
    now = datetime.utcnow()
    
    # Base query with period filter
    if period == "day":
        start_date = now - timedelta(days=1)
    elif period == "week":
        start_date = now - timedelta(weeks=1)
    elif period == "month":
        start_date = now - timedelta(days=30)
    else:
        start_date = None
    
    base_query = db.query(ErrorLog)
    if start_date:
        base_query = base_query.filter(ErrorLog.created_at >= start_date)
    
    # Total errors
    total_errors = base_query.count()
    
    # By error type
    type_stats = base_query.with_entities(
        ErrorLog.error_type,
        func.count(ErrorLog.id).label('count')
    ).group_by(ErrorLog.error_type).order_by(desc('count')).limit(10).all()
    by_type = {t[0]: t[1] for t in type_stats}
    
    # By endpoint
    endpoint_stats = base_query.filter(ErrorLog.endpoint.isnot(None)).with_entities(
        ErrorLog.endpoint,
        func.count(ErrorLog.id).label('count')
    ).group_by(ErrorLog.endpoint).order_by(desc('count')).limit(10).all()
    by_endpoint = {e[0]: e[1] for e in endpoint_stats}
    
    # By day (last 7 days)
    seven_days_ago = now - timedelta(days=7)
    daily_stats = db.query(
        func.date(ErrorLog.created_at).label('date'),
        func.count(ErrorLog.id).label('count')
    ).filter(ErrorLog.created_at >= seven_days_ago).group_by(
        func.date(ErrorLog.created_at)
    ).order_by(desc('date')).all()
    by_day = [{"date": str(d[0]), "count": d[1]} for d in daily_stats]
    
    return {
        "total_errors": total_errors,
        "type": by_type,
        "endpoint": by_endpoint,
        "day": by_day
    }


@router.get("/{error_id}", response_model=ErrorLogDetailSchema)
async def get_error_detail(
    error_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get error log detail with traceback"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        return None
    
    error = db.query(ErrorLog).filter(ErrorLog.id == error_id).first()
    return error
