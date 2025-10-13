"""
Базовые схемы для использования sid вместо UUID
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional
import uuid as uuid_lib
from app.utils.short_id import sid_to_uuid, uuid_to_sid


class SidMixin(BaseModel):
    """
    Миксин для схем, которые должны использовать sid вместо UUID
    """
    
    @classmethod
    def from_orm_with_sid(cls, obj):
        """
        Создает схему из ORM объекта, преобразуя UUID в sid
        """
        data = {}
        for field_name, field_info in cls.model_fields.items():
            if hasattr(obj, field_name):
                value = getattr(obj, field_name)
                
                # Если поле называется id и объект имеет свойство sid, используем sid
                if field_name == "id" and hasattr(obj, 'sid'):
                    data["id"] = obj.sid
                # Если это UUID, конвертируем в sid
                elif isinstance(value, uuid_lib.UUID):
                    data[field_name] = uuid_to_sid(value)
                else:
                    data[field_name] = value
            # Если поле не найдено в объекте, пробуем использовать значение по умолчанию
            elif field_name in cls.model_fields and cls.model_fields[field_name].default is not None:
                data[field_name] = cls.model_fields[field_name].default
        
        return cls(**data)


class SidField(str):
    """
    Тип поля для sid - принимает sid и может конвертировать в UUID
    """
    
    @classmethod
    def __get_validators__(cls):
        yield cls.validate
    
    @classmethod
    def validate(cls, v):
        if isinstance(v, str):
            # Проверяем что это валидный sid, пытаясь его декодировать
            try:
                sid_to_uuid(v)
                return v
            except Exception:
                raise ValueError(f"Invalid sid format: {v}")
        elif isinstance(v, uuid_lib.UUID):
            # Если передан UUID, конвертируем в sid
            return uuid_to_sid(v)
        else:
            raise ValueError(f"sid must be a string or UUID, got {type(v)}")
    
    def to_uuid(self) -> uuid_lib.UUID:
        """Конвертирует sid обратно в UUID"""
        return sid_to_uuid(self)

