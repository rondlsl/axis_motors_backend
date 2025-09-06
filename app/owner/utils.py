from datetime import datetime
from typing import Optional, List, Tuple


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
