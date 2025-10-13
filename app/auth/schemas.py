from datetime import datetime
import uuid

from pydantic import BaseModel, Field, validator, constr


class LocaleUpdate(BaseModel):
    locale: str


class SelfieUploadResponse(BaseModel):
    message: str = Field(..., description="Сообщение об успешной загрузке")
    selfie_url: str = Field(..., description="URL загруженного селфи")
    user_id: uuid.UUID = Field(..., description="ID пользователя")


class SendSmsRequest(BaseModel):
    phone_number: constr(min_length=11, max_length=11)
    first_name: str = Field(
        None,
        min_length=1,
        max_length=50,
        description="Имя пользователя (обязательно только для новых пользователей). Пример: 'Иван'"
    )
    last_name: str = Field(
        None,
        min_length=1,
        max_length=50,
        description="Фамилия пользователя (обязательно только для новых пользователей). Пример: 'Иванов'"
    )


class VerifySmsRequest(BaseModel):
    phone_number: constr(min_length=11, max_length=11)
    sms_code: constr(min_length=4, max_length=4)


class DocumentUploadRequest(BaseModel):
    first_name: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Имя пользователя. Пример: 'Иван'"
    )
    last_name: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Фамилия пользователя. Пример: 'Иванов'"
    )
    birth_date: str = Field(
        ...,
        description="Дата рождения в формате YYYY-MM-DD. Пример: '1990-05-15'"
    )
    iin: str | None = Field(
        None,
        min_length=12,
        max_length=12,
        description="ИИН - 12 цифр подряд без пробелов и дефисов. Пример: '900515123456'"
    )
    passport_number: str | None = Field(
        None,
        min_length=3,
        max_length=50,
        description="Номер паспорта. Можно указать вместо ИИН"
    )
    id_card_expiry: str = Field(
        ...,
        description="Дата окончания действия ID карты в формате YYYY-MM-DD. Должна быть в будущем. Пример: '2030-12-31'"
    )
    drivers_license_expiry: str = Field(
        ...,
        description="Дата окончания действия водительских прав в формате YYYY-MM-DD. Должна быть в будущем. Пример: '2029-08-20'"
    )
    is_citizen_kz: bool = Field(
        default=False,
        description="Гражданин Республики Казахстан. Если true, то обязательны справки"
    )

    @validator('iin', pre=True)
    def normalize_iin(cls, v):
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return None
        return v

    @validator('iin')
    def validate_iin(cls, v):
        if v is None:
            return v
        if not v.isdigit():
            raise ValueError('ИИН должен содержать только цифры. Пример: 900515123456')
        return v

    @validator('passport_number', pre=True)
    def normalize_passport(cls, v):
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return None
        return v

    @validator('passport_number')
    def validate_passport(cls, v, values):
        # Разрешаем либо ИИН, либо паспорт. Если оба пустые — ошибка
        if v is None and not values.get('iin'):
            raise ValueError('Нужно указать либо ИИН, либо номер паспорта')
        return v

    @validator('birth_date', 'id_card_expiry', 'drivers_license_expiry')
    def validate_date_format(cls, v):
        try:
            datetime.strptime(v, '%Y-%m-%d')
            return v
        except ValueError:
            raise ValueError('Дата должна быть в формате YYYY-MM-DD. Пример: 1990-05-15')

    @validator('birth_date')
    def validate_birth_date(cls, v):
        try:
            birth_date = datetime.strptime(v, '%Y-%m-%d')
            if birth_date >= datetime.now():
                raise ValueError('Дата рождения не может быть в будущем. Используйте формат YYYY-MM-DD')
            if birth_date.year < 1900:
                raise ValueError('Некорректная дата рождения. Год должен быть больше 1900')
            # Проверка возраста (должен быть минимум 18 лет)
            age = (datetime.now() - birth_date).days // 365
            if age < 18:
                raise ValueError('Возраст должен быть не менее 18 лет')
            return v
        except ValueError as e:
            if "does not match format" in str(e):
                raise ValueError('Дата должна быть в формате YYYY-MM-DD. Пример: 1990-05-15')
            raise e

    @validator('id_card_expiry', 'drivers_license_expiry')
    def validate_expiry_dates(cls, v):
        try:
            expiry_date = datetime.strptime(v, '%Y-%m-%d')
            if expiry_date <= datetime.now():
                raise ValueError('Дата окончания документа должна быть в будущем. Пример: 2030-12-31')
            return v
        except ValueError as e:
            if "does not match format" in str(e):
                raise ValueError('Дата должна быть в формате YYYY-MM-DD. Пример: 2030-12-31')
            raise e
