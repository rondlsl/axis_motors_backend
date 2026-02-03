"""Support users list — тот же контракт, что и GET /admin/users/list."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.dependencies.database.database import get_db
from app.admin.users.router import get_users_list_impl
from app.admin.users.schemas import UserPaginatedResponse
from app.support.deps import require_support_role

users_router = APIRouter(tags=["Support users"])


@users_router.get("/list", response_model=UserPaginatedResponse)
async def get_support_users_list(
    role: Optional[str] = Query(None, description="Фильтр по роли"),
    search_query: Optional[str] = Query(None, description="Поиск по имени, фамилии, телефону, ИИН или паспорту"),
    has_active_rental: Optional[bool] = Query(None, description="Фильтр по активной аренде"),
    is_blocked: Optional[bool] = Query(None, description="Фильтр по заблокированным пользователям"),
    mvd_approved: Optional[bool] = Query(None, description="Фильтр по МВД одобрению"),
    car_status: Optional[str] = Query(None, description="Фильтр по статусу авто"),
    auto_class: Optional[List[str]] = Query(None, description="Фильтр по классу авто (A, B, C, AB, ABC)"),
    balance_filter: Optional[str] = Query(None, description="Фильтр по балансу (positive / negative)"),
    documents_verified: Optional[bool] = Query(None, description="Фильтр по проверке документов"),
    is_active: Optional[bool] = Query(None, description="Фильтр по активности пользователя"),
    is_verified_email: Optional[bool] = Query(None, description="Фильтр по подтверждению email"),
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(50, ge=1, le=200, description="Количество элементов на странице"),
    current_user=Depends(require_support_role),
    db: Session = Depends(get_db),
) -> UserPaginatedResponse:
    """Список пользователей с фильтрацией и поиском (тот же endpoint, что /admin/users/list)."""
    return get_users_list_impl(
        db,
        role=role,
        search_query=search_query,
        has_active_rental=has_active_rental,
        is_blocked=is_blocked,
        mvd_approved=mvd_approved,
        car_status=car_status,
        auto_class=auto_class,
        balance_filter=balance_filter,
        documents_verified=documents_verified,
        is_active=is_active,
        is_verified_email=is_verified_email,
        page=page,
        limit=limit,
    )
