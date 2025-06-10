from datetime import datetime

from pydantic import BaseModel, Field, validator


class SendSmsRequest(BaseModel):
    phone_number: str


class VerifySmsRequest(BaseModel):
    phone_number: str = Field()
    sms_code: str = Field()


class DocumentUploadRequest(BaseModel):
    full_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Полное имя пользователя. Пример: 'Иванов Иван Иванович'"
    )
    birth_date: str = Field(
        ...,
        description="Дата рождения в формате YYYY-MM-DD. Пример: '1990-05-15'"
    )
    iin: str = Field(
        ...,
        min_length=12,
        max_length=12,
        description="ИИН - 12 цифр подряд без пробелов и дефисов. Пример: '900515123456'"
    )
    id_card_expiry: str = Field(
        ...,
        description="Дата окончания действия ID карты в формате YYYY-MM-DD. Должна быть в будущем. Пример: '2030-12-31'"
    )
    drivers_license_expiry: str = Field(
        ...,
        description="Дата окончания действия водительских прав в формате YYYY-MM-DD. Должна быть в будущем. Пример: '2029-08-20'"
    )

    @validator('iin')
    def validate_iin(cls, v):
        if not v.isdigit():
            raise ValueError('ИИН должен содержать только цифры. Пример: 900515123456')
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
