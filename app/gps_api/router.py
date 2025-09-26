from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import or_, func
from sqlalchemy.orm import Session
from typing import Dict, Any, List
import asyncio

from starlette import status

from app.core.config import GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD, RENTED_CARS_ENDPOINT_KEY
from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.gps_api.schemas import RentedCar
from app.models.car_model import Car, CarAutoClass
from app.models.history_model import RentalHistory, RentalStatus
from app.models.rental_actions_model import ActionType, RentalAction
from app.models.user_model import User, UserRole
from app.models.application_model import Application, ApplicationStatus
from app.gps_api.utils.auth_api import get_auth_token
from app.gps_api.utils.get_active_rental import get_active_rental_car, get_active_rental
from app.gps_api.utils.car_data import send_command_to_terminal, send_open, send_close, send_give_key, send_take_key, send_lock_engine, send_unlock_engine
from app.rent.utils.calculate_price import get_open_price

Vehicle_Router = APIRouter(prefix="/vehicles", tags=["Vehicles"])

AUTH_TOKEN = ""
BASE_URL = "https://regions.glonasssoft.ru"
started = False


def validate_user_can_control_car(current_user: User, db: Session) -> None:
    """
    Валидация прав пользователя на управление автомобилем.
    Проверяет роль и статус заявки пользователя.
    """
    # Админы и механики могут управлять автомобилями
    if current_user.role in [UserRole.ADMIN, UserRole.MECHANIC]:
        return
    
    # Блокированные пользователи не могут управлять
    if current_user.role in [UserRole.REJECTSECOND]:
        raise HTTPException(
            status_code=403, 
            detail="Доступ к управлению автомобилем заблокирован"
        )
    
    # Пользователи без документов не могут управлять
    if current_user.role == UserRole.CLIENT:
        raise HTTPException(
            status_code=403, 
            detail="Для управления автомобилем необходимо загрузить документы"
        )
    
    # Пользователи с неправильными документами не могут управлять
    if current_user.role == UserRole.REJECTFIRSTDOC:
        raise HTTPException(
            status_code=403, 
            detail="Необходимо загрузить документы заново"
        )
    
    # Пользователи с финансовыми проблемами не могут управлять
    if current_user.role == UserRole.REJECTFIRST:
        raise HTTPException(
            status_code=403, 
            detail="Управление недоступно по финансовым причинам"
        )
    
    # Пользователи в процессе верификации не могут управлять
    if current_user.role in [UserRole.PENDINGTOFIRST, UserRole.PENDINGTOSECOND]:
        raise HTTPException(
            status_code=403, 
            detail="Ваша заявка на рассмотрении"
        )
    
    # Для роли USER проверяем полную верификацию
    if current_user.role == UserRole.USER:
        if not bool(current_user.documents_verified):
            raise HTTPException(
                status_code=403, 
                detail="Для управления автомобилем необходимо пройти верификацию"
            )
        
        # Проверяем одобрение финансиста и МВД
        application = (
            db.query(Application)
            .filter(Application.user_id == current_user.id)
            .first()
        )
        if not application or application.financier_status != ApplicationStatus.APPROVED or application.mvd_status != ApplicationStatus.APPROVED:
            raise HTTPException(
                status_code=403, 
                detail="Для управления автомобилем требуется одобрение финансиста и МВД"
            )


@Vehicle_Router.on_event("startup")
async def start_token_refresh():
    global started
    if not started:
        started = True

        async def refresh_token():
            global AUTH_TOKEN
            while True:
                try:
                    AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
                except Exception as e:
                    print("Ошибка обновления токена: {e}")
                await asyncio.sleep(1800)

        asyncio.create_task(refresh_token())


@Vehicle_Router.get("/get_vehicles")
def get_vehicle_info(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    try:
        if current_user.role == UserRole.REJECTFIRST:
            return {"vehicles": []}
        
        # Базовый фильтр: только свободные машины
        query = db.query(Car).filter(Car.status == "FREE")

        # Фильтрация по классам авто для роли USER при верифицированных документах
        if current_user.role == UserRole.USER and bool(current_user.documents_verified):
            allowed_classes: list[str] = []

            # Поле users.auto_class может прийти как массив ["A","B"] или строка вида "{A, B}" или "{""A, B, C""}"
            if isinstance(current_user.auto_class, list):
                allowed_classes = [str(c).strip().upper() for c in current_user.auto_class if c]
            elif isinstance(current_user.auto_class, str):
                raw = current_user.auto_class.strip()
                if raw.startswith("{") and raw.endswith("}"):
                    raw = raw[1:-1]
                # Убираем все кавычки и обрабатываем строку
                raw = raw.replace('"', '').replace("'", "")
                allowed_classes = [part.strip().upper() for part in raw.split(",") if part.strip()]

            # Преобразуем в enum значения, игнорируя неизвестные элементы
            allowed_enum: list[CarAutoClass] = []
            for cls in allowed_classes:
                try:
                    allowed_enum.append(CarAutoClass(cls))
                except Exception:
                    # Пропускаем некорректные значения
                    pass

            if len(allowed_enum) == 0:
                cars = []
            else:
                cars = query.filter(Car.auto_class.in_(allowed_enum)).all()
        else:
            # Для CLIENT и прочих ролей — без ограничений по классу (только FREE)
            cars = query.all()

        vehicles_data = [{
            "id": car.id,
            "name": car.name,
            "plate_number": car.plate_number,
            "latitude": car.latitude,
            "longitude": car.longitude,
            "course": car.course,
            "fuel_level": car.fuel_level,
            "price_per_minute": car.price_per_minute,
            "price_per_hour": car.price_per_hour,
            "price_per_day": car.price_per_day,
            "engine_volume": car.engine_volume,
            "year": car.year,
            "drive_type": car.drive_type,
            "transmission_type": car.transmission_type,
            "body_type": car.body_type,
            "auto_class": car.auto_class,
            "photos": car.photos,
            "owner_id": car.owner_id,
            "current_renter_id": car.current_renter_id,
            "status": car.status,
            "open_price": get_open_price(car),
            "owned_car": True if car.owner_id == current_user.id else False
        } for car in cars]

        return {"vehicles": vehicles_data}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching vehicles data: {str(e)}")


@Vehicle_Router.get("/search")
def search_vehicles(
        query: str = Query(..., description="Поисковый запрос по названию авто или номеру"),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    try:
        if current_user.role == UserRole.REJECTFIRST:
            return {"vehicles": []}
        
        # Ищем по имени или номеру и проверяем, что машина свободна по статусу
        cars = db.query(Car).filter(
            or_(
                Car.name.ilike(f"%{query}%"),
                Car.plate_number.ilike(f"%{query}%")
            ),
            Car.status == "FREE"
        ).all()

        vehicles_data = [{
            "id": car.id,
            "name": car.name,
            "plate_number": car.plate_number,
            "latitude": car.latitude,
            "longitude": car.longitude,
            "course": car.course,
            "fuel_level": car.fuel_level,
            "price_per_minute": car.price_per_minute,
            "price_per_hour": car.price_per_hour,
            "price_per_day": car.price_per_day,
            "engine_volume": car.engine_volume,
            "year": car.year,
            "drive_type": car.drive_type,
            "transmission_type": car.transmission_type,
            "body_type": car.body_type,
            "auto_class": car.auto_class,
            "photos": car.photos,
            "owner_id": car.owner_id,
            "current_renter_id": car.current_renter_id,
            "status": car.status,
            "open_price": get_open_price(car),
            "owned_car": True if car.owner_id == current_user.id else False
        } for car in cars]

        return {"vehicles": vehicles_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка поиска авто: {str(e)}")


@Vehicle_Router.get("/frequently-used")
def get_frequently_used_vehicles(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    try:
        if current_user.role == UserRole.REJECTFIRST:
            return {"vehicles": []}
        
        # Получаем ID машин и количество аренд для текущего пользователя
        rental_counts = (
            db.query(RentalHistory.car_id, func.count(RentalHistory.id).label("rental_count"))
            .filter(RentalHistory.user_id == current_user.id)
            .group_by(RentalHistory.car_id)
            .order_by(func.count(RentalHistory.id).desc())
            .all()
        )

        if not rental_counts:
            raise HTTPException(status_code=404, detail="Вы ещё не арендовали ни одной машины")

        car_ids = [r.car_id for r in rental_counts]

        # Загружаем только свободные машины, проверяя статус
        cars = (
            db.query(Car)
            .filter(
                Car.id.in_(car_ids),
                Car.status == "FREE"
            )
            .all()
        )

        if not cars:
            raise HTTPException(status_code=404, detail="Все часто используемые вами машины сейчас заняты")

        car_dict = {car.id: car for car in cars}

        vehicles_data = []
        for r in rental_counts:
            car = car_dict.get(r.car_id)
            if car:
                vehicles_data.append({
                    "id": car.id,
                    "name": car.name,
                    "plate_number": car.plate_number,
                    "latitude": car.latitude,
                    "longitude": car.longitude,
                    "course": car.course,
                    "fuel_level": car.fuel_level,
                    "price_per_minute": car.price_per_minute,
                    "price_per_hour": car.price_per_hour,
                    "price_per_day": car.price_per_day,
                    "engine_volume": car.engine_volume,
                    "year": car.year,
                    "drive_type": car.drive_type,
                    "transmission_type": car.transmission_type,
                    "body_type": car.body_type,
                    "auto_class": car.auto_class,
                    "photos": car.photos,
                    "owner_id": car.owner_id,
                    "rental_count": r.rental_count,
                    "status": car.status,
                    "open_price": get_open_price(car),
                    "owned_car": True if car.owner_id == current_user.id else False
                })

        if not vehicles_data:
            raise HTTPException(status_code=404, detail="Нет свободных машин из тех, что вы часто арендовали")

        return {"vehicles": vehicles_data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


# === КОМАНДЫ GlonassSoft ===

@Vehicle_Router.post("/open")
async def open_vehicle(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    validate_user_can_control_car(current_user, db)
    global AUTH_TOKEN
    rental = get_active_rental(db, current_user.id)
    car = db.get(Car, rental.car_id)
    
    # Проверяем и обновляем токен если необходимо
    if not AUTH_TOKEN:
        try:
            AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    # логируем действие
    action = RentalAction(
        rental_id=rental.id,
        user_id=current_user.id,
        action_type=ActionType.OPEN_VEHICLE
    )
    db.add(action)
    # отправляем команду
    cmd = await send_open(car.gps_imei, AUTH_TOKEN)
    db.commit()

    return cmd


@Vehicle_Router.post("/close")
async def close_vehicle(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    validate_user_can_control_car(current_user, db)
    global AUTH_TOKEN
    rental = get_active_rental(db, current_user.id)
    car = db.get(Car, rental.car_id)
    
    # Проверяем и обновляем токен если необходимо
    if not AUTH_TOKEN:
        try:
            AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    action = RentalAction(
        rental_id=rental.id,
        user_id=current_user.id,
        action_type=ActionType.CLOSE_VEHICLE
    )
    db.add(action)
    cmd = await send_close(car.gps_imei, AUTH_TOKEN)
    db.commit()

    return cmd


@Vehicle_Router.post("/give_key")
async def give_key(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    validate_user_can_control_car(current_user, db)
    global AUTH_TOKEN
    rental = get_active_rental(db, current_user.id)
    car = db.get(Car, rental.car_id)
    
    # Проверяем и обновляем токен если необходимо
    if not AUTH_TOKEN:
        try:
            AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    action = RentalAction(
        rental_id=rental.id,
        user_id=current_user.id,
        action_type=ActionType.GIVE_KEY
    )
    db.add(action)
    cmd = await send_give_key(car.gps_imei, AUTH_TOKEN)
    db.commit()
    return cmd


@Vehicle_Router.post("/take_key")
async def take_key(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    validate_user_can_control_car(current_user, db)
    global AUTH_TOKEN
    rental = get_active_rental(db, current_user.id)
    car = db.get(Car, rental.car_id)
    
    # Проверяем и обновляем токен если необходимо
    if not AUTH_TOKEN:
        try:
            AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    action = RentalAction(
        rental_id=rental.id,
        user_id=current_user.id,
        action_type=ActionType.TAKE_KEY
    )
    db.add(action)
    cmd = await send_take_key(car.gps_imei, AUTH_TOKEN)
    db.commit()
    return cmd


@Vehicle_Router.post("/lock_engine", summary="Заблокировать двигатель")
async def lock_engine(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    validate_user_can_control_car(current_user, db)
    """Заблокировать двигатель автомобиля"""
    global AUTH_TOKEN
    rental = get_active_rental(db, current_user.id)
    car = db.get(Car, rental.car_id)
    
    # Проверяем и обновляем токен если необходимо
    if not AUTH_TOKEN:
        try:
            AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    action = RentalAction(
        rental_id=rental.id,
        user_id=current_user.id,
        action_type=ActionType.LOCK_ENGINE
    )
    db.add(action)
    cmd = await send_lock_engine(car.gps_imei, AUTH_TOKEN)
    db.commit()
    return cmd


@Vehicle_Router.post("/unlock_engine", summary="Разблокировать двигатель")
async def unlock_engine(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    validate_user_can_control_car(current_user, db)
    """Разблокировать двигатель автомобиля"""
    global AUTH_TOKEN
    rental = get_active_rental(db, current_user.id)
    car = db.get(Car, rental.car_id)
    
    # Проверяем и обновляем токен если необходимо
    if not AUTH_TOKEN:
        try:
            AUTH_TOKEN = await get_auth_token(BASE_URL, GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка получения токена: {e}")
    
    action = RentalAction(
        rental_id=rental.id,
        user_id=current_user.id,
        action_type=ActionType.UNLOCK_ENGINE
    )
    db.add(action)
    cmd = await send_unlock_engine(car.gps_imei, AUTH_TOKEN)
    db.commit()
    return cmd


@Vehicle_Router.get("/rented", response_model=List[RentedCar], summary="Список машин в аренде")
def get_rented_cars(
        key: str = Query(..., description="Секретный ключ доступа"),
        db: Session = Depends(get_db),
):
    # 1) Проверяем ключ
    if key != RENTED_CARS_ENDPOINT_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access key")

    # 2) Быстрый sync-запрос: только нужные поля, distinct по car_id
    statuses = [RentalStatus.IN_USE, RentalStatus.DELIVERING_IN_PROGRESS]

    rows = (
        db.query(Car.name, Car.plate_number)
        .join(RentalHistory, RentalHistory.car_id == Car.id)
        .filter(RentalHistory.rental_status.in_(statuses))
        .distinct(Car.id)
        .all()
    )

    return [RentedCar(name=name, plate_number=plate) for name, plate in rows]
