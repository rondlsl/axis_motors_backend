from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
from app.utils.short_id import safe_sid_to_uuid
from app.utils.sid_converter import convert_uuid_response_to_sid

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.support_action_model import SupportAction
from app.admin.support.schemas import (
    SupportActionsListResponse,
    SupportActionItemSchema,
    SupportUserSchema,
)


support_router = APIRouter(tags=["Admin Support"])


@support_router.get("/actions", response_model=SupportActionsListResponse)
async def list_support_actions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> SupportActionsListResponse:
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    q = db.query(SupportAction)
    if user_id is not None:
        user_uuid = safe_sid_to_uuid(user_id)
        q = q.filter(SupportAction.user_id == user_uuid)
    if action:
        like = f"%{action}%"
        q = q.filter(SupportAction.action.ilike(like))

    total = q.count()
    items = (
        q.order_by(SupportAction.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # preload users
    user_ids = {i.user_id for i in items}
    users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
    users_map = {u.id: u for u in users}

    data: List[SupportActionItemSchema] = []
    for it in items:
        u = users_map.get(it.user_id)
        action_data = {
            "id": it.id,
            "user": {
                "id": u.id if u else it.user_id,
                "first_name": u.first_name if u else None,
                "last_name": u.last_name if u else None,
                "phone_number": u.phone_number if u else None,
                "role": u.role.value if u and u.role else None,
            },
            "action": it.action,
            "entity_type": it.entity_type,
            "entity_id": it.entity_id,
            "created_at": it.created_at.isoformat(),
        }
        
        converted_data = convert_uuid_response_to_sid(action_data, ["id", "entity_id"])
        user_data = convert_uuid_response_to_sid(converted_data["user"], ["id"])
        converted_data["user"] = user_data
        
        data.append(SupportActionItemSchema(**converted_data))

    return SupportActionsListResponse(
        items=data,
        page=page,
        page_size=page_size,
        total=total,
    )


@support_router.get("/users/{user_id}", response_model=SupportUserSchema)
async def get_support_user_profile(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> SupportUserSchema:
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPPORT]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    user_uuid = safe_sid_to_uuid(user_id)
    u = db.query(User).filter(User.id == user_uuid, User.role.in_([UserRole.ADMIN, UserRole.SUPPORT])).first()
    if not u:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    user_data = {
        "id": u.id,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "phone_number": u.phone_number,
        "role": u.role.value,
    }
    
    converted_data = convert_uuid_response_to_sid(user_data, ["id"])
    return SupportUserSchema(**converted_data)


