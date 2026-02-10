"""Support users — список, бронирование, отмена аренды, загрузка фото (тот же контракт, что /admin/users)."""
import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Form, File, UploadFile
from sqlalchemy.orm import Session

from app.dependencies.database.database import get_db
from app.auth.dependencies.save_documents import save_file, validate_photos
from app.utils.atomic_operations import delete_uploaded_files
from app.admin.users.router import (
    get_users_list_impl,
    submit_rental_review_impl,
    get_user_card_data,
)
from app.admin.users.schemas import (
    UserPaginatedResponse,
    UserCardSchema,
    UserCommentUpdateSchema,
    SendUserSmsRequest,
    SendUserSmsResponse,
    SendUserEmailRequest,
    SendUserEmailResponse,
    SendUserNotificationRequest,
    SendUserNotificationResponse,
    AdminCancelReservationRequest,
    AdminCancelReservationResponse,
    AdminRentalReviewRequest,
    AdminRentalReviewResponse,
    AdminAssignMechanicRequest,
    AssignMechanicResponse,
    MechanicStartInspectionResponse,
    MechanicPhotoUploadResponse,
    MechanicCompleteInspectionResponse,
    AdminMechanicCompleteRequest,
    WalletTransactionSchema,
    WalletTransactionPaginationSchema,
    GroupedTransactionItemSchema,
    GroupedTransactionsPaginationSchema,
)
from app.support.deps import require_support_role
from app.utils.short_id import safe_sid_to_uuid, uuid_to_sid
from app.utils.sid_converter import convert_uuid_response_to_sid
from app.utils.action_logger import log_action
from app.utils.telegram_logger import log_error_to_telegram
from app.core.config import SMS_TOKEN
from app.guarantor.sms_utils import send_sms_mobizon
from email.mime.text import MIMEText
from app.core.smtp import send_email_with_fallback
from app.push.utils import send_push_to_user_by_id
from app.models.user_model import User, UserRole
from app.push.utils import user_has_push_tokens, send_localized_notification_to_user_async
from app.models.history_model import RentalHistory, RentalStatus, RentalType, RentalReview
from app.models.car_model import Car, CarStatus
from app.rent.utils.calculate_price import get_open_price, calc_required_balance
from app.utils.time_utils import get_local_time
from app.websocket.notifications import notify_user_status_update

logger = logging.getLogger(__name__)
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
    has_guarantor: Optional[bool] = Query(None, description="Фильтр «гарант»: пользователи, у которых есть гарант"),
    is_guarantor_for: Optional[bool] = Query(None, description="Фильтр «с гарантом»: пользователи, которые являются гарантом"),
    sort_by: Optional[str] = Query(None, description="Сортировка по балансу: wallet_asc, wallet_desc"),
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
        has_guarantor=has_guarantor,
        is_guarantor_for=is_guarantor_for,
        sort_by=sort_by,
        page=page,
        limit=limit,
    )


@users_router.get("/{user_id}/card", response_model=UserCardSchema)
async def get_support_user_card(
    user_id: str,
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """Получение полной карточки пользователя (support)."""
    user_uuid = safe_sid_to_uuid(user_id)
    user_data = get_user_card_data(db, user_uuid)
    if not user_data:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    converted_data = convert_uuid_response_to_sid(user_data, ["id"])
    return UserCardSchema(**converted_data)


@users_router.patch("/{user_id}/comment")
async def support_update_user_comment(
    user_id: str,
    comment_data: UserCommentUpdateSchema,
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """Обновление комментария пользователя (support). Действие логируется."""
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.admin_comment = comment_data.admin_comment
    log_action(
        db,
        actor_id=current_user.id,
        action="update_user_comment",
        entity_type="user",
        entity_id=user.id,
        details={"comment": comment_data.admin_comment, "actor_role": "support"},
    )
    db.commit()
    return {"message": "Комментарий обновлен", "admin_comment": comment_data.admin_comment}


@users_router.post("/{user_id}/send-sms", response_model=SendUserSmsResponse)
async def support_send_sms_to_user(
    user_id: str,
    request: SendUserSmsRequest,
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """Отправка SMS пользователю (support). Действие логируется."""
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if not user.phone_number:
        raise HTTPException(status_code=400, detail="У пользователя не указан номер телефона")
    phone_number = user.phone_number.strip()
    message_text = request.message.strip()
    if SMS_TOKEN == "1010":
        log_action(
            db,
            actor_id=current_user.id,
            action="send_sms_to_user",
            entity_type="user",
            entity_id=user.id,
            details={"phone_number": phone_number, "message": message_text, "test_mode": True, "actor_role": "support"},
        )
        db.commit()
        return SendUserSmsResponse(
            success=True,
            message="SMS отправлено (тестовый режим)",
            user_id=user_id,
            phone_number=phone_number,
            result="Test mode - SMS not actually sent",
        )
    try:
        result = await send_sms_mobizon(phone_number, message_text, SMS_TOKEN)
        log_action(
            db,
            actor_id=current_user.id,
            action="send_sms_to_user",
            entity_type="user",
            entity_id=user.id,
            details={"phone_number": phone_number, "message": message_text, "result": result, "actor_role": "support"},
        )
        db.commit()
        return SendUserSmsResponse(
            success=True,
            message="SMS успешно отправлено",
            user_id=user_id,
            phone_number=phone_number,
            result=result,
        )
    except Exception as e:
        logger.error("Support SMS error: user_id=%s, phone=%s, error=%s", user_id, phone_number, e, exc_info=True)
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "support_send_sms_to_user",
                    "user_id": user_id,
                    "phone_number": phone_number,
                },
            )
        except Exception:
            pass
        return SendUserSmsResponse(
            success=False,
            message="Ошибка при отправке SMS",
            user_id=user_id,
            phone_number=phone_number,
            error=str(e),
        )


@users_router.post("/{user_id}/send-email", response_model=SendUserEmailResponse)
async def support_send_email_to_user(
    user_id: str,
    request: SendUserEmailRequest,
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """Отправка email пользователю (support). Действие логируется."""
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if not user.email:
        raise HTTPException(status_code=400, detail="У пользователя не указан email")
    email = user.email.strip().lower()
    subject = request.subject.strip()
    body = request.body.strip()
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["To"] = email
        if send_email_with_fallback(msg, email):
            log_action(
                db,
                actor_id=current_user.id,
                action="send_email_to_user",
                entity_type="user",
                entity_id=user.id,
                details={"email": email, "subject": subject, "actor_role": "support"},
            )
            db.commit()
            return SendUserEmailResponse(
                success=True,
                message="Email успешно отправлен",
                user_id=user_id,
                email=email,
            )
        return SendUserEmailResponse(
            success=False,
            message="SMTP не настроен",
            user_id=user_id,
            email=email,
            error="SMTP configuration missing",
        )
    except Exception as e:
        logger.error("Support send email error: %s", e)
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "support_send_email_to_user",
                    "user_id": user_id,
                    "email": email,
                },
            )
        except Exception:
            pass
        return SendUserEmailResponse(
            success=False,
            message="Ошибка при отправке email",
            user_id=user_id,
            email=email,
            error=str(e),
        )


@users_router.post("/{user_id}/send-notification", response_model=SendUserNotificationResponse)
async def support_send_notification_to_user(
    user_id: str,
    request: SendUserNotificationRequest,
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """Отправка push-уведомления пользователю (support). Действие логируется."""
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    title = request.title.strip()
    body = request.body.strip()
    try:
        push_sent = await send_push_to_user_by_id(
            db_session=db,
            user_id=user.id,
            title=title,
            body=body,
        )
        log_action(
            db,
            actor_id=current_user.id,
            action="send_notification_to_user",
            entity_type="user",
            entity_id=user.id,
            details={"title": title, "body": body, "push_sent": push_sent, "actor_role": "support"},
        )
        db.commit()
        return SendUserNotificationResponse(
            success=True,
            message="Уведомление успешно отправлено",
            user_id=user_id,
            push_sent=push_sent,
        )
    except Exception as e:
        db.rollback()
        logger.error("Support send notification error: %s", e)
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=current_user,
                additional_context={
                    "action": "support_send_notification_to_user",
                    "user_id": user_id,
                },
            )
        except Exception:
            pass
        return SendUserNotificationResponse(
            success=False,
            message="Ошибка при отправке уведомления",
            user_id=user_id,
            push_sent=False,
            error=str(e),
        )


@users_router.post("/trips/reserve", summary="Забронировать машину за клиента (Support)")
async def support_reserve_car(
    car_id: str = Form(..., description="ID машины"),
    user_id: str = Form(..., description="ID пользователя"),
    rental_type: str = Form(..., description="Тип аренды: MINUTES, HOURS, DAYS"),
    duration: Optional[str] = Form(None, description="Длительность (для HOURS/DAYS)"),
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """
    Эндпоинт для support для бронирования машины за клиента.
    Точная копия POST /admin/users/trips/reserve.

    - Создает аренду со статусом RESERVED
    - Проверяет минимальный баланс клиента
    - Обновляет статус машины на RESERVED
    """
    parsed_duration = None
    if duration and duration.strip():
        try:
            parsed_duration = int(duration.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Duration должен быть целым числом")

    rental_type_map = {
        "MINUTES": RentalType.MINUTES,
        "HOURS": RentalType.HOURS,
        "DAYS": RentalType.DAYS
    }
    rental_type_enum = rental_type_map.get(rental_type.upper())
    if not rental_type_enum:
        raise HTTPException(status_code=400, detail="Неверный тип аренды. Допустимые: MINUTES, HOURS, DAYS")

    if rental_type_enum in [RentalType.HOURS, RentalType.DAYS] and not parsed_duration:
        raise HTTPException(status_code=400, detail="Duration обязателен для аренды по часам/дням")

    target_user_uuid = safe_sid_to_uuid(user_id)
    target_user = db.query(User).filter(User.id == target_user_uuid).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    car_uuid = safe_sid_to_uuid(car_id)
    car = db.query(Car).filter(Car.id == car_uuid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    if car.status not in [CarStatus.FREE, CarStatus.PENDING]:
        raise HTTPException(status_code=400, detail=f"Машина недоступна для бронирования. Текущий статус: {car.status.value}")

    active_rental = db.query(RentalHistory).filter(
        RentalHistory.user_id == target_user_uuid,
        RentalHistory.rental_status.in_([RentalStatus.RESERVED, RentalStatus.IN_USE])
    ).first()

    if active_rental:
        if active_rental.rental_status == RentalStatus.IN_USE:
            raise HTTPException(status_code=400, detail="У пользователя уже есть активная аренда")
        if active_rental.rental_status == RentalStatus.RESERVED:
            raise HTTPException(status_code=400, detail="У пользователя уже есть активное бронирование")

    is_owner = (car.owner_id == target_user_uuid)
    required_balance = calc_required_balance(
        rental_type=rental_type_enum,
        duration=parsed_duration,
        car=car,
        include_delivery=False,
        is_owner=is_owner,
        with_driver=False
    )

    if target_user.wallet_balance < required_balance:
        formatted_required = f"{required_balance:,}".replace(",", " ")
        formatted_balance = f"{int(target_user.wallet_balance):,}".replace(",", " ")
        raise HTTPException(
            status_code=402,
            detail=f"Недостаточно средств на балансе клиента. Требуется минимум: {formatted_required} ₸, доступно: {formatted_balance} ₸"
        )

    open_fee = get_open_price(car)

    new_rental = RentalHistory(
        user_id=target_user_uuid,
        car_id=car_uuid,
        rental_type=rental_type_enum,
        duration=parsed_duration,
        rental_status=RentalStatus.RESERVED,
        reservation_time=get_local_time(),
        start_latitude=car.latitude or 0,
        start_longitude=car.longitude or 0,
        open_fee=open_fee,
        base_price=required_balance,
    )

    db.add(new_rental)

    car.status = CarStatus.RESERVED
    car.current_renter_id = target_user_uuid

    target_user.last_activity_at = get_local_time()

    db.commit()
    db.refresh(new_rental)

    asyncio.create_task(notify_user_status_update(str(target_user.id)))

    return {
        "success": True,
        "message": "Машина успешно забронирована за клиента",
        "rental_id": uuid_to_sid(new_rental.id),
        "user_id": uuid_to_sid(new_rental.user_id),
        "car_id": uuid_to_sid(new_rental.car_id),
        "rental_type": new_rental.rental_type.value,
        "rental_status": new_rental.rental_status.value,
        "duration": new_rental.duration,
        "required_balance": required_balance,
        "reservation_time": new_rental.reservation_time.isoformat(),
        "reserved_by_admin": uuid_to_sid(current_user.id)
    }


@users_router.post("/rentals/cancel", response_model=AdminCancelReservationResponse)
async def support_cancel_reservation(
    request: AdminCancelReservationRequest,
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
) -> AdminCancelReservationResponse:
    """
    Отменить бронь/аренду клиента от имени support.
    Точная копия POST /admin/users/rentals/cancel.

    - rental_id: ID аренды
    - Работает для статусов: RESERVED, DELIVERING, DELIVERY_RESERVED, DELIVERING_IN_PROGRESS, SCHEDULED, IN_USE
    """
    try:
        rental_uuid = safe_sid_to_uuid(request.rental_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Неверный формат rental_id: {str(e)}")

    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")

    cancellable_statuses = [
        RentalStatus.RESERVED,
        RentalStatus.DELIVERING,
        RentalStatus.DELIVERY_RESERVED,
        RentalStatus.DELIVERING_IN_PROGRESS,
        RentalStatus.SCHEDULED,
        RentalStatus.IN_USE,
    ]

    if rental.rental_status not in cancellable_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Нельзя отменить аренду со статусом {rental.rental_status.value}"
        )

    previous_status = rental.rental_status.value

    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    rental.rental_status = RentalStatus.CANCELLED
    rental.end_time = datetime.now()

    car.current_renter_id = None
    car.status = CarStatus.FREE

    client_id = uuid_to_sid(rental.user_id) if rental.user_id else None

    db.commit()

    try:
        if rental.user_id:
            await notify_user_status_update(str(rental.user_id))
        if car.owner_id:
            await notify_user_status_update(str(car.owner_id))
    except Exception as e:
        logger.error(f"Error sending WebSocket notifications: {e}")

    return AdminCancelReservationResponse(
        message="Бронь отменена",
        rental_id=request.rental_id,
        car_name=car.name,
        plate_number=car.plate_number,
        previous_status=previous_status,
        client_id=client_id
    )


@users_router.post("/rentals/{rental_id}/admin-upload-photos-before")
async def support_upload_photos_before(
    rental_id: str,
    selfie: Optional[UploadFile] = File(None, description="Селфи клиента (необязательно для владельца)"),
    car_photos: List[UploadFile] = File(..., description="Фотографии кузова автомобиля"),
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """
    Загрузить фотографии ДО начала аренды от имени клиента (support).
    Аналог POST /admin/users/rentals/{rental_id}/admin-upload-photos-before.
    """
    try:
        rental_uuid = safe_sid_to_uuid(rental_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Неверный формат rental_id: {str(e)}")

    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")

    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    validate_photos(car_photos, "car_photos")
    if selfie:
        validate_photos([selfie], "selfie")

    uploaded_files = []
    try:
        urls = list(rental.photos_before or [])

        if selfie:
            selfie_url = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/before/selfie/")
            urls.append(selfie_url)
            uploaded_files.append(selfie_url)

        for p in car_photos:
            car_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/before/car/")
            urls.append(car_url)
            uploaded_files.append(car_url)

        rental.photos_before = urls
        db.commit()

        db.expire_all()
        db.refresh(rental)

        try:
            if rental.user_id:
                await notify_user_status_update(str(rental.user_id))
            if car.owner_id:
                await notify_user_status_update(str(car.owner_id))
        except Exception as e:
            logger.error("Error sending WebSocket notifications: %s", e)

        return {
            "message": "Фотографии до аренды (selfie+car) загружены",
            "rental_id": rental_id,
            "photo_count": len(urls),
            "selfie_uploaded": selfie is not None,
        }
    except HTTPException:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке фотографий: {str(e)}") from e


@users_router.post("/rentals/{rental_id}/admin-upload-photos-before-interior")
async def support_upload_photos_before_interior(
    rental_id: str,
    interior_photos: List[UploadFile] = File(..., description="Фотографии салона автомобиля"),
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """
    Загрузить фотографии салона ДО начала аренды от имени клиента (support).
    Аналог POST /admin/users/rentals/{rental_id}/admin-upload-photos-before-interior.
    """
    try:
        rental_uuid = safe_sid_to_uuid(rental_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Неверный формат rental_id: {str(e)}")

    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")

    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    validate_photos(interior_photos, "interior_photos")

    uploaded_files = []
    try:
        urls = list(rental.photos_before or [])

        for p in interior_photos:
            interior_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/before/interior/")
            urls.append(interior_url)
            uploaded_files.append(interior_url)

        rental.photos_before = urls
        db.commit()

        db.expire_all()
        db.refresh(rental)

        try:
            if rental.user_id:
                await notify_user_status_update(str(rental.user_id))
            if car.owner_id:
                await notify_user_status_update(str(car.owner_id))
        except Exception as e:
            logger.error("Error sending WebSocket notifications: %s", e)

        return {
            "message": "Фотографии салона до аренды загружены",
            "rental_id": rental_id,
            "photo_count": len(interior_photos),
        }
    except HTTPException:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке фотографий салона: {str(e)}") from e


@users_router.post("/rentals/{rental_id}/admin-upload-photos-after")
async def support_upload_photos_after(
    rental_id: str,
    selfie: Optional[UploadFile] = File(None, description="Селфи клиента (необязательно для владельца)"),
    interior_photos: List[UploadFile] = File(..., description="Фотографии салона автомобиля"),
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """
    Загрузить фотографии ПОСЛЕ аренды от имени клиента (support).
    Аналог POST /admin/users/rentals/{rental_id}/admin-upload-photos-after.
    """
    try:
        rental_uuid = safe_sid_to_uuid(rental_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Неверный формат rental_id: {str(e)}")

    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")

    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    validate_photos(interior_photos, "interior_photos")
    if selfie:
        validate_photos([selfie], "selfie")

    uploaded_files = []
    try:
        urls = list(rental.photos_after or [])

        if selfie:
            selfie_url = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/after/selfie/")
            urls.append(selfie_url)
            uploaded_files.append(selfie_url)

        for p in interior_photos:
            interior_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/after/interior/")
            urls.append(interior_url)
            uploaded_files.append(interior_url)

        rental.photos_after = urls
        db.commit()

        db.expire_all()
        db.refresh(rental)

        try:
            if rental.user_id:
                await notify_user_status_update(str(rental.user_id))
            if car.owner_id:
                await notify_user_status_update(str(car.owner_id))
        except Exception as e:
            logger.error("Error sending WebSocket notifications: %s", e)

        return {
            "message": "Фотографии после аренды (selfie+interior) загружены",
            "rental_id": rental_id,
            "photo_count": len(urls),
            "selfie_uploaded": selfie is not None,
        }
    except HTTPException:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке фотографий: {str(e)}") from e


@users_router.post("/rentals/{rental_id}/admin-upload-photos-after-car")
async def support_upload_photos_after_car(
    rental_id: str,
    car_photos: List[UploadFile] = File(..., description="Фотографии кузова автомобиля"),
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """
    Загрузить фотографии кузова ПОСЛЕ аренды от имени клиента (support).
    Аналог POST /admin/users/rentals/{rental_id}/admin-upload-photos-after-car.
    """
    try:
        rental_uuid = safe_sid_to_uuid(rental_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Неверный формат rental_id: {str(e)}")

    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")

    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    validate_photos(car_photos, "car_photos")

    uploaded_files = []
    try:
        urls = list(rental.photos_after or [])

        for p in car_photos:
            car_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/after/car/")
            urls.append(car_url)
            uploaded_files.append(car_url)

        rental.photos_after = urls
        db.commit()

        db.expire_all()
        db.refresh(rental)

        try:
            if rental.user_id:
                await notify_user_status_update(str(rental.user_id))
            if car.owner_id:
                await notify_user_status_update(str(car.owner_id))
        except Exception as e:
            logger.error("Error sending WebSocket notifications: %s", e)

        return {
            "message": "Фотографии кузова после аренды загружены",
            "rental_id": rental_id,
            "photo_count": len(car_photos),
        }
    except HTTPException:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise
    except Exception as e:
        db.rollback()
        delete_uploaded_files(uploaded_files)
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке фотографий кузова: {str(e)}") from e


@users_router.post("/rentals/review", response_model=AdminRentalReviewResponse)
async def support_submit_rental_review(
    request: AdminRentalReviewRequest,
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
) -> AdminRentalReviewResponse:
    """
    Добавить/обновить оценку и комментарий к аренде и завершить аренду (support).
    Аналог POST /admin/users/rentals/review.
    """
    return await submit_rental_review_impl(db, request)


@users_router.post("/rentals/{rental_id}/assign-mechanic", response_model=AssignMechanicResponse)
async def support_assign_mechanic(
    rental_id: str,
    request: AdminAssignMechanicRequest,
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
) -> AssignMechanicResponse:
    """
    Назначить механика для осмотра автомобиля (support).
    Аналог POST /admin/users/rentals/{rental_id}/assign-mechanic.
    """
    rental_uuid = safe_sid_to_uuid(rental_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")

    mechanic_uuid = safe_sid_to_uuid(request.mechanic_id)
    mechanic = db.query(User).filter(User.id == mechanic_uuid).first()
    if not mechanic:
        raise HTTPException(status_code=404, detail="Механик не найден")

    if mechanic.role != UserRole.MECHANIC:
        raise HTTPException(status_code=400, detail="Указанный пользователь не является механиком")

    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    rental.mechanic_inspector_id = mechanic.id
    rental.mechanic_inspection_status = "PENDING"

    car.status = CarStatus.SERVICE
    car.current_renter_id = mechanic.id

    log_action(
        db,
        actor_id=current_user.id,
        action="assign_mechanic",
        entity_type="rental",
        entity_id=rental.id,
        details={"mechanic_id": str(mechanic.id), "mechanic_name": f"{mechanic.first_name} {mechanic.last_name}"},
    )

    db.commit()

    try:
        await notify_user_status_update(str(mechanic.id))
        if rental.user_id:
            await notify_user_status_update(str(rental.user_id))
        if car.owner_id:
            await notify_user_status_update(str(car.owner_id))
    except Exception as e:
        logger.error("Error sending WebSocket notifications: %s", e)

    try:
        if user_has_push_tokens(db, mechanic.id):
            await send_localized_notification_to_user_async(
                mechanic.id,
                "inspection_assigned_by_admin",
                "inspection_assigned_by_admin",
                car_name=car.name,
                plate_number=car.plate_number,
            )
    except Exception as e:
        logger.error("Error sending push notification: %s", e)

    return AssignMechanicResponse(
        message="Механик назначен",
        rental_id=rental_id,
        mechanic_id=request.mechanic_id,
        mechanic_name=f"{mechanic.first_name or ''} {mechanic.last_name or ''}".strip(),
        car_name=car.name,
        plate_number=car.plate_number,
    )


@users_router.post("/rentals/{rental_id}/mechanic-start-inspection", response_model=MechanicStartInspectionResponse)
async def support_mechanic_start_inspection(
    rental_id: str,
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
) -> MechanicStartInspectionResponse:
    """
    Начать осмотр механиком (support). Аналог POST /admin/users/rentals/{rental_id}/mechanic-start-inspection.
    """
    rental_uuid = safe_sid_to_uuid(rental_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")

    if not rental.mechanic_inspector_id:
        raise HTTPException(status_code=400, detail="Механик-инспектор не назначен для этой аренды")

    if rental.mechanic_inspection_status != "PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"Осмотр может быть начат только со статусом PENDING. Текущий статус: {rental.mechanic_inspection_status}",
        )

    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    mechanic_id = rental.mechanic_inspector_id

    if not rental.mechanic_inspection_start_time:
        rental.mechanic_inspection_start_time = get_local_time()
        rental.mechanic_inspection_start_latitude = car.latitude
        rental.mechanic_inspection_start_longitude = car.longitude

    rental.mechanic_inspection_status = "IN_USE"

    car.status = CarStatus.IN_USE
    car.current_renter_id = mechanic_id

    log_action(
        db,
        actor_id=current_user.id,
        action="mechanic_start_inspection",
        entity_type="rental",
        entity_id=rental.id,
        details={"status": "IN_USE", "mechanic_id": str(mechanic_id)},
    )

    db.commit()

    try:
        await notify_user_status_update(str(mechanic_id))
        if rental.user_id:
            await notify_user_status_update(str(rental.user_id))
    except Exception as e:
        logger.error("Error sending WebSocket notifications: %s", e)

    return MechanicStartInspectionResponse(
        message="Осмотр начат",
        rental_id=rental_id,
        inspection_status="IN_USE",
    )


@users_router.post("/rentals/{rental_id}/mechanic-photos-before", response_model=MechanicPhotoUploadResponse)
async def support_mechanic_upload_photos_before(
    rental_id: str,
    selfie: Optional[UploadFile] = File(None),
    car_photos: List[UploadFile] = File(...),
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
) -> MechanicPhotoUploadResponse:
    """
    Загрузка фото ДО осмотра: селфи (опционально) + кузов (support).
    Аналог POST /admin/users/rentals/{rental_id}/mechanic-photos-before.
    """
    rental_uuid = safe_sid_to_uuid(rental_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")

    validate_photos(car_photos, "car_photos")
    urls = list(rental.mechanic_photos_before or [])

    if selfie:
        validate_photos([selfie], "selfie")
        selfie_url = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/mechanic/before/selfie/")
        urls.append(selfie_url)

    for p in car_photos:
        photo_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/mechanic/before/car/")
        urls.append(photo_url)

    rental.mechanic_photos_before = urls

    log_action(
        db,
        actor_id=current_user.id,
        action="mechanic_upload_photos_before",
        entity_type="rental",
        entity_id=rental.id,
        details={"photo_count": len(urls)},
    )
    db.commit()

    return MechanicPhotoUploadResponse(
        message="Фото до осмотра (селфи+кузов) загружены",
        photo_count=len(urls),
    )


@users_router.post("/rentals/{rental_id}/mechanic-photos-before-interior", response_model=MechanicPhotoUploadResponse)
async def support_mechanic_upload_photos_before_interior(
    rental_id: str,
    interior_photos: List[UploadFile] = File(...),
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
) -> MechanicPhotoUploadResponse:
    """
    Загрузка фото салона ДО осмотра (support).
    Аналог POST /admin/users/rentals/{rental_id}/mechanic-photos-before-interior.
    """
    rental_uuid = safe_sid_to_uuid(rental_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")

    validate_photos(interior_photos, "interior_photos")
    urls = list(rental.mechanic_photos_before or [])

    for p in interior_photos:
        photo_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/mechanic/before/interior/")
        urls.append(photo_url)

    rental.mechanic_photos_before = urls

    log_action(
        db,
        actor_id=current_user.id,
        action="mechanic_upload_photos_before_interior",
        entity_type="rental",
        entity_id=rental.id,
        details={"photo_count": len(urls)},
    )
    db.commit()

    return MechanicPhotoUploadResponse(
        message="Фото салона до осмотра загружены",
        photo_count=len(urls),
    )


@users_router.post("/rentals/{rental_id}/mechanic-photos-after", response_model=MechanicPhotoUploadResponse)
async def support_mechanic_upload_photos_after(
    rental_id: str,
    selfie: Optional[UploadFile] = File(None),
    interior_photos: List[UploadFile] = File(...),
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
) -> MechanicPhotoUploadResponse:
    """
    Загрузка фото ПОСЛЕ осмотра: селфи (опционально) + салон (support).
    Аналог POST /admin/users/rentals/{rental_id}/mechanic-photos-after.
    """
    rental_uuid = safe_sid_to_uuid(rental_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")

    validate_photos(interior_photos, "interior_photos")
    urls = list(rental.mechanic_photos_after or [])

    if selfie:
        validate_photos([selfie], "selfie")
        selfie_url = await save_file(selfie, rental.id, f"uploads/rents/{rental.id}/mechanic/after/selfie/")
        urls.append(selfie_url)

    for p in interior_photos:
        photo_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/mechanic/after/interior/")
        urls.append(photo_url)

    rental.mechanic_photos_after = urls

    log_action(
        db,
        actor_id=current_user.id,
        action="mechanic_upload_photos_after",
        entity_type="rental",
        entity_id=rental.id,
        details={"photo_count": len(urls)},
    )
    db.commit()

    return MechanicPhotoUploadResponse(
        message="Фото после осмотра (селфи+салон) загружены",
        photo_count=len(urls),
    )


@users_router.post("/rentals/{rental_id}/mechanic-photos-after-car", response_model=MechanicPhotoUploadResponse)
async def support_mechanic_upload_photos_after_car(
    rental_id: str,
    car_photos: List[UploadFile] = File(...),
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
) -> MechanicPhotoUploadResponse:
    """
    Загрузка фото кузова ПОСЛЕ осмотра (support).
    Аналог POST /admin/users/rentals/{rental_id}/mechanic-photos-after-car.
    """
    rental_uuid = safe_sid_to_uuid(rental_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")

    validate_photos(car_photos, "car_photos")
    urls = list(rental.mechanic_photos_after or [])

    for p in car_photos:
        photo_url = await save_file(p, rental.id, f"uploads/rents/{rental.id}/mechanic/after/car/")
        urls.append(photo_url)

    rental.mechanic_photos_after = urls

    log_action(
        db,
        actor_id=current_user.id,
        action="mechanic_upload_photos_after_car",
        entity_type="rental",
        entity_id=rental.id,
        details={"photo_count": len(urls)},
    )
    db.commit()

    return MechanicPhotoUploadResponse(
        message="Фото кузова после осмотра загружены",
        photo_count=len(urls),
    )


@users_router.post("/rentals/{rental_id}/mechanic-complete-inspection", response_model=MechanicCompleteInspectionResponse)
async def support_mechanic_complete_inspection(
    rental_id: str,
    request: AdminMechanicCompleteRequest,
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
) -> MechanicCompleteInspectionResponse:
    """
    Завершить осмотр механиком (support).
    Аналог POST /admin/users/rentals/{rental_id}/mechanic-complete-inspection.
    """
    rental_uuid = safe_sid_to_uuid(rental_id)
    rental = db.query(RentalHistory).filter(RentalHistory.id == rental_uuid).first()
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")

    car = db.query(Car).filter(Car.id == rental.car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    rental.mechanic_inspection_status = "COMPLETED"
    rental.mechanic_inspection_end_time = get_local_time()
    rental.mechanic_inspection_end_latitude = car.latitude
    rental.mechanic_inspection_end_longitude = car.longitude
    rental.mechanic_inspection_comment = request.comment

    rental.rental_status = RentalStatus.COMPLETED
    if not rental.end_time:
        rental.end_time = get_local_time()

    if request.rating:
        existing_review = db.query(RentalReview).filter(RentalReview.rental_id == rental.id).first()
        if existing_review:
            existing_review.mechanic_rating = request.rating
            existing_review.mechanic_comment = request.comment
        else:
            review = RentalReview(
                rental_id=rental.id,
                mechanic_rating=request.rating,
                mechanic_comment=request.comment,
            )
            db.add(review)

    car.status = CarStatus.FREE
    car.current_renter_id = None

    log_action(
        db,
        actor_id=current_user.id,
        action="mechanic_complete_inspection",
        entity_type="rental",
        entity_id=rental.id,
        details={"rating": request.rating, "comment": request.comment},
    )

    db.commit()

    try:
        await notify_user_status_update(str(current_user.id))
        if rental.user_id:
            await notify_user_status_update(str(rental.user_id))
    except Exception as e:
        logger.error("Error sending WebSocket notifications: %s", e)

    return MechanicCompleteInspectionResponse(
        message="Осмотр завершён",
        rental_id=rental_id,
        car_status="FREE",
        rating=request.rating,
    )


# ---------------------------------------------------------------------------
# Transactions endpoints (support)
# ---------------------------------------------------------------------------

@users_router.get("/{user_id}/transactions/summary")
async def support_get_user_transactions_summary(
    user_id: str,
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(12, ge=1, le=60, description="Количество месяцев на странице"),
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """Агрегированные данные по транзакциям пользователя, сгруппированные по месяцам (support)."""
    from collections import defaultdict
    from math import ceil
    from app.utils.time_utils import get_local_time
    from app.models.wallet_transaction_model import WalletTransaction, WalletTransactionType

    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    all_tx = db.query(WalletTransaction).filter(WalletTransaction.user_id == user.id).all()

    DEPOSIT_TX_TYPES = {
        WalletTransactionType.DEPOSIT,
        WalletTransactionType.PROMO_BONUS,
        WalletTransactionType.COMPANY_BONUS,
        WalletTransactionType.REFUND,
    }

    monthly = defaultdict(lambda: {"transactions_count": 0, "total_deposits": 0.0, "total_expenses": 0.0})
    total_deposits_all_time = 0.0
    total_expenses_all_time = 0.0

    for tx in all_tx:
        dt = tx.created_at
        if not dt:
            continue
        key = (dt.year, dt.month)
        monthly[key]["transactions_count"] += 1
        amt = float(tx.amount)
        if tx.transaction_type in DEPOSIT_TX_TYPES:
            monthly[key]["total_deposits"] += amt
            total_deposits_all_time += amt
        else:
            monthly[key]["total_expenses"] += amt
            total_expenses_all_time += amt

    now = get_local_time()
    sorted_months = sorted(monthly.keys(), reverse=True)
    total_months = len(sorted_months)
    paginated = sorted_months[(page - 1) * limit : page * limit]

    months_result = []
    for year, month in paginated:
        d = monthly[(year, month)]
        months_result.append({
            "year": year,
            "month": month,
            "transactions_count": d["transactions_count"],
            "total_deposits": round(d["total_deposits"], 2),
            "total_expenses": round(d["total_expenses"], 2),
            "net_change": round(d["total_deposits"] + d["total_expenses"], 2),
            "is_current_month": (year == now.year and month == now.month),
        })

    return {
        "user_id": uuid_to_sid(user.id),
        "user_name": f"{user.first_name or ''} {user.last_name or ''}".strip() or None,
        "wallet_balance": float(user.wallet_balance) if user.wallet_balance else 0.0,
        "total_deposits_all_time": round(total_deposits_all_time, 2),
        "total_expenses_all_time": round(total_expenses_all_time, 2),
        "current_month": {"year": now.year, "month": now.month},
        "months": months_result,
        "total": total_months,
        "page": page,
        "limit": limit,
        "pages": ceil(total_months / limit) if limit > 0 else 0,
    }


@users_router.get("/{user_id}/transactions", response_model=WalletTransactionPaginationSchema)
async def support_get_user_transactions(
    user_id: str,
    month: Optional[int] = Query(None, ge=1, le=12, description="Месяц (1-12)"),
    year: Optional[int] = Query(None, description="Год"),
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(20, ge=1, le=100, description="Количество элементов на странице"),
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """Получение истории транзакций пользователя (support)."""
    from calendar import monthrange
    from math import ceil
    from sqlalchemy import desc
    from app.models.wallet_transaction_model import WalletTransaction
    from app.models.history_model import RentalHistory

    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    query = db.query(WalletTransaction).filter(WalletTransaction.user_id == user.id)

    if month is not None and year is not None:
        start_dt = datetime(year, month, 1)
        end_dt = datetime(year, month, monthrange(year, month)[1], 23, 59, 59)
        query = query.filter(
            WalletTransaction.created_at >= start_dt,
            WalletTransaction.created_at <= end_dt,
        )

    query = query.order_by(desc(WalletTransaction.created_at))

    total_count = query.count()
    transactions = query.offset((page - 1) * limit).limit(limit).all()

    # Маппинг rental_id -> car_id для добавления car_id к транзакциям
    rental_ids = [tx.related_rental_id for tx in transactions if tx.related_rental_id]
    rental_id_to_car_id = {}
    if rental_ids:
        rentals = db.query(RentalHistory.id, RentalHistory.car_id).filter(
            RentalHistory.id.in_(rental_ids)
        ).all()
        rental_id_to_car_id = {r.id: r.car_id for r in rentals if r.car_id}

    items = []
    for tx in transactions:
        car_id_sid = None
        if tx.related_rental_id and tx.related_rental_id in rental_id_to_car_id:
            car_id_sid = uuid_to_sid(rental_id_to_car_id[tx.related_rental_id])
        tx_data = {
            "id": uuid_to_sid(tx.id),
            "amount": float(tx.amount),
            "transaction_type": tx.transaction_type.value if hasattr(tx.transaction_type, "value") else str(tx.transaction_type),
            "description": tx.description,
            "balance_before": float(tx.balance_before),
            "balance_after": float(tx.balance_after),
            "tracking_id": tx.tracking_id,
            "created_at": tx.created_at,
            "related_rental_id": uuid_to_sid(tx.related_rental_id) if tx.related_rental_id else None,
            "car_id": car_id_sid,
        }
        items.append(WalletTransactionSchema(**tx_data))

    return {
        "items": items,
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": ceil(total_count / limit) if total_count > 0 else 0,
        "wallet_balance": float(user.wallet_balance) if user.wallet_balance else 0.0,
    }


@users_router.get("/{user_id}/transactions-grouped", response_model=GroupedTransactionsPaginationSchema)
async def support_get_user_transactions_grouped(
    user_id: str,
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(50, ge=1, le=200, description="Количество элементов на странице"),
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """Получение истории транзакций пользователя с группировкой по аренде (support)."""
    from collections import defaultdict
    from math import ceil, floor
    from sqlalchemy.orm import joinedload
    from sqlalchemy import desc
    from app.models.wallet_transaction_model import WalletTransaction
    from app.models.history_model import RentalHistory, RentalStatus
    from app.models.car_model import Car, CarBodyType
    from app.admin.cars.utils import sort_car_photos
    from app.rent.utils.calculate_price import FUEL_PRICE_PER_LITER, ELECTRIC_FUEL_PRICE_PER_LITER

    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Все транзакции
    all_transactions = (
        db.query(WalletTransaction)
        .filter(WalletTransaction.user_id == user.id)
        .order_by(desc(WalletTransaction.created_at), desc(WalletTransaction.id))
        .all()
    )

    # Все аренды
    all_user_rentals = (
        db.query(RentalHistory)
        .options(joinedload(RentalHistory.car), joinedload(RentalHistory.user))
        .filter(RentalHistory.user_id == user.id)
        .all()
    )

    # Группируем транзакции по rental_id
    rental_transactions = defaultdict(list)
    standalone_transactions = []

    for tx in all_transactions:
        if tx.related_rental_id:
            rental_transactions[tx.related_rental_id].append(tx)
        else:
            standalone_transactions.append(tx)

    # Для каждой аренды добавляем транзакции по временному диапазону с проверкой цепочки балансов
    for rental in all_user_rentals:
        if rental.id not in rental_transactions:
            rental_transactions[rental.id] = []

        start_bound = rental.reservation_time if rental.reservation_time else rental.start_time
        end_bound = rental.end_time

        if start_bound and end_bound:
            transactions_in_range = []
            for tx in standalone_transactions:
                if tx.created_at and start_bound <= tx.created_at <= end_bound:
                    transactions_in_range.append(tx)

            if transactions_in_range:
                if rental_transactions[rental.id]:
                    all_rental_txs = list(rental_transactions[rental.id])

                    for tx in transactions_in_range:
                        can_add = False

                        if tx.balance_before is None or tx.balance_after is None:
                            continue

                        for i, existing_tx in enumerate(all_rental_txs):
                            if existing_tx.balance_before is None or existing_tx.balance_after is None:
                                continue

                            if tx.created_at and existing_tx.created_at and tx.created_at <= existing_tx.created_at:
                                if i == 0:
                                    if abs(float(tx.balance_after) - float(existing_tx.balance_before)) < 0.01:
                                        can_add = True
                                        break
                                else:
                                    prev_tx = all_rental_txs[i - 1]
                                    if prev_tx.balance_after is not None and prev_tx.balance_before is not None:
                                        if (
                                            abs(float(prev_tx.balance_after) - float(tx.balance_before)) < 0.01
                                            and abs(float(tx.balance_after) - float(existing_tx.balance_before)) < 0.01
                                        ):
                                            can_add = True
                                            break

                        if not can_add and all_rental_txs:
                            last_tx = all_rental_txs[-1]
                            if (
                                last_tx.balance_after is not None
                                and tx.created_at
                                and last_tx.created_at
                                and tx.created_at >= last_tx.created_at
                            ):
                                if abs(float(last_tx.balance_after) - float(tx.balance_before)) < 0.01:
                                    can_add = True

                        if can_add:
                            rental_transactions[rental.id].append(tx)
                            all_rental_txs = list(rental_transactions[rental.id])

    # Убираем из standalone те, что были добавлены к арендам
    used_tx_ids = set()
    for transactions in rental_transactions.values():
        for tx in transactions:
            used_tx_ids.add(tx.id)

    standalone_transactions = [tx for tx in standalone_transactions if tx.id not in used_tx_ids]

    # Собираем все элементы
    all_items = []

    for rental_id, transactions in rental_transactions.items():
        rental = None
        for r in all_user_rentals:
            if r.id == rental_id:
                rental = r
                break

        if not rental:
            rental = (
                db.query(RentalHistory)
                .options(joinedload(RentalHistory.car), joinedload(RentalHistory.user))
                .filter(RentalHistory.id == rental_id)
                .first()
            )

        if rental and transactions:
            car = rental.car
            renter = rental.user

            # fuel_fee
            fuel_fee = 0
            if rental.fuel_before is not None and rental.fuel_after is not None:
                if rental.fuel_after < rental.fuel_before:
                    fuel_consumed = ceil(rental.fuel_before) - floor(rental.fuel_after)
                    if fuel_consumed > 0 and car:
                        fuel_price = ELECTRIC_FUEL_PRICE_PER_LITER if car.body_type == CarBodyType.ELECTRIC else FUEL_PRICE_PER_LITER
                        fuel_fee = int(fuel_consumed * fuel_price)

            total_price_without_fuel = (
                (rental.base_price or 0)
                + (rental.open_fee or 0)
                + (rental.delivery_fee or 0)
                + (rental.waiting_fee or 0)
                + (rental.overtime_fee or 0)
                + (rental.distance_fee or 0)
                + (rental.driver_fee or 0)
            )

            car_info = {}
            if car:
                car_info = {
                    "id": uuid_to_sid(car.id),
                    "name": car.name,
                    "plate_number": car.plate_number,
                    "engine_volume": car.engine_volume,
                    "year": car.year,
                    "drive_type": car.drive_type,
                    "transmission_type": car.transmission_type.value if car.transmission_type else None,
                    "body_type": car.body_type.value if car.body_type else None,
                    "auto_class": car.auto_class.value if car.auto_class else None,
                    "price_per_minute": car.price_per_minute,
                    "price_per_hour": car.price_per_hour,
                    "price_per_day": car.price_per_day,
                    "minutes_tariff_enabled": getattr(car, "minutes_tariff_enabled", True),
                    "hourly_tariff_enabled": getattr(car, "hourly_tariff_enabled", True),
                    "hourly_min_hours": max(1, getattr(car, "hourly_min_hours", 1) or 1),
                    "latitude": car.latitude,
                    "longitude": car.longitude,
                    "fuel_level": car.fuel_level,
                    "mileage": car.mileage,
                    "course": car.course,
                    "photos": sort_car_photos(car.photos or []),
                    "description": car.description,
                    "vin": car.vin,
                    "color": car.color,
                    "gps_id": car.gps_id,
                    "gps_imei": car.gps_imei,
                    "status": car.status.value if car.status else None,
                }

            renter_info = {}
            if renter:
                is_owner = False
                if car and car.owner_id:
                    is_owner = renter.id == car.owner_id
                renter_info = {
                    "id": uuid_to_sid(renter.id),
                    "first_name": renter.first_name,
                    "last_name": renter.last_name,
                    "phone_number": renter.phone_number,
                    "selfie": renter.selfie_url,
                    "is_owner": is_owner,
                }

            tariff_value = rental.rental_type.value if hasattr(rental.rental_type, "value") else str(rental.rental_type)
            tariff_map = {"minutes": "Минутный", "hours": "Часовой", "days": "Суточный"}
            tariff_display = tariff_map.get(tariff_value, tariff_value)

            base_price_owner = int((rental.base_price or 0) * 0.5 * 0.97)
            waiting_fee_owner = int((rental.waiting_fee or 0) * 0.5 * 0.97)
            overtime_fee_owner = int((rental.overtime_fee or 0) * 0.5 * 0.97)
            total_owner_earnings = int(
                ((rental.base_price or 0) + (rental.waiting_fee or 0) + (rental.overtime_fee or 0)) * 0.5 * 0.97
            )

            transactions_list = []
            sorted_transactions = sorted(transactions, key=lambda x: (x.created_at or datetime.min, x.id or ""))
            for tx in sorted_transactions:
                transactions_list.append({
                    "id": uuid_to_sid(tx.id),
                    "amount": float(tx.amount),
                    "transaction_type": tx.transaction_type.value if hasattr(tx.transaction_type, "value") else str(tx.transaction_type),
                    "description": tx.description,
                    "balance_before": float(tx.balance_before),
                    "balance_after": float(tx.balance_after),
                    "tracking_id": tx.tracking_id,
                    "created_at": tx.created_at.isoformat() if tx.created_at else None,
                    "related_rental_id": uuid_to_sid(tx.related_rental_id) if tx.related_rental_id else None,
                })

            first_tx = sorted_transactions[0] if sorted_transactions else None
            last_tx = sorted_transactions[-1] if sorted_transactions else None
            rental_balance_before = float(first_tx.balance_before) if first_tx and first_tx.balance_before is not None else 0.0
            rental_balance_after = float(last_tx.balance_after) if last_tx and last_tx.balance_after is not None else 0.0

            rental_data = {
                "rental_id": uuid_to_sid(rental.id),
                "car": car_info,
                "reservation_time": rental.reservation_time.isoformat() if rental.reservation_time else None,
                "start_time": rental.start_time.isoformat() if rental.start_time else None,
                "end_time": rental.end_time.isoformat() if rental.end_time else None,
                "duration": rental.duration,
                "already_payed": rental.already_payed or 0,
                "total_price": rental.total_price or 0,
                "total_price_without_fuel": total_price_without_fuel,
                "tariff": tariff_value,
                "tariff_display": tariff_display,
                "base_price": rental.base_price or 0,
                "open_fee": rental.open_fee or 0,
                "delivery_fee": rental.delivery_fee or 0,
                "fuel_fee": fuel_fee,
                "waiting_fee": rental.waiting_fee or 0,
                "overtime_fee": rental.overtime_fee or 0,
                "distance_fee": rental.distance_fee or 0,
                "with_driver": rental.with_driver or False,
                "driver_fee": rental.driver_fee or 0,
                "rebooking_fee": rental.rebooking_fee or 0,
                "base_price_owner": base_price_owner,
                "waiting_fee_owner": waiting_fee_owner,
                "overtime_fee_owner": overtime_fee_owner,
                "total_owner_earnings": total_owner_earnings,
                "fuel_before": float(rental.fuel_before) if rental.fuel_before is not None else None,
                "fuel_after": float(rental.fuel_after) if rental.fuel_after is not None else None,
                "renter": renter_info,
                "transactions": transactions_list,
                "balance_before": rental_balance_before,
                "balance_after": rental_balance_after,
            }

            if transactions:
                earliest_tx = min(transactions, key=lambda x: (x.created_at or datetime.max, x.id or ""))
                sort_date = earliest_tx.created_at
            else:
                sort_date = rental.reservation_time if rental.reservation_time else rental.start_time

            all_items.append({
                "type": "rental",
                "created_at": sort_date,
                "rental": rental_data,
                "transaction": None,
                "sort_id": rental.id,
            })

    # Отдельные транзакции
    for tx in standalone_transactions:
        tx_data = {
            "id": uuid_to_sid(tx.id),
            "amount": float(tx.amount),
            "transaction_type": tx.transaction_type.value if hasattr(tx.transaction_type, "value") else str(tx.transaction_type),
            "description": tx.description,
            "balance_before": float(tx.balance_before),
            "balance_after": float(tx.balance_after),
            "tracking_id": tx.tracking_id,
            "created_at": tx.created_at,
            "related_rental_id": uuid_to_sid(tx.related_rental_id) if tx.related_rental_id else None,
        }
        all_items.append({
            "type": "transaction",
            "created_at": tx.created_at,
            "transaction": WalletTransactionSchema(**tx_data),
            "rental": None,
            "sort_id": tx.id,
        })

    # Сортировка
    all_items.sort(
        key=lambda x: (x["created_at"] if x["created_at"] else datetime.min, x.get("sort_id", "")),
        reverse=True,
    )

    total_count = len(all_items)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated_items = all_items[start_idx:end_idx]

    result_items = []
    for item in paginated_items:
        item_copy = {k: v for k, v in item.items() if k != "sort_id"}
        result_items.append(GroupedTransactionItemSchema(**item_copy))

    return {
        "items": result_items,
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": ceil(total_count / limit) if limit > 0 else 0,
        "wallet_balance": float(user.wallet_balance) if user.wallet_balance else 0.0,
    }


@users_router.post("/{user_id}/balance/recalculate")
async def support_recalculate_user_balance(
    user_id: str,
    initial_balance: Optional[float] = Form(0.0, description="Начальный баланс перед первой транзакцией (по умолчанию 0)"),
    current_user: User = Depends(require_support_role),
    db: Session = Depends(get_db),
):
    """
    Пересчёт балансов всех транзакций пользователя (support).
    Действие логируется с actor_role=support.
    """
    from math import ceil
    from app.models.wallet_transaction_model import WalletTransaction

    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    all_transactions = (
        db.query(WalletTransaction)
        .filter(WalletTransaction.user_id == user_uuid)
        .order_by(WalletTransaction.created_at.asc())
        .all()
    )

    if not all_transactions:
        raise HTTPException(status_code=400, detail="У пользователя нет транзакций для пересчёта")

    old_balance = float(user.wallet_balance or 0)
    running_balance = float(initial_balance or 0)
    updated_count = 0

    for tx in all_transactions:
        tx.balance_before = running_balance
        tx.balance_after = running_balance + float(tx.amount)
        running_balance = tx.balance_after
        updated_count += 1

    new_balance = running_balance
    user.wallet_balance = new_balance

    log_action(
        db,
        actor_id=current_user.id,
        action="balance_recalculate",
        entity_type="user",
        entity_id=user.id,
        details={
            "user_id": user_id,
            "initial_balance": initial_balance,
            "old_balance": old_balance,
            "new_balance": new_balance,
            "transactions_count": updated_count,
            "balance_difference": new_balance - old_balance,
            "actor_role": "support",
        },
    )

    db.commit()

    return {
        "success": True,
        "message": "Балансы транзакций успешно пересчитаны",
        "user_id": uuid_to_sid(user_uuid),
        "initial_balance": initial_balance,
        "old_balance": old_balance,
        "new_balance": new_balance,
        "balance_difference": new_balance - old_balance,
        "transactions_updated": updated_count,
    }
