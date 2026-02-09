from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.core.logging_config import get_logger
from app.auth.dependencies.get_current_user import get_current_user
from app.dependencies.database.database import get_db
from app.models.user_model import User, UserRole
from app.utils.short_id import uuid_to_sid, safe_sid_to_uuid
from app.promo.schemas import (
    PromoCreateRequest,
    PromoUpdateRequest,
    PromoOut,
    PromoListResponse,
    PromoDetailResponse,
    PromoUsageOut,
)
from app.promo.service import (
    create_promo_code,
    get_promo_list,
    get_promo_detail,
    get_unique_users_count,
)
from app.models.bonus_promo_model import BonusPromoCode

logger = get_logger(__name__)

promo_admin_router = APIRouter(tags=["Admin Promo"])


def _ensure_admin(user: User):
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")


@promo_admin_router.post("", response_model=PromoOut, status_code=201)
async def admin_create_promo(
    body: PromoCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Создать новый бонусный промокод."""
    _ensure_admin(current_user)

    # Проверка уникальности кода
    existing = db.query(BonusPromoCode).filter(BonusPromoCode.code == body.code.strip()).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Промокод «{body.code}» уже существует")

    promo = await create_promo_code(
        db,
        code=body.code,
        description=body.description,
        bonus_amount=body.bonus_amount,
        valid_from=body.valid_from,
        valid_to=body.valid_to,
        max_uses=body.max_uses,
    )

    return PromoOut(
        id=promo.sid,
        code=promo.code,
        description=promo.description,
        bonus_amount=promo.bonus_amount,
        valid_from=promo.valid_from,
        valid_to=promo.valid_to,
        max_uses=promo.max_uses,
        used_count=promo.used_count,
        is_active=promo.is_active,
        created_at=promo.created_at,
        unique_users=0,
    )


@promo_admin_router.get("", response_model=PromoListResponse)
def admin_list_promos(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Список всех бонусных промокодов."""
    _ensure_admin(current_user)

    promos, total = get_promo_list(db, limit=limit, offset=offset)

    items = []
    for p in promos:
        unique = get_unique_users_count(db, p.id)
        items.append(PromoOut(
            id=p.sid,
            code=p.code,
            description=p.description,
            bonus_amount=p.bonus_amount,
            valid_from=p.valid_from,
            valid_to=p.valid_to,
            max_uses=p.max_uses,
            used_count=p.used_count,
            is_active=p.is_active,
            created_at=p.created_at,
            unique_users=unique,
        ))

    return PromoListResponse(promo_codes=items, total=total)


@promo_admin_router.get("/{promo_id}", response_model=PromoDetailResponse)
def admin_get_promo_detail(
    promo_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Детальная информация о промокоде + список использований."""
    _ensure_admin(current_user)

    try:
        promo_uuid = safe_sid_to_uuid(promo_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат ID")

    promo, usages = get_promo_detail(db, promo_uuid)
    if promo is None:
        raise HTTPException(status_code=404, detail="Промокод не найден")

    unique = get_unique_users_count(db, promo.id)

    usage_items = []
    for u in usages:
        user = u.user
        usage_items.append(PromoUsageOut(
            id=u.sid,
            user_id=uuid_to_sid(u.user_id),
            user_phone=user.phone_number if user else None,
            user_name=f"{user.first_name or ''} {user.last_name or ''}".strip() if user else None,
            selfie_url=user.selfie_url if user else None,
            used_at=u.used_at,
        ))

    return PromoDetailResponse(
        id=promo.sid,
        code=promo.code,
        description=promo.description,
        bonus_amount=promo.bonus_amount,
        valid_from=promo.valid_from,
        valid_to=promo.valid_to,
        max_uses=promo.max_uses,
        used_count=promo.used_count,
        is_active=promo.is_active,
        created_at=promo.created_at,
        unique_users=unique,
        usages=usage_items,
    )


@promo_admin_router.patch("/{promo_id}", response_model=PromoOut)
async def admin_update_promo(
    promo_id: str,
    body: PromoUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Обновить бонусный промокод."""
    _ensure_admin(current_user)

    try:
        promo_uuid = safe_sid_to_uuid(promo_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат ID")

    promo = db.query(BonusPromoCode).filter(BonusPromoCode.id == promo_uuid).first()
    if promo is None:
        raise HTTPException(status_code=404, detail="Промокод не найден")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(promo, field, value)

    db.commit()
    db.refresh(promo)

    # Инвалидируем Redis-кэш
    from app.promo.service import _invalidate_promo_cache
    await _invalidate_promo_cache(promo.code)

    unique = get_unique_users_count(db, promo.id)

    return PromoOut(
        id=promo.sid,
        code=promo.code,
        description=promo.description,
        bonus_amount=promo.bonus_amount,
        valid_from=promo.valid_from,
        valid_to=promo.valid_to,
        max_uses=promo.max_uses,
        used_count=promo.used_count,
        is_active=promo.is_active,
        created_at=promo.created_at,
        unique_users=unique,
    )
