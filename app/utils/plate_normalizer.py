def normalize_plate_number(plate_number: str) -> str:
    """
    Нормализует номерной знак для использования в путях к файлам
    
    Правила:
    - Убирает пробелы
    - Убирает спецсимволы
    - Оставляет только буквы и цифры
    - Приводит к верхнему регистру
    
    Args:
        plate_number: Исходный номерной знак (например: "422 ABK 02", "422-ABK-02")
    
    Returns:
        Нормализованный номер (например: "422ABK02")
    
    Examples:
        >>> normalize_plate_number("422 ABK 02")
        "422ABK02"
        >>> normalize_plate_number("422-ABK-02")
        "422ABK02"
        >>> normalize_plate_number("300MCB02")
        "300MCB02"
    """
    if not plate_number:
        raise ValueError("plate_number cannot be empty")
    
    # Убираем все кроме букв и цифр, приводим к верхнему регистру
    normalized = ''.join(c for c in plate_number if c.isalnum()).upper()
    
    if not normalized:
        raise ValueError(f"Invalid plate_number: {plate_number}")
    
    return normalized


def get_car_photos_dir(plate_number: str) -> str:
    """
    Возвращает путь к директории с фотографиями автомобиля
    
    Args:
        plate_number: Номерной знак автомобиля
    
    Returns:
        Путь к директории (например: "uploads/cars/422ABK02")
    """
    normalized = normalize_plate_number(plate_number)
    return f"uploads/cars/{normalized}"


def get_car_photo_url(plate_number: str, filename: str) -> str:
    """
    Возвращает URL к фотографии автомобиля
    
    Args:
        plate_number: Номерной знак автомобиля
        filename: Имя файла фотографии
    
    Returns:
        URL фотографии (например: "/uploads/cars/422ABK02/photo1.jpg")
    """
    normalized = normalize_plate_number(plate_number)
    return f"/uploads/cars/{normalized}/{filename}"

