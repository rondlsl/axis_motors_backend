from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.dependencies.database.database import get_db
from app.utils.short_id import uuid_to_sid, safe_sid_to_uuid
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.application_model import Application, ApplicationStatus
from app.push.utils import send_push_to_user_by_id, send_localized_notification_to_user

FinancierRouter = APIRouter(prefix="/financier", tags=["Financier"])


def get_current_financier(current_user: User = Depends(get_current_user)) -> User:
    """Проверяет, что текущий пользователь - финансист"""
    if current_user.role != UserRole.FINANCIER:
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права финансиста")
    return current_user


@FinancierRouter.get("/pending", summary="Получить заявки на рассмотрении")
async def get_pending_applications(
        search: Optional[str] = Query(None, description="Поиск по имени, телефону, ИИН или номеру паспорта"),
        page: int = Query(1, ge=1, description="Номер страницы"),
        per_page: int = Query(10, ge=1, le=100, description="Количество элементов на странице"),
        db: Session = Depends(get_db),
        current_financier: User = Depends(get_current_financier)
) -> Dict[str, Any]:
    """Получить заявки, ожидающие проверки финансистом"""
    
    query = db.query(Application).options(
        joinedload(Application.user)
    ).join(User, Application.user_id == User.id).filter(
        and_(
            Application.financier_status == ApplicationStatus.PENDING,
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
            "email": user.email,
            "phone_number": user.phone_number,
            "iin": user.iin,
            "passport_number": user.passport_number,
            "birth_date": user.birth_date.isoformat() if user.birth_date else None,
            "id_card_expiry": user.id_card_expiry.isoformat() if user.id_card_expiry else None,
            "drivers_license_expiry": user.drivers_license_expiry.isoformat() if user.drivers_license_expiry else None,
            "is_citizen_kz": user.is_citizen_kz,
            "is_verified_email": user.is_verified_email,
            "certificates": {
                "psych_neurology_certificate_url": user.psych_neurology_certificate_url,
                "narcology_certificate_url": user.narcology_certificate_url,
                "pension_contributions_certificate_url": user.pension_contributions_certificate_url,
            },
            "documents": {
                "id_card_front_url": user.id_card_front_url,
                "id_card_back_url": user.id_card_back_url,
                "drivers_license_url": user.drivers_license_url,
                "selfie_url": user.selfie_url,
                "selfie_with_license_url": user.selfie_with_license_url
            },
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


@FinancierRouter.get("/approved", summary="Получить одобренные заявки")
async def get_approved_applications(
        search: Optional[str] = Query(None, description="Поиск по имени, телефону, ИИН или номеру паспорта"),
        page: int = Query(1, ge=1, description="Номер страницы"),
        per_page: int = Query(10, ge=1, le=100, description="Количество элементов на странице"),
        db: Session = Depends(get_db),
        current_financier: User = Depends(get_current_financier)
) -> Dict[str, Any]:
    """Получить заявки, одобренные финансистом"""
    
    query = db.query(Application).options(
        joinedload(Application.user)
    ).join(User, Application.user_id == User.id).filter(
        and_(
            Application.financier_status == ApplicationStatus.APPROVED,
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
            "email": user.email,
            "phone_number": user.phone_number,
            "iin": user.iin,
            "passport_number": user.passport_number,
            "birth_date": user.birth_date.isoformat() if user.birth_date else None,
            "id_card_expiry": user.id_card_expiry.isoformat() if user.id_card_expiry else None,
            "drivers_license_expiry": user.drivers_license_expiry.isoformat() if user.drivers_license_expiry else None,
            "is_citizen_kz": user.is_citizen_kz,
            "is_verified_email": user.is_verified_email,
            "certificates": {
                "psych_neurology_certificate_url": user.psych_neurology_certificate_url,
                "narcology_certificate_url": user.narcology_certificate_url,
                "pension_contributions_certificate_url": user.pension_contributions_certificate_url,
            },
            "documents": {
                "id_card_front_url": user.id_card_front_url,
                "id_card_back_url": user.id_card_back_url,
                "drivers_license_url": user.drivers_license_url,
                "selfie_url": user.selfie_url,
                "selfie_with_license_url": user.selfie_with_license_url
            },
            "auto_class": app.user.auto_class,
            "approved_at": app.financier_approved_at.isoformat() if app.financier_approved_at else None,
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


@FinancierRouter.get("/rejected", summary="Получить отклоненные заявки")
async def get_rejected_applications(
        search: Optional[str] = Query(None, description="Поиск по имени, телефону, ИИН или номеру паспорта"),
        page: int = Query(1, ge=1, description="Номер страницы"),
        per_page: int = Query(10, ge=1, le=100, description="Количество элементов на странице"),
        db: Session = Depends(get_db),
        current_financier: User = Depends(get_current_financier)
) -> Dict[str, Any]:
    """Получить заявки, отклоненные финансистом"""
    
    query = db.query(Application).options(
        joinedload(Application.user)
    ).join(User, Application.user_id == User.id).filter(
        and_(
            Application.financier_status == ApplicationStatus.REJECTED,
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
            "email": user.email,
            "phone_number": user.phone_number,
            "iin": user.iin,
            "passport_number": user.passport_number,
            "birth_date": user.birth_date.isoformat() if user.birth_date else None,
            "id_card_expiry": user.id_card_expiry.isoformat() if user.id_card_expiry else None,
            "drivers_license_expiry": user.drivers_license_expiry.isoformat() if user.drivers_license_expiry else None,
            "is_citizen_kz": user.is_citizen_kz,
            "is_verified_email": user.is_verified_email,
            "certificates": {
                "psych_neurology_certificate_url": user.psych_neurology_certificate_url,
                "narcology_certificate_url": user.narcology_certificate_url,
                "pension_contributions_certificate_url": user.pension_contributions_certificate_url,
            },
            "documents": {
                "id_card_front_url": user.id_card_front_url,
                "id_card_back_url": user.id_card_back_url,
                "drivers_license_url": user.drivers_license_url,
                "selfie_url": user.selfie_url,
                "selfie_with_license_url": user.selfie_with_license_url
            },
            "rejected_at": app.financier_rejected_at.isoformat() if app.financier_rejected_at else None,
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


@FinancierRouter.post("/approve/{application_id}", summary="Одобрить заявку")
async def approve_application(
        application_id: str,
        auto_class: str = Query(..., description="Класс доступа: A или комбинации (например, A, B)"),
        db: Session = Depends(get_db),
        current_financier: User = Depends(get_current_financier)
) -> Dict[str, Any]:
    """Одобрить заявку и установить класс доступа к автомобилям"""
    
    application_uuid = safe_sid_to_uuid(application_id)
    application = db.query(Application).options(
        joinedload(Application.user)
    ).filter(Application.id == application_uuid).first()
    
    if not application:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    if application.financier_status != ApplicationStatus.PENDING:
        raise HTTPException(status_code=400, detail="Заявка уже обработана")
    
    # Обновляем заявку
    application.financier_status = ApplicationStatus.APPROVED
    application.financier_approved_at = datetime.utcnow()
    application.financier_user_id = current_financier.id
    application.updated_at = datetime.utcnow()
    
    # Обновляем пользователя
    user = application.user
    raw_auto_class = auto_class.strip()
    if raw_auto_class.startswith("{") and raw_auto_class.endswith("}"):
        raw_auto_class = raw_auto_class[1:-1]
    raw_auto_class = raw_auto_class.replace('"', '').replace("'", "")
    auto_classes = [cls.strip() for cls in raw_auto_class.split(",") if cls.strip()]
    user.auto_class = auto_classes  # Сохраняем как массив строк в users.auto_class
    # После одобрения финансистом – ждём МВД
    user.role = UserRole.PENDINGTOSECOND
    
    # Если у пользователя есть гарант, обновляем его auto_class тоже
    from app.models.guarantor_model import Guarantor
    guarantor_relations = db.query(Guarantor).filter(
        Guarantor.client_id == user.id
    ).all()
    
    for relation in guarantor_relations:
        guarantor_user = db.query(User).filter(User.id == relation.guarantor_id).first()
        if guarantor_user:
            # Добавляем классы к существующим классам гаранта
            existing_classes = guarantor_user.auto_class or []
            for cls in auto_classes:
                if cls not in existing_classes:
                    existing_classes.append(cls)
            guarantor_user.auto_class = existing_classes
    
    # Если пользователь является гарантом, обновляем auto_class всех его клиентов
    client_relations = db.query(Guarantor).filter(
        Guarantor.guarantor_id == user.id
    ).all()
    
    for relation in client_relations:
        client_user = db.query(User).filter(User.id == relation.client_id).first()
        if client_user:
            # Добавляем классы к существующим классам клиента
            existing_classes = client_user.auto_class or []
            for cls in auto_classes:
                if cls not in existing_classes:
                    existing_classes.append(cls)
            client_user.auto_class = existing_classes
    
    db.commit()
    
    try:
        await send_localized_notification_to_user(
            db, 
            application.user.id, 
            "financier_approve", 
            "application_approved_financier",
            auto_class=auto_class
        )
    except Exception:
        pass
    
    return {
        "message": "Заявка одобрена",
        "application_id": uuid_to_sid(application_uuid),
        "auto_class": auto_class,
        "user_id": uuid_to_sid(user.id)
    }


@FinancierRouter.post("/reject/{application_id}", summary="Отклонить заявку")
async def reject_application(
        application_id: str,
        reason: Optional[str] = Query(None, description="Причина отклонения"),
        reason_type: Optional[str] = Query(
            None,
            description="Тип причины: 'financial', 'documents' или 'certificates'",
        ),
        db: Session = Depends(get_db),
        current_financier: User = Depends(get_current_financier)
) -> Dict[str, Any]:
    """Отклонить заявку"""
    
    application_uuid = safe_sid_to_uuid(application_id)
    application = db.query(Application).filter(Application.id == application_uuid).first()
    
    if not application:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    if application.financier_status != ApplicationStatus.PENDING:
        raise HTTPException(status_code=400, detail="Заявка уже обработана")
    
    # Обновляем заявку
    application.financier_status = ApplicationStatus.REJECTED
    application.financier_rejected_at = datetime.utcnow()
    application.financier_user_id = current_financier.id
    application.updated_at = datetime.utcnow()
    application.reason = reason
    
    # Обновляем пользователя
    user = application.user
    user.auto_class = None  # Убираем класс доступа из users.auto_class
    # Выставляем подробную роль-отказ в зависимости от типа
    if reason_type == "documents":
        user.role = UserRole.REJECTFIRSTDOC
    elif reason_type == "certificates":
        user.role = UserRole.REJECTFIRSTCERT
    else:
        user.role = UserRole.REJECTFIRST
    
    # Если у пользователя есть гарант, нужно пересчитать его auto_class
    # (убрать классы, которые были получены только от этого клиента)
    from app.models.guarantor_model import Guarantor
    guarantor_relations = db.query(Guarantor).filter(
        Guarantor.client_id == user.id
    ).all()
    
    for relation in guarantor_relations:
        guarantor_user = db.query(User).filter(User.id == relation.guarantor_id).first()
        if guarantor_user and guarantor_user.auto_class:
            # Пересчитываем классы гаранта на основе оставшихся клиентов
            client_relations = db.query(Guarantor).filter(
                Guarantor.guarantor_id == guarantor_user.id
            ).all()
            
            all_client_classes = []
            for client_rel in client_relations:
                client = db.query(User).filter(User.id == client_rel.client_id).first()
                if client and client.auto_class and client.role != UserRole.REJECTED:
                    all_client_classes.extend(client.auto_class)
            
            # Убираем дубликаты и обновляем классы гаранта
            guarantor_user.auto_class = list(set(all_client_classes)) if all_client_classes else None
    
    # Если пользователь был гарантом, отменяем все его заявки
    from app.guarantor.router import cancel_guarantor_requests_on_rejection
    await cancel_guarantor_requests_on_rejection(str(user.id), db)
    
    db.commit()

    # Уведомление пользователю
    try:
        if reason_type == "documents":
            translation_key = "financier_reject_documents"
        elif reason_type == "certificates":
            translation_key = "financier_reject_certificates"
        else:
            translation_key = "financier_reject_financial"
        
        await send_localized_notification_to_user(
            db, 
            application.user.id, 
            translation_key, 
            "application_rejected_financier"
        )
    except Exception:
        pass
    
    return {
        "message": "Заявка отклонена",
        "application_id": uuid_to_sid(application_uuid),
        "user_id": uuid_to_sid(user.id),
        "reason": application.reason,
        "reason_type": reason_type
    }
