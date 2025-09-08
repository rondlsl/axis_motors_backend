# Пошаговая инструкция по генерации Swagger документации

## 1. Установка зависимостей
Убедитесь, что у вас установлены все необходимые зависимости. FastAPI автоматически генерирует Swagger документацию.

```bash
pip install fastapi uvicorn
```

## 2. Запуск приложения
Запустите приложение одним из способов:

### Способ 1: Через uvicorn напрямую
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Способ 2: Через Python
```bash
python -m uvicorn main:app --reload
```

### Способ 3: Через Docker (если настроен)
```bash
docker-compose up
```

## 3. Доступ к Swagger документации

После запуска приложения, Swagger документация будет доступна по следующим адресам:

### Swagger UI (интерактивная документация)
```
http://localhost:8000/docs
```

### ReDoc (альтернативная документация)
```
http://localhost:8000/redoc
```

### OpenAPI JSON схема
```
http://localhost:8000/openapi.json
```

## 4. Структура Swagger документации

В Swagger UI вы увидите следующие разделы:

### Auth - Аутентификация
- `POST /auth/send_sms/` - Отправка SMS кода
- `POST /auth/verify_sms/` - Верификация SMS кода
- `GET /auth/user/me` - Получение информации о пользователе
- `POST /auth/upload-documents/` - Загрузка документов
- И другие эндпоинты авторизации...

### Guarantor - Функционал гарантов
- `GET /guarantor/info` - Информация о функции гаранта
- `POST /guarantor/request` - Создание заявки на гаранта
- `POST /guarantor/respond/{request_id}` - Ответ на заявку гаранта
- `GET /guarantor/my-info` - Информация о гарантах пользователя
- `POST /guarantor/sign-contract` - Подписание договора
- `POST /guarantor/check-user-eligibility` - Проверка платежеспособности
- `GET /guarantor/contracts` - Получение списка договоров
- `POST /guarantor/upload-contract/{contract_type}` - Загрузка договоров (админ)

### Admin - Административные функции
- `GET /admin/pending-users` - Пользователи, ожидающие одобрения
- `POST /admin/approve-user` - Одобрение/отклонение пользователя
- `GET /admin/users` - Список всех пользователей

### Другие разделы
- **Vehicle** - Работа с автомобилями
- **Rent** - Аренда
- **Mechanic** - Механики
- **Owner** - Владельцы
- **Push** - Push уведомления

## 5. Тестирование API через Swagger

### Шаг 1: Аутентификация
1. Перейдите в раздел **Auth**
2. Выполните `POST /auth/send_sms/` с вашим номером телефона
3. Выполните `POST /auth/verify_sms/` с полученным кодом (или используйте "6666" для тестирования)
4. Скопируйте `access_token` из ответа

### Шаг 2: Авторизация в Swagger
1. Нажмите кнопку **Authorize** в правом верхнем углу Swagger UI
2. В поле **Value** введите: `Bearer YOUR_ACCESS_TOKEN`
3. Нажмите **Authorize**

### Шаг 3: Тестирование эндпоинтов гарантов
После авторизации вы можете тестировать все эндпоинты:

1. **Создание заявки на гаранта:**
   ```json
   {
     "guarantor_info": {
       "full_name": "Тестов Тест Тестович",
       "phone_number": "77001234567"
     },
     "reason": "Тестовая заявка"
   }
   ```

2. **Проверка платежеспособности:**
   ```json
   {
     "phone_number": "77001234567"
   }
   ```

## 6. Особенности тестирования

### SMS уведомления
- Для тестирования установите `SMS_TOKEN=6666` в переменных окружения
- SMS будут выводиться в консоль вместо отправки

### Тестовый SMS код
- Используйте код "6666" для быстрой авторизации в тестовом режиме

### Административные функции
- Для тестирования админских функций создайте пользователя с ролью `ADMIN`

## 7. Экспорт документации

### Сохранение OpenAPI схемы
```bash
curl http://localhost:8000/openapi.json > api_schema.json
```

### Генерация клиентского кода
Используйте OpenAPI Generator для создания клиентов на различных языках:

```bash
# Установка openapi-generator
npm install @openapitools/openapi-generator-cli -g

# Генерация клиента для JavaScript
openapi-generator-cli generate -i http://localhost:8000/openapi.json -g javascript -o ./client-js

# Генерация клиента для Python
openapi-generator-cli generate -i http://localhost:8000/openapi.json -g python -o ./client-python
```

## 8. Настройка документации

### Изменение заголовка и описания
В `main.py` можно настроить мета-информацию:

```python
app = FastAPI(
    title="AZV Motors API with Guarantor System",
    description="API для приложения AZV Motors с функционалом гарантов",
    version="1.0.0",
    contact={
        "name": "AZV Motors",
        "email": "support@azvmotors.kz",
    },
)
```

## 9. Решение проблем

### Документация не отображается
- Проверьте, что приложение запущено
- Убедитесь, что порт 8000 доступен
- Проверьте консоль на наличие ошибок

### Эндпоинты не отображаются
- Убедитесь, что все роутеры подключены в `main.py`
- Проверьте корректность импортов

### Ошибки в схемах
- Проверьте Pydantic модели в `schemas.py`
- Убедитесь в корректности типов данных

## 10. Дополнительные возможности

### Группировка эндпоинтов
Эндпоинты автоматически группируются по тегам, указанным в роутерах:
```python
guarantor_router = APIRouter(prefix="/guarantor", tags=["Guarantor"])
```

### Детальное описание эндпоинтов
Добавьте описания к функциям для более подробной документации:
```python
@guarantor_router.post("/request", 
                      summary="Создание заявки на гаранта",
                      description="Подробное описание эндпоинта...")
```
