from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.application_model import Application, ApplicationStatus
from app.admin.users.schemas import UserProfileSchema, UserRoleUpdateSchema

users_router = APIRouter(tags=["Admin Users"])


@users_router.get("/pending", response_model=List[UserProfileSchema])
async def get_pending_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение пользователей, ожидающих одобрения"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    # Получаем пользователей с ролью PENDING
    users = db.query(User).filter(User.role == UserRole.PENDING).all()
    
    result = []
    for user in users:
        result.append(UserProfileSchema(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            phone_number=user.phone_number,
            role=user.role.value,
            is_active=user.is_active,
            is_verified_email=user.is_verified_email,
            is_citizen_kz=user.is_citizen_kz,
            documents_verified=user.documents_verified,
            selfie_url=user.selfie_url,
            selfie_with_license_url=user.selfie_with_license_url,
            drivers_license_url=user.drivers_license_url,
            id_card_front_url=user.id_card_front_url,
            id_card_back_url=user.id_card_back_url,
            psych_neurology_certificate_url=user.psych_neurology_certificate_url,
            narcology_certificate_url=user.narcology_certificate_url,
            pension_contributions_certificate_url=user.pension_contributions_certificate_url,
            auto_class=user.auto_class or []
        ))
    
    return result


@users_router.post("/{user_id}/approve")
async def approve_or_reject_user(
    user_id: int,
    approved: bool,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Одобрение или отклонение пользователя"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    if approved:
        user.role = UserRole.CLIENT
        user.documents_verified = True
        
        # Создаем заявку для одобренного пользователя
        application = Application(
            user_id=user.id,
            status=ApplicationStatus.APPROVED,
            created_at=datetime.utcnow()
        )
        db.add(application)
        
        message = "Пользователь одобрен"
    else:
        user.role = UserRole.REJECTED
        message = "Пользователь отклонен"
    
    db.commit()
    
    return {"message": message}


@users_router.get("/all", response_model=List[UserProfileSchema])
async def get_all_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение всех пользователей"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    users = db.query(User).all()
    
    result = []
    for user in users:
        result.append(UserProfileSchema(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            phone_number=user.phone_number,
            role=user.role.value,
            is_active=user.is_active,
            is_verified_email=user.is_verified_email,
            is_citizen_kz=user.is_citizen_kz,
            documents_verified=user.documents_verified,
            selfie_url=user.selfie_url,
            selfie_with_license_url=user.selfie_with_license_url,
            drivers_license_url=user.drivers_license_url,
            id_card_front_url=user.id_card_front_url,
            id_card_back_url=user.id_card_back_url,
            psych_neurology_certificate_url=user.psych_neurology_certificate_url,
            narcology_certificate_url=user.narcology_certificate_url,
            pension_contributions_certificate_url=user.pension_contributions_certificate_url,
            auto_class=user.auto_class or []
        ))
    
    return result


@users_router.get("/clients", response_model=List[UserProfileSchema])
async def get_all_clients(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение всех клиентов"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    users = db.query(User).filter(User.role == UserRole.CLIENT).all()
    
    result = []
    for user in users:
        result.append(UserProfileSchema(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            phone_number=user.phone_number,
            role=user.role.value,
            is_active=user.is_active,
            is_verified_email=user.is_verified_email,
            is_citizen_kz=user.is_citizen_kz,
            documents_verified=user.documents_verified,
            selfie_url=user.selfie_url,
            selfie_with_license_url=user.selfie_with_license_url,
            drivers_license_url=user.drivers_license_url,
            id_card_front_url=user.id_card_front_url,
            id_card_back_url=user.id_card_back_url,
            psych_neurology_certificate_url=user.psych_neurology_certificate_url,
            narcology_certificate_url=user.narcology_certificate_url,
            pension_contributions_certificate_url=user.pension_contributions_certificate_url,
            auto_class=user.auto_class or []
        ))
    
    return result


@users_router.patch("/{user_id}/role")
async def update_employee_role(
    user_id: int,
    role_data: UserRoleUpdateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Обновление роли сотрудника"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    user.role = role_data.role
    db.commit()
    
    return {"message": f"Роль пользователя изменена на {role_data.role.value}"}


# === User Profile ===
@users_router.get("/{user_id}/profile", response_model=UserProfileSchema)
async def get_user_profile(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> UserProfileSchema:
    """Получить профиль пользователя"""
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
        email=user.email,
        phone_number=user.phone_number,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role.value,
        is_active=user.is_active,
        is_verified_email=user.is_verified_email,
        is_citizen_kz=user.is_citizen_kz,
        documents_verified=user.documents_verified,
        selfie_url=user.selfie_url,
        selfie_with_license_url=user.selfie_with_license_url,
        drivers_license_url=user.drivers_license_url,
        id_card_front_url=user.id_card_front_url,
        id_card_back_url=user.id_card_back_url,
        psych_neurology_certificate_url=user.psych_neurology_certificate_url,
        narcology_certificate_url=user.narcology_certificate_url,
        pension_contributions_certificate_url=user.pension_contributions_certificate_url,
        auto_class=auto_class_list,
    )