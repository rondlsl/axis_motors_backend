from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import or_


def _clip_overlap_seconds(
        start: Optional[datetime],
        end: Optional[datetime],
        window_start: datetime,
        window_end: datetime
) -> int:
    """
    Возвращает число секунд пересечения отрезка [start, end] с окном [window_start, window_end].
    Если end is None — считаем до window_end.
    Если start is None — возвращаем 0 (для корректности).
    """
    if start is None:
        return 0
    if end is None:
        end = window_end
    # нормируем к окну
    s = max(start, window_start)
    e = min(end, window_end)
    if e <= s:
        return 0
    return int((e - s).total_seconds())


def merge_overlapping_intervals(intervals: List[Tuple[datetime, Optional[datetime]]], window_end: datetime) -> List[Tuple[datetime, datetime]]:
    """
    Объединяет перекрывающиеся интервалы времени для корректного подсчета общего времени недоступности.
    
    Args:
        intervals: список кортежей (start_time, end_time), где end_time может быть None
        window_end: конец расчетного окна (для интервалов с end_time=None)
    
    Returns:
        список неперекрывающихся интервалов (start_time, end_time)
    """
    if not intervals:
        return []
    
    # Преобразуем None в window_end и сортируем по началу
    normalized_intervals = []
    for start, end in intervals:
        if start is None:
            continue
        end_time = end if end is not None else window_end
        normalized_intervals.append((start, end_time))
    
    if not normalized_intervals:
        return []
    
    # Сортируем по времени начала
    normalized_intervals.sort(key=lambda x: x[0])
    
    merged = [normalized_intervals[0]]
    
    for current_start, current_end in normalized_intervals[1:]:
        last_start, last_end = merged[-1]
        
        # Если интервалы перекрываются или касаются
        if current_start <= last_end:
            # Объединяем интервалы
            merged[-1] = (last_start, max(last_end, current_end))
        else:
            # Интервалы не перекрываются
            merged.append((current_start, current_end))
    
    return merged


def calculate_total_unavailable_seconds(intervals: List[Tuple[datetime, Optional[datetime]]], 
                                      window_start: datetime, 
                                      window_end: datetime) -> int:
    """
    Вычисляет общее количество секунд недоступности с учетом перекрывающихся интервалов.
    
    Args:
        intervals: список интервалов недоступности (start_time, end_time)
        window_start: начало расчетного окна
        window_end: конец расчетного окна
    
    Returns:
        общее количество секунд недоступности
    """
    # Объединяем перекрывающиеся интервалы
    merged_intervals = merge_overlapping_intervals(intervals, window_end)
    
    total_seconds = 0
    for start, end in merged_intervals:
        # Обрезаем интервал по границам окна
        clipped_start = max(start, window_start)
        clipped_end = min(end, window_end)
        
        if clipped_end > clipped_start:
            total_seconds += int((clipped_end - clipped_start).total_seconds())
    
    return total_seconds


def calculate_month_availability_minutes(
    car_id: int,
    year: int,
    month: int,
    owner_id: int,
    db: Session
) -> int:
    """
    Рассчитывает количество минут в указанном месяце, когда автомобиль был доступен для аренды клиентами.
    
    Логика расчета:
    - Общее время месяца МИНУС время использования владельца = время доступности
    - Время когда машина свободна = доступна для аренды
    - Время когда клиенты арендуют = тоже доступна для аренды (уже арендована клиентами)
    - Время когда владелец арендует = НЕ доступна для аренды
    
    Args:
        car_id: ID автомобиля
        year: Год
        month: Месяц (1-12)
        owner_id: ID владельца автомобиля
        db: Сессия базы данных
    
    Returns:
        Количество минут доступности для клиентов
    """
    from app.models.history_model import RentalHistory, RentalStatus
    
    # Определяем границы месяца
    month_start = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
    
    # Определяем конец месяца
    if month == 12:
        month_end = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    else:
        month_end = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    
    # Если это текущий месяц, используем текущее время как конец периода
    now = datetime.now(timezone.utc)
    if year == now.year and month == now.month:
        calculation_end = now
    else:
        calculation_end = month_end
    
    print(f"[MONTH CALC DEBUG] Расчет для автомобиля ID:{car_id}, период: {month_start} - {calculation_end}")
    
    # Получаем все аренды для этого автомобиля в указанном месяце
    # Исключаем CANCELLED (отмененные аренды не влияют на доступность)
    all_rentals = (
        db.query(RentalHistory)
        .filter(
            RentalHistory.car_id == car_id,
            RentalHistory.rental_status != RentalStatus.CANCELLED,
            RentalHistory.reservation_time < calculation_end,
            or_(RentalHistory.end_time == None, RentalHistory.end_time > month_start),
        )
        .all()
    )
    
    print(f"[MONTH CALC DEBUG] Найдено аренд в месяце: {len(all_rentals)}")
    
    # Собираем ТОЛЬКО интервалы аренд владельца (они делают машину недоступной для клиентов)
    # Аренды клиентов - это время когда машина доступна для аренды (просто уже арендована)
    owner_unavailable_intervals = []
    for rental in all_rentals:
        user_type = "владелец" if rental.user_id == owner_id else "клиент"
        print(f"[MONTH CALC DEBUG]   Аренда ID:{rental.id}, {user_type}, {rental.reservation_time} - {rental.end_time}, статус: {rental.rental_status.value}")
        
        # Добавляем в недоступность только аренды владельца
        if rental.user_id == owner_id:
            start_ts = rental.reservation_time
            end_ts = rental.end_time
            owner_unavailable_intervals.append((start_ts, end_ts))
            print(f"[MONTH CALC DEBUG]     -> Учитывается как недоступность (аренда владельца)")
        else:
            print(f"[MONTH CALC DEBUG]     -> НЕ учитывается (аренда клиента = доступность)")
    
    # Вычисляем время недоступности только для аренд владельца
    unavailable_seconds = calculate_total_unavailable_seconds(
        owner_unavailable_intervals, month_start, calculation_end
    )
    
    # Общее время периода в секундах
    total_period_seconds = int((calculation_end - month_start).total_seconds())
    
    # Время доступности = общее время - время недоступности
    available_seconds = max(0, total_period_seconds - unavailable_seconds)
    
    # Переводим в минуты
    available_minutes = available_seconds // 60
    
    print(f"[MONTH CALC DEBUG] Общее время периода: {total_period_seconds/3600:.1f} часов")
    print(f"[MONTH CALC DEBUG] Время недоступности: {unavailable_seconds/3600:.1f} часов")
    print(f"[MONTH CALC DEBUG] Время доступности: {available_seconds/3600:.1f} часов ({available_minutes} минут)")
    
    return available_minutes
