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
from app.models.guarantor_model import Guarantor
from app.push.utils import send_push_to_user_by_id, send_localized_notification_to_user
from app.utils.telegram_logger import log_error_to_telegram
from app.utils.time_utils import get_local_time
from app.websocket.notifications import notify_user_status_update
import asyncio

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
        
        # Находим клиентов, за которых этот user является гарантом
        # (user является гарантом для других клиентов)
        guarantor_relations = db.query(Guarantor).options(
            joinedload(Guarantor.client_user)
        ).filter(
            and_(
                Guarantor.guarantor_id == user.id,
                Guarantor.is_active == True
            )
        ).all()
        
        # Формируем данные клиентов, за которых user является гарантом
        clients_data = []
        for relation in guarantor_relations:
            client = relation.client_user
            if client:
                clients_data.append({
                    "sid": uuid_to_sid(client.id),
                    "first_name": client.first_name,
                    "last_name": client.last_name,
                    "middle_name": client.middle_name,
                    "iin": client.iin,
                    "passport_number": client.passport_number,
                    "selfie_url": client.selfie_url
                })
        
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
            "reason": app.reason,
            "guaranteed_clients": clients_data  # Клиенты, за которых этот user является гарантом
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
        
        # Находим гарантов этого клиента
        # (кто является гарантом для этого user)
        guarantor_relations = db.query(Guarantor).options(
            joinedload(Guarantor.guarantor_user)
        ).filter(
            and_(
                Guarantor.client_id == user.id,
                Guarantor.is_active == True
            )
        ).all()
        
        # Формируем данные гарантов клиента
        guarantors_data = []
        for relation in guarantor_relations:
            guarantor = relation.guarantor_user
            if guarantor:
                guarantors_data.append({
                    "sid": uuid_to_sid(guarantor.id),
                    "first_name": guarantor.first_name,
                    "last_name": guarantor.last_name,
                    "middle_name": guarantor.middle_name,
                    "iin": guarantor.iin,
                    "passport_number": guarantor.passport_number,
                    "selfie_url": guarantor.selfie_url
                })
        
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
            "reason": app.reason,
            "guarantors": guarantors_data  # Гаранты этого клиента
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
    application.financier_approved_at = get_local_time()
    application.financier_user_id = current_financier.id
    application.updated_at = get_local_time()
    
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
    db.refresh(user)
    db.refresh(application)
    
    try:
        await send_localized_notification_to_user(
            db, 
            user.id, 
            "financier_approve", 
            "application_approved_financier",
            auto_class=auto_class
        )
    except Exception as e:
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_financier,
                additional_context={
                    "action": "financier_approve_notification",
                    "application_id": str(application_uuid),
                    "user_id": str(user.id),
                    "financier_id": str(current_financier.id),
                    "auto_class": auto_class
                }
            )
        except:
            pass
    
    db.expire_all()
    db.refresh(user)
    db.refresh(application)
    await asyncio.sleep(0.05)
    
    asyncio.create_task(notify_user_status_update(str(user.id)))
    
    for relation in guarantor_relations:
        if relation.guarantor_id:
            asyncio.create_task(notify_user_status_update(str(relation.guarantor_id)))
    for relation in client_relations:
        if relation.client_id:
            asyncio.create_task(notify_user_status_update(str(relation.client_id)))
    
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
    application.financier_rejected_at = get_local_time()
    application.financier_user_id = current_financier.id
    application.updated_at = get_local_time()
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
    
    user_ids_to_notify = {str(user.id)}
    for relation in guarantor_relations:
        if relation.guarantor_id:
            user_ids_to_notify.add(str(relation.guarantor_id))
    
    for user_id in user_ids_to_notify:
        asyncio.create_task(notify_user_status_update(user_id))

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
        
        # Дополнительное уведомление о том, что проверка не пройдена
        if user.fcm_token:
            asyncio.create_task(
                send_localized_notification_to_user(
                    db,
                    user.id,
                    "verification_failed",
                    "verification_failed"
                )
        )
    except Exception as e:
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_financier,
                additional_context={
                    "action": "financier_reject_notification",
                    "application_id": str(application_uuid),
                    "user_id": str(application.user.id),
                    "financier_id": str(current_financier.id),
                    "reason_type": reason_type,
                    "reason": application.reason
                }
            )
        except:
            pass
    
    return {
        "message": "Заявка отклонена",
        "application_id": uuid_to_sid(application_uuid),
        "user_id": uuid_to_sid(user.id),
        "reason": application.reason,
        "reason_type": reason_type
    }


@FinancierRouter.post("/recheck/{application_id}", summary="Запросить повторную проверку документов")
async def request_documents_recheck(
        application_id: str,
        db: Session = Depends(get_db),
        current_financier: User = Depends(get_current_financier)
) -> Dict[str, Any]:
    """Запросить повторную проверку документов пользователя.
    
    Переводит заявку в статус PENDINGTOFIRST и снимает одобрение МВД.
    Пользователь должен будет заново загрузить документы."""
    
    application_uuid = safe_sid_to_uuid(application_id)
    application = db.query(Application).options(
        joinedload(Application.user)
    ).filter(Application.id == application_uuid).first()
    
    if not application:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    user = application.user
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Меняем роль пользователя на PENDINGTOFIRST (как при первой загрузке документов)
    user.role = UserRole.PENDINGTOFIRST
    
    # Сбрасываем статусы в applications на PENDING
    application.financier_status = ApplicationStatus.PENDING
    application.mvd_status = ApplicationStatus.PENDING
    
    # Очищаем даты и IDs одобрения/отклонения МВД (снимаем одобрение МВД)
    application.mvd_approved_at = None
    application.mvd_rejected_at = None
    application.mvd_user_id = None
    
    # Очищаем даты и IDs одобрения/отклонения финансиста (чтобы финансист мог снова проверить)
    application.financier_approved_at = None
    application.financier_rejected_at = None
    application.financier_user_id = None
    
    # Очищаем причину отклонения
    application.reason = None
    
    # Очищаем auto_class, чтобы финансист мог заново установить его при одобрении
    user.auto_class = None
    
    # Если у пользователя есть гарант, нужно пересчитать его auto_class
    # (убрать классы, которые были получены только от этого клиента)
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
                if client and client.auto_class and client.role not in [UserRole.REJECTFIRST, UserRole.REJECTSECOND, UserRole.PENDINGTOFIRST]:
                    all_client_classes.extend(client.auto_class)
            
            # Убираем дубликаты и обновляем классы гаранта
            guarantor_user.auto_class = list(set(all_client_classes)) if all_client_classes else None
    
    # Обновляем updated_at
    application.updated_at = get_local_time()
    
    db.commit()
    
    user_ids_to_notify = {str(user.id)}
    for relation in guarantor_relations:
        if relation.guarantor_id:
            user_ids_to_notify.add(str(relation.guarantor_id))
    
    for user_id in user_ids_to_notify:
        asyncio.create_task(notify_user_status_update(user_id))
    
    try:
        await send_localized_notification_to_user(
            db,
            user.id,
            "financier_request_recheck",
            "documents_recheck_required"
        )
    except Exception as e:
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_financier,
                additional_context={
                    "action": "financier_request_recheck_notification",
                    "application_id": str(application_uuid),
                    "user_id": str(user.id),
                    "financier_id": str(current_financier.id)
                }
            )
        except:
            pass
    
    return {
        "message": "Запрошена повторная проверка документов",
        "application_id": uuid_to_sid(application_uuid),
        "user_id": uuid_to_sid(user.id),
        "user_role": user.role.value,
        "financier_status": application.financier_status.value,
        "mvd_status": application.mvd_status.value
    }
