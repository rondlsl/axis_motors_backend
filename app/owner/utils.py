from datetime import datetime
from typing import Optional


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
