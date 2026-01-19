"""
Router для работы с пользователями для бухгалтеров
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from math import ceil, floor
from datetime import datetime
from collections import defaultdict

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_accountant
from app.models.user_model import User
from app.models.wallet_transaction_model import WalletTransaction
from app.models.history_model import RentalHistory
from app.models.car_model import Car, CarBodyType
from app.utils.short_id import uuid_to_sid, safe_sid_to_uuid
from app.admin.users.schemas import (
    WalletTransactionSchema, 
    WalletTransactionPaginationSchema,
    GroupedTransactionsPaginationSchema,
    GroupedTransactionItemSchema
)
from app.rent.utils.calculate_price import FUEL_PRICE_PER_LITER, ELECTRIC_FUEL_PRICE_PER_LITER
from app.admin.cars.utils import sort_car_photos

accountant_users_router = APIRouter(tags=["Accountant Users"])


@accountant_users_router.get("/users/{user_id}/transactions", response_model=WalletTransactionPaginationSchema)
async def get_user_transactions(
    user_id: str,
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(20, ge=1, le=100, description="Количество элементов на странице"),
    current_user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db)
):
    """
    Получение истории транзакций пользователя для бухгалтеров
    """
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
        
    query = db.query(WalletTransaction).filter(WalletTransaction.user_id == user.id)
    
    query = query.order_by(desc(WalletTransaction.created_at), desc(WalletTransaction.id))
    
    total_count = query.count()
    transactions = query.offset((page - 1) * limit).limit(limit).all()
    
    items = []
    for tx in transactions:
        tx_data = {
            "id": uuid_to_sid(tx.id),
            "amount": float(tx.amount),
            "transaction_type": tx.transaction_type.value if hasattr(tx.transaction_type, "value") else str(tx.transaction_type),
            "description": tx.description,
            "balance_before": float(tx.balance_before),
            "balance_after": float(tx.balance_after),
            "tracking_id": tx.tracking_id,
            "created_at": tx.created_at,
            "related_rental_id": uuid_to_sid(tx.related_rental_id) if tx.related_rental_id else None
        }
        items.append(WalletTransactionSchema(**tx_data))
        
    return {
        "items": items,
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": ceil(total_count / limit) if limit > 0 else 0,
        "wallet_balance": float(user.wallet_balance) if user.wallet_balance else 0.0
    }


@accountant_users_router.get("/users/{user_id}/transactions-grouped", response_model=GroupedTransactionsPaginationSchema)
async def get_user_transactions_grouped(
    user_id: str,
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(50, ge=1, le=200, description="Количество элементов на странице"),
    current_user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db)
):
    """
    Получение истории транзакций пользователя с группировкой по аренде для бухгалтеров.
    
    Транзакции с одинаковым rental_id группируются в одну аренду (как в /admin/rentals/completed),
    а транзакции без rental_id или с уникальным rental_id показываются отдельно.
    """
    user_uuid = safe_sid_to_uuid(user_id)
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Получаем все транзакции пользователя с сортировкой по created_at и id для стабильности
    all_transactions = (
        db.query(WalletTransaction)
        .filter(WalletTransaction.user_id == user.id)
        .order_by(desc(WalletTransaction.created_at), desc(WalletTransaction.id))
        .all()
    )
    
    # Получаем все аренды пользователя
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
        
        # Определяем временной диапазон аренды
        start_bound = rental.reservation_time if rental.reservation_time else rental.start_time
        end_bound = rental.end_time
        
        if start_bound and end_bound:
            # Ищем транзакции в этом диапазоне
            transactions_in_range = []
            for tx in standalone_transactions:
                if tx.created_at and start_bound <= tx.created_at <= end_bound:
                    transactions_in_range.append(tx)
            
            # Если есть транзакции в диапазоне
            if transactions_in_range:
                # Если у аренды уже есть транзакции, проверяем цепочку балансов
                if rental_transactions[rental.id]:
                    all_rental_txs = list(rental_transactions[rental.id])
                    
                    for tx in transactions_in_range:
                        # Проверяем, вписывается ли транзакция в цепочку балансов
                        can_add = False
                        
                        # Проверяем наличие balance_before и balance_after
                        if tx.balance_before is None or tx.balance_after is None:
                            continue
                        
                        # Ищем место, куда можно вставить транзакцию
                        for i, existing_tx in enumerate(all_rental_txs):
                            if existing_tx.balance_before is None or existing_tx.balance_after is None:
                                continue
                            
                            # Проверяем, может ли tx идти перед existing_tx
                            if tx.created_at and existing_tx.created_at and tx.created_at <= existing_tx.created_at:
                                if i == 0:
                                    # tx будет первой - проверяем только balance_after tx == balance_before existing_tx
                                    if abs(float(tx.balance_after) - float(existing_tx.balance_before)) < 0.01:
                                        can_add = True
                                        break
                                else:
                                    # tx между предыдущей и текущей
                                    prev_tx = all_rental_txs[i - 1]
                                    if prev_tx.balance_after is not None and prev_tx.balance_before is not None:
                                        if (abs(float(prev_tx.balance_after) - float(tx.balance_before)) < 0.01 and 
                                            abs(float(tx.balance_after) - float(existing_tx.balance_before)) < 0.01):
                                            can_add = True
                                            break
                        
                        # Или tx может быть последней
                        if not can_add and all_rental_txs:
                            last_tx = all_rental_txs[-1]
                            if (last_tx.balance_after is not None and 
                                tx.created_at and last_tx.created_at and 
                                tx.created_at >= last_tx.created_at):
                                if abs(float(last_tx.balance_after) - float(tx.balance_before)) < 0.01:
                                    can_add = True
                        
                        # Если транзакция вписывается в цепочку, добавляем её
                        if can_add:
                            rental_transactions[rental.id].append(tx)
                            all_rental_txs = list(rental_transactions[rental.id])
    
    # Убираем из standalone те транзакции, которые были добавлены к арендам
    used_tx_ids = set()
    for transactions in rental_transactions.values():
        for tx in transactions:
            used_tx_ids.add(tx.id)
    
    standalone_transactions = [tx for tx in standalone_transactions if tx.id not in used_tx_ids]
    
    # Создаем список всех элементов (аренды и отдельные транзакции)
    all_items = []
    
    # Добавляем аренды
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
            
            # Рассчитываем fuel_fee
            fuel_fee = 0
            if rental.fuel_before is not None and rental.fuel_after is not None:
                if rental.fuel_after < rental.fuel_before:
                    fuel_consumed = ceil(rental.fuel_before) - floor(rental.fuel_after)
                    if fuel_consumed > 0 and car:
                        fuel_price = ELECTRIC_FUEL_PRICE_PER_LITER if car.body_type == CarBodyType.ELECTRIC else FUEL_PRICE_PER_LITER
                        fuel_fee = int(fuel_consumed * fuel_price)
            
            # Рассчитываем total_price_without_fuel
            total_price_without_fuel = (
                (rental.base_price or 0) +
                (rental.open_fee or 0) +
                (rental.delivery_fee or 0) +
                (rental.waiting_fee or 0) +
                (rental.overtime_fee or 0) +
                (rental.distance_fee or 0) +
                (rental.driver_fee or 0)
            )
            
            # Строим информацию о машине
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
            
            # Строим информацию об арендаторе
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
                    "is_owner": is_owner
                }
            
            # Получаем tariff_display
            tariff_value = rental.rental_type.value if hasattr(rental.rental_type, 'value') else str(rental.rental_type)
            tariff_map = {
                "minutes": "Минутный",
                "hours": "Часовой",
                "days": "Суточный"
            }
            tariff_display = tariff_map.get(tariff_value, tariff_value)
            
            # Рассчитываем заработок владельца
            base_price_owner = int((rental.base_price or 0) * 0.5 * 0.97)
            waiting_fee_owner = int((rental.waiting_fee or 0) * 0.5 * 0.97)
            overtime_fee_owner = int((rental.overtime_fee or 0) * 0.5 * 0.97)
            total_owner_earnings = int(((rental.base_price or 0) + (rental.waiting_fee or 0) + (rental.overtime_fee or 0)) * 0.5 * 0.97)
            
            # Строим список транзакций с правильной сортировкой по created_at и id
            transactions_list = []
            sorted_transactions = sorted(
                transactions, 
                key=lambda x: (x.created_at or datetime.min, x.id or '')
            )
            for tx in sorted_transactions:
                transactions_list.append({
                    "id": uuid_to_sid(tx.id),
                    "amount": float(tx.amount),
                    "transaction_type": tx.transaction_type.value if hasattr(tx.transaction_type, 'value') else str(tx.transaction_type),
                    "description": tx.description,
                    "balance_before": float(tx.balance_before),
                    "balance_after": float(tx.balance_after),
                    "tracking_id": tx.tracking_id,
                    "created_at": tx.created_at.isoformat() if tx.created_at else None,
                    "related_rental_id": uuid_to_sid(tx.related_rental_id) if tx.related_rental_id else None,
                })
            
            # Получаем balance_before из первой транзакции и balance_after из последней
            first_tx = sorted_transactions[0] if sorted_transactions else None
            last_tx = sorted_transactions[-1] if sorted_transactions else None
            rental_balance_before = float(first_tx.balance_before) if first_tx and first_tx.balance_before is not None else 0.0
            rental_balance_after = float(last_tx.balance_after) if last_tx and last_tx.balance_after is not None else 0.0
            
            # Формируем объект аренды
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
            
            # Используем самую раннюю дату транзакции аренды для сортировки
            # Если нет транзакций, используем reservation_time или start_time аренды
            # Сортируем по created_at и id для стабильности при одинаковых временах
            if transactions:
                earliest_tx = min(
                    transactions, 
                    key=lambda x: (x.created_at or datetime.max, x.id or '')
                )
                sort_date = earliest_tx.created_at
            else:
                sort_date = rental.reservation_time if rental.reservation_time else rental.start_time
            
            all_items.append({
                "type": "rental",
                "created_at": sort_date,
                "rental": rental_data,
                "transaction": None,
                "sort_id": rental.id
            })
    
    # Добавляем отдельные транзакции
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
            "related_rental_id": uuid_to_sid(tx.related_rental_id) if tx.related_rental_id else None
        }
        all_items.append({
            "type": "transaction",
            "created_at": tx.created_at,
            "transaction": WalletTransactionSchema(**tx_data),
            "rental": None,
            "sort_id": tx.id
        })
    
    # Сортируем все элементы по дате (самые новые сначала) с учетом id для стабильности
    # Используем кортеж (created_at, sort_id) для стабильной сортировки при одинаковых временах
    all_items.sort(key=lambda x: (
        x["created_at"] if x["created_at"] else datetime.min,
        x.get("sort_id", "")
    ), reverse=True)
    
    # Применяем пагинацию
    total_count = len(all_items)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated_items = all_items[start_idx:end_idx]
    
    # Формируем финальный список (удаляем sort_id перед созданием схемы)
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
        "wallet_balance": float(user.wallet_balance) if user.wallet_balance else 0.0
    }
