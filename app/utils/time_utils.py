from datetime import datetime, timedelta


ALMATY_OFFSET = timedelta(hours=5)


def get_local_time() -> datetime:
    """
    Return naive datetime shifted to GMT+5 (Almaty time).
    """
    return datetime.utcnow() + ALMATY_OFFSET


def parse_datetime_to_local(dt_str: str) -> datetime:
    """
    Парсит ISO datetime строку и преобразует в UTC+5 (локальное время для базы данных).
    
    Если время приходит в UTC (с "Z"), преобразует его в UTC+5 (добавляет 5 часов).
    Если время приходит с timezone offset, конвертирует в UTC+5.
    Возвращает наивное datetime (без timezone) в UTC+5.
    
    :param dt_str: ISO datetime строка (например, "2026-01-20T15:58:00.000Z")
    :return: datetime в UTC+5 (наивное, без timezone)
    """
    if not dt_str:
        raise ValueError("Empty datetime string")
    
    dt_str = dt_str.strip()
    
    # Если время приходит в UTC (с "Z"), парсим как UTC и добавляем 5 часов
    if dt_str.upper().endswith("Z"):
        # Заменяем "Z" на "+00:00" для правильного парсинга timezone
        dt_str_normalized = dt_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(dt_str_normalized)
        # Преобразуем в UTC (наивное) и добавляем 5 часов
        offset = dt.tzinfo.utcoffset(dt) if dt.tzinfo else timedelta(0)
        dt_utc = (dt - offset).replace(tzinfo=None)
        return dt_utc + timedelta(hours=5)
    
    # Если есть timezone offset, парсим и конвертируем
    try:
        # Пробуем парсить с timezone (заменяем "Z" на "+00:00" если есть)
        normalized = dt_str.replace("Z", "+00:00") if "Z" in dt_str.upper() else dt_str
        dt = datetime.fromisoformat(normalized)
        
        if dt.tzinfo is not None:
            # Получаем UTC offset
            offset = dt.tzinfo.utcoffset(dt)
            if offset is None:
                offset = timedelta(0)
            
            # Преобразуем в UTC (наивное время)
            dt_utc = (dt - offset).replace(tzinfo=None)
            
            # Добавляем 5 часов для получения UTC+5
            return dt_utc + timedelta(hours=5)
        else:
            # Если timezone info нет после парсинга, считаем что это уже UTC+5
            return dt
    except ValueError:
        # Если не удалось распарсить, пробуем без timezone (считаем что это уже UTC+5)
        # Убираем timezone часть если есть
        dt_str_clean = dt_str.split("+")[0]
        if dt_str_clean.count("-") > 2 and "T" in dt_str_clean:
            # Есть timezone offset в формате -05:00
            parts = dt_str_clean.rsplit("-", 1)
            if len(parts) == 2 and ":" in parts[1]:
                dt_str_clean = parts[0]
        
        # Убираем миллисекунды если есть
        if "." in dt_str_clean:
            dt_str_clean = dt_str_clean.split(".")[0]
        
        try:
            return datetime.fromisoformat(dt_str_clean)
        except ValueError:
            raise ValueError(f"Не удалось распарсить дату: {dt_str}")

