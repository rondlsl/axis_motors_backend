"""
Утилиты для конвертации sid в UUID и обратно в роутерах
"""
from fastapi import Path, Query
from typing import Annotated
import uuid as uuid_lib
from app.utils.short_id import sid_to_uuid, uuid_to_sid


def sid_path_param(description: str = "Short ID") -> Annotated[str, Path(...)]:
    """
    Параметр пути для sid, который будет конвертирован в UUID
    
    Usage:
        @router.get("/user/{user_sid}")
        async def get_user(user_sid: str = sid_path_param("ID пользователя")):
            user_uuid = sid_to_uuid(user_sid)
            ...
    """
    return Path(..., description=description, example="VQ6EAOKbQdSnFkRmVUQAAA")


def sid_query_param(description: str = "Short ID", default=None) -> Annotated[str, Query(...)]:
    """
    Query параметр для sid
    
    Usage:
        @router.get("/rentals")
        async def get_rentals(user_sid: str = sid_query_param("ID пользователя")):
            if user_sid:
                user_uuid = sid_to_uuid(user_sid)
            ...
    """
    if default is None:
        return Query(..., description=description, example="VQ6EAOKbQdSnFkRmVUQAAA")
    else:
        return Query(default, description=description, example="VQ6EAOKbQdSnFkRmVUQAAA")


def convert_uuid_response_to_sid(data: dict, uuid_fields: list[str], keep_uuid_fields: list[str] = None) -> dict:
    """
    Конвертирует UUID поля в sid в ответе API
    
    Args:
        data: Словарь с данными ответа
        uuid_fields: Список полей, которые нужно конвертировать в sid
        keep_uuid_fields: Список полей, которые нужно оставить как UUID (например, для подписания договоров)
        
    Returns:
        Словарь с сконвертированными полями
        
    Example:
        response_data = {
            "id": UUID("550e8400-e29b-41d4-a716-446655440000"),
            "user_id": UUID("..."),
            "rental_id": UUID("..."),
            "signature_id": UUID("...")  # это поле нужно оставить как UUID
        }
        
        result = convert_uuid_response_to_sid(
            response_data, 
            uuid_fields=["id", "user_id", "rental_id", "signature_id"],
            keep_uuid_fields=["signature_id"]  # не конвертируем signature_id
        )
        # result = {"id": "VQ6E...", "user_id": "...", "rental_id": "...", "signature_id": UUID("...")}
    """
    if keep_uuid_fields is None:
        keep_uuid_fields = []
    
    result = data.copy()
    
    for field in uuid_fields:
        if field in result and field not in keep_uuid_fields:
            value = result[field]
            if isinstance(value, uuid_lib.UUID):
                result[field] = uuid_to_sid(value)
            elif isinstance(value, str):
                # Проверяем, является ли это строкой UUID
                try:
                    uuid_obj = uuid_lib.UUID(value)
                    result[field] = uuid_to_sid(uuid_obj)
                except (ValueError, AttributeError):
                    # Не UUID, оставляем как есть
                    pass
    
    return result


def add_sid_to_response(data: dict, id_field: str = "id", sid_field: str = "sid") -> dict:
    """
    Добавляет поле sid к ответу, оставляя оригинальный UUID
    
    Args:
        data: Словарь с данными ответа
        id_field: Название поля с UUID (по умолчанию "id")
        sid_field: Название нового поля для sid (по умолчанию "sid")
        
    Returns:
        Словарь с добавленным полем sid
        
    Example:
        response_data = {"id": UUID("550e8400-e29b-41d4-a716-446655440000"), "name": "John"}
        result = add_sid_to_response(response_data)
        # result = {"id": UUID("..."), "sid": "VQ6E...", "name": "John"}
    """
    result = data.copy()
    
    if id_field in result:
        value = result[id_field]
        if isinstance(value, uuid_lib.UUID):
            result[sid_field] = uuid_to_sid(value)
        elif isinstance(value, str):
            try:
                uuid_obj = uuid_lib.UUID(value)
                result[sid_field] = uuid_to_sid(uuid_obj)
            except (ValueError, AttributeError):
                pass
    
    return result

