from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.models.application_model import Application, ApplicationStatus
from app.push.utils import send_push_to_user_by_id

FinancierRouter = APIRouter(prefix="/financier", tags=["Financier"])


def get_current_financier(current_user: User = Depends(get_current_user)) -> User:
    """Проверяет, что текущий пользователь - финансист"""
    if current_user.role != UserRole.FINANCIER:
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права финансиста")
    return current_user


@FinancierRouter.get("/pending", summary="Получить заявки на рассмотрении")
async def get_pending_applications(
        search: Optional[str] = Query(None, description="Поиск по имени, телефону, ИИН или номеру паспорта"),
        db: Session = Depends(get_db),
        current_financier: User = Depends(get_current_financier)
) -> Dict[str, Any]:
    """Получить заявки, ожидающие проверки финансистом"""
    
    query = db.query(Application).options(
        joinedload(Application.user)
    ).filter(
        Application.financier_status == ApplicationStatus.PENDING
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
            "created_at": app.created_at.isoformat(),
            "updated_at": app.updated_at.isoformat(),
            "reason": app.reason
        })
    
    return {"applications": applications_data}


@FinancierRouter.get("/approved", summary="Получить одобренные заявки")
async def get_approved_applications(
        search: Optional[str] = Query(None, description="Поиск по имени, телефону, ИИН или номеру паспорта"),
        db: Session = Depends(get_db),
        current_financier: User = Depends(get_current_financier)
) -> Dict[str, Any]:
    """Получить заявки, одобренные финансистом"""
    
    query = db.query(Application).options(
        joinedload(Application.user)
    ).filter(
        Application.financier_status == ApplicationStatus.APPROVED
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
            "approved_at": app.financier_approved_at.isoformat() if app.financier_approved_at else None,
            "created_at": app.created_at.isoformat(),
            "updated_at": app.updated_at.isoformat(),
            "reason": app.reason
        })
    
    return {"applications": applications_data}


@FinancierRouter.get("/rejected", summary="Получить отклоненные заявки")
async def get_rejected_applications(
        search: Optional[str] = Query(None, description="Поиск по имени, телефону, ИИН или номеру паспорта"),
        db: Session = Depends(get_db),
        current_financier: User = Depends(get_current_financier)
) -> Dict[str, Any]:
    """Получить заявки, отклоненные финансистом"""
    
    query = db.query(Application).options(
        joinedload(Application.user)
    ).filter(
        Application.financier_status == ApplicationStatus.REJECTED
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
            "rejected_at": app.financier_rejected_at.isoformat() if app.financier_rejected_at else None,
            "created_at": app.created_at.isoformat(),
            "updated_at": app.updated_at.isoformat(),
            "reason": app.reason
        })
    
    return {"applications": applications_data}


@FinancierRouter.post("/approve/{application_id}", summary="Одобрить заявку")
async def approve_application(
        application_id: int,
        auto_class: str = Query(..., description="Класс доступа: A или комбинации (например, A, B)"),
        db: Session = Depends(get_db),
        current_financier: User = Depends(get_current_financier)
) -> Dict[str, Any]:
    """Одобрить заявку и установить класс доступа к автомобилям"""
    
    application = db.query(Application).options(
        joinedload(Application.user)
    ).filter(Application.id == application_id).first()
    
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
    user.auto_class = [auto_class]  # Сохраняем как массив строк в users.auto_class
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
            # Добавляем класс к существующим классам гаранта
            existing_classes = guarantor_user.auto_class or []
            if auto_class not in existing_classes:
                guarantor_user.auto_class = existing_classes + [auto_class]
    
    # Если пользователь является гарантом, обновляем auto_class всех его клиентов
    client_relations = db.query(Guarantor).filter(
        Guarantor.guarantor_id == user.id
    ).all()
    
    for relation in client_relations:
        client_user = db.query(User).filter(User.id == relation.client_id).first()
        if client_user:
            # Добавляем класс к существующим классам клиента
            existing_classes = client_user.auto_class or []
            if auto_class not in existing_classes:
                client_user.auto_class = existing_classes + [auto_class]
    
    db.commit()
    
    try:
        title = "Заявка одобрена финансистом"
        body = f"Ваша заявка одобрена. Класс доступа: {auto_class}. Ожидайте проверки МВД."
        await send_push_to_user_by_id(db, application.user.id, title, body, "application_approved_financier")
    except Exception:
        pass
    
    return {
        "message": "Заявка одобрена",
        "application_id": application_id,
        "auto_class": auto_class,
        "user_id": user.id
    }


@FinancierRouter.post("/reject/{application_id}", summary="Отклонить заявку")
async def reject_application(
        application_id: int,
        reason: Optional[str] = Query(None, description="Причина отклонения"),
        reason_type: Optional[str] = Query(
            None,
            description="Тип причины: 'financial' или 'documents'",
        ),
        db: Session = Depends(get_db),
        current_financier: User = Depends(get_current_financier)
) -> Dict[str, Any]:
    """Отклонить заявку"""
    
    application = db.query(Application).filter(Application.id == application_id).first()
    
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
    
    db.commit()

    # Уведомление пользователю
    try:
        title = "Заявка отклонена финансистом"
        # Сообщение в зависимости от типа причины
        if reason_type == "documents":
            body = (f"Причина: {reason}. Пожалуйста, загрузите документы заново." if reason 
                    else "Заявка отклонена: некорректные документы. Загрузите документы заново.")
        else:
            body = f"Причина: {reason}" if reason else "Заявка отклонена финансистом"
        await send_push_to_user_by_id(db, application.user.id, title, body, "application_rejected_financier")
    except Exception:
        pass
    
    return {
        "message": "Заявка отклонена",
        "application_id": application_id,
        "user_id": user.id,
        "reason": application.reason,
        "reason_type": reason_type
    }
