from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, exists, select
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.dependencies.database.database import get_db
from app.utils.short_id import uuid_to_sid, safe_sid_to_uuid
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.application_model import Application, ApplicationStatus
from app.models.guarantor_model import Guarantor, GuarantorRequest, GuarantorRequestStatus
from app.push.utils import send_push_to_user_by_id, send_localized_notification_to_user
from app.utils.telegram_logger import log_error_to_telegram
from app.utils.time_utils import get_local_time
from app.websocket.notifications import notify_user_status_update
import asyncio

MvdRouter = APIRouter(prefix="/mvd", tags=["MVD"])


def get_current_mvd_user(current_user: User = Depends(get_current_user)) -> User:
    """Проверяет, что текущий пользователь - сотрудник МВД"""
    if current_user.role != UserRole.MVD:
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права МВД")
    return current_user


@MvdRouter.get("/pending", summary="Получить заявки на рассмотрении")
async def get_pending_applications(
        search: Optional[str] = Query(None, description="Поиск по имени, телефону, ИИН или номеру паспорта"),
        page: int = Query(1, ge=1, description="Номер страницы"),
        per_page: int = Query(10, ge=1, le=100, description="Количество элементов на странице"),
        db: Session = Depends(get_db),
        current_mvd: User = Depends(get_current_mvd_user)
) -> Dict[str, Any]:
    """Получить заявки, одобренные финансистом и ожидающие проверки МВД.
    Также показывает пользователей с REJECTFIRST (отказ по финансу), у которых есть одобренный гарант."""
    
    query = db.query(Application).join(User, Application.user_id == User.id).options(
        joinedload(Application.user)
    ).filter(
        Application.mvd_status == ApplicationStatus.PENDING,
        User.is_verified_email == True,
        or_(
            Application.financier_status == ApplicationStatus.APPROVED,
            and_(
                Application.financier_status == ApplicationStatus.REJECTED,
                User.role == UserRole.REJECTFIRST,
                exists(
                    select(1)
                    .select_from(Guarantor)
                    .join(GuarantorRequest, Guarantor.request_id == GuarantorRequest.id)
                    .where(
                        Guarantor.client_id == User.id,
                        Guarantor.is_active == True,
                        GuarantorRequest.status == GuarantorRequestStatus.ACCEPTED
                    )
                )
            )
        )
    )
    
    if search:
        search_filter = or_(
            User.first_name.ilike(f"%{search}%"),
            User.last_name.ilike(f"%{search}%"),
            User.phone_number.ilike(f"%{search}%"),
            User.iin.ilike(f"%{search}%"),
            User.passport_number.ilike(f"%{search}%")
        )
        query = query.filter(search_filter)
    
    total = query.count()
    applications = query.offset((page - 1) * per_page).limit(per_page).all()
    
    applications_data = []
    for app in applications:
        user = app.user
        
        has_guarantor = db.query(Guarantor).join(
            GuarantorRequest, Guarantor.request_id == GuarantorRequest.id
        ).filter(
            Guarantor.client_id == user.id,
            Guarantor.is_active == True,
            GuarantorRequest.status == GuarantorRequestStatus.ACCEPTED
        ).first() is not None
        
        applications_data.append({
            "application_id": uuid_to_sid(app.id),
            "user_id": uuid_to_sid(user.id),
            "role": user.role.value if user.role else None,
            "financier_status": app.financier_status.value if app.financier_status else None,
            "mvd_status": app.mvd_status.value if app.mvd_status else None,
            "has_active_guarantor": has_guarantor,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "middle_name": user.middle_name,
            "email": user.email,
            "phone_number": user.phone_number,
            "iin": user.iin,
            "passport_number": user.passport_number,
            "birth_date": user.birth_date.isoformat() if user.birth_date else None,
            "id_card_expiry": user.id_card_expiry.isoformat() if user.id_card_expiry else None,
            "drivers_license_expiry": user.drivers_license_expiry.isoformat() if user.drivers_license_expiry else None,
            "is_citizen_kz": user.is_citizen_kz,
            "documents": {
                "id_card_front_url": user.id_card_front_url,
                "id_card_back_url": user.id_card_back_url,
                "drivers_license_url": user.drivers_license_url,
                "selfie_url": user.selfie_url,
                "selfie_with_license_url": user.selfie_with_license_url
            },
            "certificates": {
                "psych_neurology_certificate_url": user.psych_neurology_certificate_url,
                "narcology_certificate_url": user.narcology_certificate_url,
                "pension_contributions_certificate_url": user.pension_contributions_certificate_url,
            },
            "auto_class": app.user.auto_class,
            "financier_approved_at": app.financier_approved_at.isoformat() if app.financier_approved_at else None,
            "created_at": app.created_at.isoformat(),
            "updated_at": app.updated_at.isoformat(),
            "reason": app.reason
        })
    
    return {
        "applications": applications_data,
        "pagination": {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page
        }
    }


@MvdRouter.get("/approved", summary="Получить одобренные заявки")
async def get_approved_applications(
        search: Optional[str] = Query(None, description="Поиск по имени, телефону, ИИН или номеру паспорта"),
        page: int = Query(1, ge=1, description="Номер страницы"),
        per_page: int = Query(10, ge=1, le=100, description="Количество элементов на странице"),
        db: Session = Depends(get_db),
        current_mvd: User = Depends(get_current_mvd_user)
) -> Dict[str, Any]:
    """Получить заявки, одобренные МВД"""
    
    query = db.query(Application).join(User, Application.user_id == User.id).options(
        joinedload(Application.user)
    ).filter(
        and_(
            Application.financier_status == ApplicationStatus.APPROVED,
            Application.mvd_status == ApplicationStatus.APPROVED,
            User.is_verified_email == True
        )
    )
    
    if search:
        search_filter = or_(
            User.first_name.ilike(f"%{search}%"),
            User.last_name.ilike(f"%{search}%"),
            User.phone_number.ilike(f"%{search}%"),
            User.iin.ilike(f"%{search}%"),
            User.passport_number.ilike(f"%{search}%")
        )
        query = query.filter(search_filter)
    
    total = query.count()
    applications = query.offset((page - 1) * per_page).limit(per_page).all()
    
    applications_data = []
    for app in applications:
        user = app.user
        applications_data.append({
            "application_id": uuid_to_sid(app.id),
            "user_id": uuid_to_sid(user.id),
            "first_name": user.first_name,
            "last_name": user.last_name,
            "middle_name": user.middle_name,
            "email": user.email,
            "phone_number": user.phone_number,
            "iin": user.iin,
            "passport_number": user.passport_number,
            "birth_date": user.birth_date.isoformat() if user.birth_date else None,
            "id_card_expiry": user.id_card_expiry.isoformat() if user.id_card_expiry else None,
            "drivers_license_expiry": user.drivers_license_expiry.isoformat() if user.drivers_license_expiry else None,
            "is_citizen_kz": user.is_citizen_kz,
            "documents": {
                "id_card_front_url": user.id_card_front_url,
                "id_card_back_url": user.id_card_back_url,
                "drivers_license_url": user.drivers_license_url,
                "selfie_url": user.selfie_url,
                "selfie_with_license_url": user.selfie_with_license_url
            },
            "certificates": {
                "psych_neurology_certificate_url": user.psych_neurology_certificate_url,
                "narcology_certificate_url": user.narcology_certificate_url,
                "pension_contributions_certificate_url": user.pension_contributions_certificate_url,
            },
            "auto_class": app.user.auto_class,
            "financier_approved_at": app.financier_approved_at.isoformat() if app.financier_approved_at else None,
            "mvd_approved_at": app.mvd_approved_at.isoformat() if app.mvd_approved_at else None,
            "created_at": app.created_at.isoformat(),
            "updated_at": app.updated_at.isoformat(),
            "reason": app.reason
        })
    
    return {
        "applications": applications_data,
        "pagination": {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page
        }
    }


@MvdRouter.get("/rejected", summary="Получить отклоненные заявки")
async def get_rejected_applications(
        search: Optional[str] = Query(None, description="Поиск по имени, телефону, ИИН или номеру паспорта"),
        page: int = Query(1, ge=1, description="Номер страницы"),
        per_page: int = Query(10, ge=1, le=100, description="Количество элементов на странице"),
        db: Session = Depends(get_db),
        current_mvd: User = Depends(get_current_mvd_user)
) -> Dict[str, Any]:
    """Получить заявки, отклоненные МВД.
    Показывает все заявки с mvd_status == REJECTED, независимо от статуса финансиста."""
    
    query = db.query(Application).join(User, Application.user_id == User.id).options(
        joinedload(Application.user)
    ).filter(
        and_(
            Application.mvd_status == ApplicationStatus.REJECTED,
            User.is_verified_email == True
        )
    )
    
    if search:
        search_filter = or_(
            User.first_name.ilike(f"%{search}%"),
            User.last_name.ilike(f"%{search}%"),
            User.phone_number.ilike(f"%{search}%"),
            User.iin.ilike(f"%{search}%"),
            User.passport_number.ilike(f"%{search}%")
        )
        query = query.filter(search_filter)
    
    total = query.count()
    applications = query.offset((page - 1) * per_page).limit(per_page).all()
    
    applications_data = []
    for app in applications:
        user = app.user
        applications_data.append({
            "application_id": uuid_to_sid(app.id),
            "user_id": uuid_to_sid(user.id),
            "role": user.role.value if user.role else None,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "middle_name": user.middle_name,
            "email": user.email,
            "phone_number": user.phone_number,
            "iin": user.iin,
            "passport_number": user.passport_number,
            "birth_date": user.birth_date.isoformat() if user.birth_date else None,
            "id_card_expiry": user.id_card_expiry.isoformat() if user.id_card_expiry else None,
            "drivers_license_expiry": user.drivers_license_expiry.isoformat() if user.drivers_license_expiry else None,
            "is_citizen_kz": user.is_citizen_kz,
            "is_active": user.is_active,
            "documents": {
                "id_card_front_url": user.id_card_front_url,
                "id_card_back_url": user.id_card_back_url,
                "drivers_license_url": user.drivers_license_url,
                "selfie_url": user.selfie_url,
                "selfie_with_license_url": user.selfie_with_license_url
            },
            "certificates": {
                "psych_neurology_certificate_url": user.psych_neurology_certificate_url,
                "narcology_certificate_url": user.narcology_certificate_url,
                "pension_contributions_certificate_url": user.pension_contributions_certificate_url,
            },
            "auto_class": app.user.auto_class,
            "financier_status": app.financier_status.value if app.financier_status else None,
            "mvd_status": app.mvd_status.value if app.mvd_status else None,
            "financier_approved_at": app.financier_approved_at.isoformat() if app.financier_approved_at else None,
            "financier_rejected_at": app.financier_rejected_at.isoformat() if app.financier_rejected_at else None,
            "mvd_rejected_at": app.mvd_rejected_at.isoformat() if app.mvd_rejected_at else None,
            "created_at": app.created_at.isoformat(),
            "updated_at": app.updated_at.isoformat(),
            "reason": app.reason
        })
    
    return {
        "applications": applications_data,
        "pagination": {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page
        }
    }


@MvdRouter.post("/approve/{application_id}", summary="Одобрить заявку")
async def approve_application(
        application_id: str,
        db: Session = Depends(get_db),
        current_mvd: User = Depends(get_current_mvd_user)
) -> Dict[str, Any]:
    """Одобрить заявку в МВД"""
    
    application_uuid = safe_sid_to_uuid(application_id)
    application = db.query(Application).options(
        joinedload(Application.user)
    ).filter(Application.id == application_uuid).first()
    
    if not application:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    if application.mvd_status != ApplicationStatus.PENDING:
        raise HTTPException(status_code=400, detail="Заявка уже обработана")
    
    user = application.user
    is_rejectfirst_with_guarantor = (
        user and 
        user.role == UserRole.REJECTFIRST and
        application.financier_status == ApplicationStatus.REJECTED and
        db.query(Guarantor).join(GuarantorRequest, Guarantor.request_id == GuarantorRequest.id).filter(
            Guarantor.client_id == user.id,
            Guarantor.is_active == True,
            GuarantorRequest.status == GuarantorRequestStatus.ACCEPTED
        ).first() is not None
    )
    
    if application.financier_status == ApplicationStatus.PENDING:
        raise HTTPException(status_code=400, detail="Финансист еще не рассмотрел заявку")
    
    if application.financier_status != ApplicationStatus.APPROVED and not is_rejectfirst_with_guarantor:
        raise HTTPException(status_code=400, detail="Заявка не одобрена финансистом или нет активного гаранта")
    
    application.mvd_status = ApplicationStatus.APPROVED
    application.mvd_approved_at = get_local_time()
    application.mvd_user_id = current_mvd.id
    application.updated_at = get_local_time()

    if user and user.role != UserRole.REJECTFIRST:
        user.role = UserRole.USER
    
    db.commit()
    
    asyncio.create_task(notify_user_status_update(str(user.id)))
    
    try:
        await send_localized_notification_to_user(
            db, 
            application.user.id, 
            "mvd_approve",
            "application_approved_mvd"
        )
    except Exception as e:
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_mvd,
                additional_context={
                    "action": "mvd_approve_notification",
                    "application_id": str(application_uuid),
                    "user_id": str(application.user.id),
                    "mvd_officer_id": str(current_mvd.id)
                }
            )
        except:
            pass
    
    return {
        "message": "Заявка одобрена",
        "application_id": uuid_to_sid(application_uuid),
        "user_id": uuid_to_sid(application.user.id)
    }


@MvdRouter.post("/reject/{application_id}", summary="Отклонить заявку")
async def reject_application(
        application_id: str,
        reason: Optional[str] = Query(None, description="Причина отклонения"),
        db: Session = Depends(get_db),
        current_mvd: User = Depends(get_current_mvd_user)
) -> Dict[str, Any]:
    """Отклонить заявку в МВД"""
    
    application_uuid = safe_sid_to_uuid(application_id)
    application = db.query(Application).options(
        joinedload(Application.user)
    ).filter(Application.id == application_uuid).first()
    
    if not application:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    if application.mvd_status != ApplicationStatus.PENDING:
        raise HTTPException(status_code=400, detail="Заявка уже обработана")
    
    user = application.user
    is_rejectfirst_with_guarantor = (
        user and 
        user.role == UserRole.REJECTFIRST and
        application.financier_status == ApplicationStatus.REJECTED and
        db.query(Guarantor).join(GuarantorRequest, Guarantor.request_id == GuarantorRequest.id).filter(
            Guarantor.client_id == user.id,
            Guarantor.is_active == True,
            GuarantorRequest.status == GuarantorRequestStatus.ACCEPTED
        ).first() is not None
    )
    
    if application.financier_status == ApplicationStatus.PENDING:
        raise HTTPException(status_code=400, detail="Финансист еще не рассмотрел заявку")
    
    if application.financier_status != ApplicationStatus.APPROVED and not is_rejectfirst_with_guarantor:
        raise HTTPException(status_code=400, detail="Заявка не одобрена финансистом или нет активного гаранта")
    
    application.mvd_status = ApplicationStatus.REJECTED
    application.mvd_rejected_at = get_local_time()
    application.mvd_user_id = current_mvd.id
    application.updated_at = get_local_time()
    application.reason = reason

    # При отклонении МВД всегда меняем роль на REJECTSECOND и деактивируем пользователя
    if user:
        user.role = UserRole.REJECTSECOND
        user.is_active = False
        
        from app.guarantor.router import cancel_guarantor_requests_on_rejection
        await cancel_guarantor_requests_on_rejection(str(user.id), db)
    
    db.commit()
    
    if user:
        asyncio.create_task(notify_user_status_update(str(user.id)))
    
    try:
        await send_localized_notification_to_user(
            db, 
            application.user.id, 
            "mvd_reject", 
            "application_rejected_mvd"
        )
    except Exception as e:
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_mvd,
                additional_context={
                    "action": "mvd_reject_notification",
                    "application_id": str(application_uuid),
                    "user_id": str(application.user.id),
                    "mvd_officer_id": str(current_mvd.id),
                    "reason": application.reason
                }
            )
        except:
            pass

    return {
        "message": "Заявка отклонена",
        "application_id": uuid_to_sid(application_uuid),
        "user_id": uuid_to_sid(application.user.id),
        "reason": application.reason
    }
