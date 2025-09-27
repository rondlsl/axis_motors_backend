from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.application_model import Application, ApplicationStatus
from app.push.utils import send_push_to_user_by_id, send_localized_notification_to_user

MvdRouter = APIRouter(prefix="/mvd", tags=["MVD"])


def get_current_mvd_user(current_user: User = Depends(get_current_user)) -> User:
    """Проверяет, что текущий пользователь - сотрудник МВД"""
    if current_user.role != UserRole.MVD:
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права МВД")
    return current_user


@MvdRouter.get("/pending", summary="Получить заявки на рассмотрении")
async def get_pending_applications(
        search: Optional[str] = Query(None, description="Поиск по имени, телефону, ИИН или номеру паспорта"),
        db: Session = Depends(get_db),
        current_mvd: User = Depends(get_current_mvd_user)
) -> Dict[str, Any]:
    """Получить заявки, одобренные финансистом и ожидающие проверки МВД"""
    
    query = db.query(Application).options(
        joinedload(Application.user)
    ).filter(
        and_(
            Application.financier_status == ApplicationStatus.APPROVED,  # Только одобренные финансистом
            Application.mvd_status == ApplicationStatus.PENDING
        )
    )
    
    # Поиск по имени, телефону, ИИН или номеру паспорта
    if search:
        search_filter = or_(
            User.first_name.ilike(f"%{search}%"),
            User.last_name.ilike(f"%{search}%"),
            User.phone_number.ilike(f"%{search}%"),
            User.iin.ilike(f"%{search}%"),
            User.passport_number.ilike(f"%{search}%")
        )
        query = query.filter(search_filter)
    
    applications = query.all()
    
    applications_data = []
    for app in applications:
        user = app.user
        applications_data.append({
            "application_id": app.id,
            "user_id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone_number": user.phone_number,
            "iin": user.iin,
            "passport_number": user.passport_number,
            "birth_date": user.birth_date.isoformat() if user.birth_date else None,
            "id_card_expiry": user.id_card_expiry.isoformat() if user.id_card_expiry else None,
            "drivers_license_expiry": user.drivers_license_expiry.isoformat() if user.drivers_license_expiry else None,
            "documents": {
                "id_card_front_url": user.id_card_front_url,
                "id_card_back_url": user.id_card_back_url,
                "drivers_license_url": user.drivers_license_url,
                "selfie_url": user.selfie_url,
                "selfie_with_license_url": user.selfie_with_license_url
            },
            "auto_class": app.user.auto_class,
            "financier_approved_at": app.financier_approved_at.isoformat() if app.financier_approved_at else None,
            "created_at": app.created_at.isoformat(),
            "updated_at": app.updated_at.isoformat(),
            "reason": app.reason
        })
    
    return {"applications": applications_data}


@MvdRouter.get("/approved", summary="Получить одобренные заявки")
async def get_approved_applications(
        search: Optional[str] = Query(None, description="Поиск по имени, телефону, ИИН или номеру паспорта"),
        db: Session = Depends(get_db),
        current_mvd: User = Depends(get_current_mvd_user)
) -> Dict[str, Any]:
    """Получить заявки, одобренные МВД"""
    
    query = db.query(Application).options(
        joinedload(Application.user)
    ).filter(
        and_(
            Application.financier_status == ApplicationStatus.APPROVED,
            Application.mvd_status == ApplicationStatus.APPROVED
        )
    )
    
    # Поиск по имени, телефону, ИИН или номеру паспорта
    if search:
        search_filter = or_(
            User.first_name.ilike(f"%{search}%"),
            User.last_name.ilike(f"%{search}%"),
            User.phone_number.ilike(f"%{search}%"),
            User.iin.ilike(f"%{search}%"),
            User.passport_number.ilike(f"%{search}%")
        )
        query = query.filter(search_filter)
    
    applications = query.all()
    
    applications_data = []
    for app in applications:
        user = app.user
        applications_data.append({
            "application_id": app.id,
            "user_id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone_number": user.phone_number,
            "iin": user.iin,
            "passport_number": user.passport_number,
            "birth_date": user.birth_date.isoformat() if user.birth_date else None,
            "id_card_expiry": user.id_card_expiry.isoformat() if user.id_card_expiry else None,
            "drivers_license_expiry": user.drivers_license_expiry.isoformat() if user.drivers_license_expiry else None,
            "documents": {
                "id_card_front_url": user.id_card_front_url,
                "id_card_back_url": user.id_card_back_url,
                "drivers_license_url": user.drivers_license_url,
                "selfie_url": user.selfie_url,
                "selfie_with_license_url": user.selfie_with_license_url
            },
            "auto_class": app.user.auto_class,
            "financier_approved_at": app.financier_approved_at.isoformat() if app.financier_approved_at else None,
            "mvd_approved_at": app.mvd_approved_at.isoformat() if app.mvd_approved_at else None,
            "created_at": app.created_at.isoformat(),
            "updated_at": app.updated_at.isoformat(),
            "reason": app.reason
        })
    
    return {"applications": applications_data}


@MvdRouter.get("/rejected", summary="Получить отклоненные заявки")
async def get_rejected_applications(
        search: Optional[str] = Query(None, description="Поиск по имени, телефону, ИИН или номеру паспорта"),
        db: Session = Depends(get_db),
        current_mvd: User = Depends(get_current_mvd_user)
) -> Dict[str, Any]:
    """Получить заявки, отклоненные МВД"""
    
    query = db.query(Application).options(
        joinedload(Application.user)
    ).filter(
        and_(
            Application.financier_status == ApplicationStatus.APPROVED,
            Application.mvd_status == ApplicationStatus.REJECTED
        )
    )
    
    # Поиск по имени, телефону, ИИН или номеру паспорта
    if search:
        search_filter = or_(
            User.first_name.ilike(f"%{search}%"),
            User.last_name.ilike(f"%{search}%"),
            User.phone_number.ilike(f"%{search}%"),
            User.iin.ilike(f"%{search}%"),
            User.passport_number.ilike(f"%{search}%")
        )
        query = query.filter(search_filter)
    
    applications = query.all()
    
    applications_data = []
    for app in applications:
        user = app.user
        applications_data.append({
            "application_id": app.id,
            "user_id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone_number": user.phone_number,
            "iin": user.iin,
            "passport_number": user.passport_number,
            "birth_date": user.birth_date.isoformat() if user.birth_date else None,
            "id_card_expiry": user.id_card_expiry.isoformat() if user.id_card_expiry else None,
            "drivers_license_expiry": user.drivers_license_expiry.isoformat() if user.drivers_license_expiry else None,
            "documents": {
                "id_card_front_url": user.id_card_front_url,
                "id_card_back_url": user.id_card_back_url,
                "drivers_license_url": user.drivers_license_url,
                "selfie_url": user.selfie_url,
                "selfie_with_license_url": user.selfie_with_license_url
            },
            "auto_class": app.user.auto_class,
            "financier_approved_at": app.financier_approved_at.isoformat() if app.financier_approved_at else None,
            "mvd_rejected_at": app.mvd_rejected_at.isoformat() if app.mvd_rejected_at else None,
            "created_at": app.created_at.isoformat(),
            "updated_at": app.updated_at.isoformat(),
            "reason": app.reason
        })
    
    return {"applications": applications_data}


@MvdRouter.post("/approve/{application_id}", summary="Одобрить заявку")
async def approve_application(
        application_id: int,
        db: Session = Depends(get_db),
        current_mvd: User = Depends(get_current_mvd_user)
) -> Dict[str, Any]:
    """Одобрить заявку в МВД"""
    
    application = db.query(Application).options(
        joinedload(Application.user)
    ).filter(Application.id == application_id).first()
    
    if not application:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    if application.mvd_status != ApplicationStatus.PENDING:
        raise HTTPException(status_code=400, detail="Заявка уже обработана")
    
    if application.financier_status != ApplicationStatus.APPROVED:
        raise HTTPException(status_code=400, detail="Заявка не одобрена")
    
    # Обновляем заявку
    application.mvd_status = ApplicationStatus.APPROVED
    application.mvd_approved_at = datetime.utcnow()
    application.mvd_user_id = current_mvd.id
    application.updated_at = datetime.utcnow()

    # Переводим пользователя в полноценного USER
    user = application.user
    if user:
        user.role = UserRole.USER
    
    db.commit()
    
    try:
        await send_localized_notification_to_user(
            db, 
            application.user.id, 
            "mvd_approve", 
            "application_approved_mvd"
        )
    except Exception:
        pass
    
    return {
        "message": "Заявка одобрена",
        "application_id": application_id,
        "user_id": application.user.id
    }


@MvdRouter.post("/reject/{application_id}", summary="Отклонить заявку")
async def reject_application(
        application_id: int,
        reason: Optional[str] = Query(None, description="Причина отклонения"),
        db: Session = Depends(get_db),
        current_mvd: User = Depends(get_current_mvd_user)
) -> Dict[str, Any]:
    """Отклонить заявку в МВД"""
    
    application = db.query(Application).options(
        joinedload(Application.user)
    ).filter(Application.id == application_id).first()
    
    if not application:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    if application.mvd_status != ApplicationStatus.PENDING:
        raise HTTPException(status_code=400, detail="Заявка уже обработана")
    
    if application.financier_status != ApplicationStatus.APPROVED:
        raise HTTPException(status_code=400, detail="Заявка не одобрена")
    
    # Обновляем заявку
    application.mvd_status = ApplicationStatus.REJECTED
    application.mvd_rejected_at = datetime.utcnow()
    application.mvd_user_id = current_mvd.id
    application.updated_at = datetime.utcnow()
    application.reason = reason

    # Блокируем доступ пользователя: роль REJECTSECOND, деактивируем
    user = application.user
    if user:
        user.role = UserRole.REJECTSECOND
        user.is_active = False
    
    db.commit()
    
    # Пуш пользователю
    try:
        await send_localized_notification_to_user(
            db, 
            application.user.id, 
            "mvd_reject", 
            "application_rejected_mvd"
        )
    except Exception:
        pass

    return {
        "message": "Заявка отклонена",
        "application_id": application_id,
        "user_id": application.user.id,
        "reason": application.reason
    }
