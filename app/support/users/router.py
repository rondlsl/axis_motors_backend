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
from app.admin.users.router import get_users_list_impl, submit_rental_review_impl
from app.admin.users.schemas import (
    UserPaginatedResponse,
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
)
from app.support.deps import require_support_role
from app.utils.short_id import safe_sid_to_uuid, uuid_to_sid
from app.utils.action_logger import log_action
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
