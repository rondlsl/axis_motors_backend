"""
Переводы заголовков для экспорта в Excel
"""

EXCEL_HEADERS_TRANSLATIONS = {
    "ru": {
        "id": "ID",
        "created_at": "Дата создания",
        "type": "Тип транзакции",
        "amount": "Сумма",
        "balance_before": "Баланс до",
        "balance_after": "Баланс после",
        "related_rental_id": "ID аренды",
        "tracking_id": "ID отслеживания",
        "description": "Описание"
    },
    "en": {
        "id": "ID",
        "created_at": "Created At",
        "type": "Transaction Type",
        "amount": "Amount",
        "balance_before": "Balance Before",
        "balance_after": "Balance After",
        "related_rental_id": "Rental ID",
        "tracking_id": "Tracking ID",
        "description": "Description"
    },
    "kz": {
        "id": "ID",
        "created_at": "Жасалған күні",
        "type": "Транзакция түрі",
        "amount": "Сома",
        "balance_before": "Алдындағы баланс",
        "balance_after": "Кейінгі баланс",
        "related_rental_id": "Жалға алу ID",
        "tracking_id": "Бақылау ID",
        "description": "Сипаттама"
    }
}


def get_excel_headers(locale: str = "ru") -> dict:
    """
    Получить переведенные заголовки для Excel
    
    Args:
        locale: Язык пользователя (ru/en/kz)
        
    Returns:
        dict: Словарь с переведенными заголовками
    """
    if locale not in EXCEL_HEADERS_TRANSLATIONS:
        locale = "ru"
    
    return EXCEL_HEADERS_TRANSLATIONS[locale]


def get_excel_header_row(locale: str = "ru") -> str:
    """
    Получить строку заголовков для CSV/Excel
    
    Args:
        locale: Язык пользователя (ru/en/kz)
        
    Returns:
        str: Строка заголовков, разделенная запятыми
    """
    headers = get_excel_headers(locale)
    # Экранируем запятые в заголовках, если они есть
    header_values = [
        headers['id'],
        headers['created_at'],
        headers['type'],
        headers['amount'],
        headers['balance_before'],
        headers['balance_after'],
        headers['related_rental_id'],
        headers['tracking_id'],
        headers['description']
    ]
    return ",".join(header_values) + "\n"

