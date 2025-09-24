# API для управления автомобилями в админ-панели

## Обзор

Данный документ описывает новые API эндпоинты для управления автомобилями в админ-панели согласно структуре "Управление автомобилями".

## Авторизация

Все эндпоинты требуют авторизации и доступны только для пользователей с ролью `ADMIN` или `SUPPORT` (в зависимости от эндпоинта).

## Эндпоинты

### 1. Получение списка автомобилей с фильтрацией

**GET** `/admin/cars/list`

Получение списка всех автомобилей с возможностью фильтрации по различным параметрам.

#### Параметры запроса:
- `status` (optional) - Фильтр по статусу автомобиля
  - Возможные значения: `FREE`, `IN_USE`, `MAINTENANCE`, `DELIVERING`, `OWNER`, `RETURNING`, `DELIVERED`, `RETURNED`
- `search` (optional) - Поиск по госномеру и марке автомобиля
- `owner_id` (optional) - Фильтр по ID владельца
- `auto_class` (optional) - Фильтр по классу автомобиля (`A`, `B`, `C`)

#### Пример запроса:
```
GET /admin/cars/list?status=IN_USE&search=ABC123
```

#### Ответ:
```json
{
  "cars": [
    {
      "id": 1,
      "name": "Toyota Camry",
      "plate_number": "ABC123",
      "status": "IN_USE",
      "status_display": "В аренде",
      "latitude": 40.7128,
      "longitude": -74.0060,
      "fuel_level": 75.5,
      "mileage": 50000,
      "auto_class": "A",
      "body_type": "SEDAN",
      "year": 2020,
      "owner_name": "Иван Иванов",
      "current_renter_name": "Петр Петров",
      "photos": ["photo1.jpg", "photo2.jpg"]
    }
  ],
  "total_count": 100,
  "filtered_count": 1
}
```

### 2. Получение данных автомобилей для карты

**GET** `/admin/cars/map`

Получение данных всех автомобилей для отображения на карте админ-панели.

#### Ответ:
```json
{
  "cars": [
    {
      "id": 1,
      "name": "Toyota Camry",
      "plate_number": "ABC123",
      "status": "FREE",
      "status_display": "Свободно",
      "latitude": 40.7128,
      "longitude": -74.0060,
      "fuel_level": 75.5,
      "course": 90,
      "photos": ["photo1.jpg"],
      "current_renter": {
        "id": 123,
        "first_name": "Петр",
        "last_name": "Петров",
        "phone_number": "+1234567890",
        "selfie": "selfie_url"
      }
    }
  ],
  "total_count": 100
}
```

### 3. Обновление статуса автомобиля

**POST** `/admin/cars/{car_id}/status`

Обновление статуса автомобиля. Доступно только для `ADMIN` и `SUPPORT`.

#### Параметры пути:
- `car_id` - ID автомобиля

#### Тело запроса:
```json
{
  "status": "MAINTENANCE",
  "reason": "Плановое техническое обслуживание"
}
```

#### Ответ:
```json
{
  "message": "Статус автомобиля ABC123 изменен с 'FREE' на 'MAINTENANCE'",
  "car_id": 1,
  "old_status": "FREE",
  "new_status": "MAINTENANCE",
  "reason": "Плановое техническое обслуживание"
}
```

### 4. Поиск автомобилей

**GET** `/admin/cars/search`

Поиск автомобилей по госномеру и марке.

#### Параметры запроса:
- `q` (required) - Поисковый запрос

#### Пример запроса:
```
GET /admin/cars/search?q=Toyota
```

#### Ответ:
```json
{
  "cars": [
    {
      "id": 1,
      "name": "Toyota Camry",
      "plate_number": "ABC123",
      "status": "FREE",
      "status_display": "Свободно",
      "latitude": 40.7128,
      "longitude": -74.0060,
      "fuel_level": 75.5,
      "mileage": 50000,
      "auto_class": "A",
      "body_type": "SEDAN",
      "year": 2020,
      "owner_name": "Иван Иванов",
      "current_renter_name": null,
      "photos": ["photo1.jpg"]
    }
  ],
  "search_query": "Toyota",
  "results_count": 1
}
```

### 5. Получение детальной информации об автомобиле

**GET** `/admin/cars/{car_id}`

Получение полной информации об автомобиле.

#### Параметры пути:
- `car_id` - ID автомобиля

#### Ответ:
```json
{
  "id": 1,
  "name": "Toyota Camry",
  "plate_number": "ABC123",
  "status": "FREE",
  "status_display": "Свободно",
  "latitude": 40.7128,
  "longitude": -74.0060,
  "fuel_level": 75.5,
  "mileage": 50000,
  "course": 90,
  "auto_class": "A",
  "body_type": "SEDAN",
  "transmission_type": "automatic",
  "year": 2020,
  "engine_volume": 2.5,
  "drive_type": 1,
  "price_per_minute": 10,
  "price_per_hour": 500,
  "price_per_day": 8000,
  "description": "Комфортный седан для города",
  "photos": ["photo1.jpg", "photo2.jpg"],
  "gps_id": "GPS123",
  "gps_imei": "IMEI123",
  "owner": {
    "id": 456,
    "first_name": "Иван",
    "last_name": "Иванов",
    "phone_number": "+1234567890",
    "auto_class": ["A", "B"]
  },
  "current_renter": null
}
```

### 6. Получение статистики по автомобилям

**GET** `/admin/cars/statistics`

Получение статистики по автомобилям для дашборда админ-панели.

#### Ответ:
```json
{
  "total_cars": 100,
  "cars_by_status": {
    "FREE": 45,
    "IN_USE": 30,
    "MAINTENANCE": 10,
    "DELIVERING": 5,
    "OWNER": 5,
    "RETURNING": 3,
    "DELIVERED": 1,
    "RETURNED": 1
  },
  "cars_by_class": {
    "A": 60,
    "B": 30,
    "C": 10
  },
  "cars_by_body_type": {
    "SEDAN": 40,
    "SUV": 25,
    "CROSSOVER": 20,
    "HATCHBACK": 15
  },
  "active_rentals": 30,
  "available_cars": 45,
  "maintenance_cars": 10
}
```

## Статусы автомобилей

| Статус | Описание | Отображение |
|--------|----------|-------------|
| `FREE` | Свободен | "Свободно" |
| `IN_USE` | В аренде | "В аренде" |
| `MAINTENANCE` | На ремонте/у механика | "На ремонте" |
| `DELIVERING` | В доставке | "В доставке" |
| `OWNER` | У владельца | "У владельца" |
| `RETURNING` | Возвращается | "Возвращается" |
| `DELIVERED` | Доставлено | "Доставлено" |
| `RETURNED` | Возвращено | "Возвращено" |

## Коды ошибок

- `403 Forbidden` - Недостаточно прав доступа
- `404 Not Found` - Автомобиль не найден
- `422 Unprocessable Entity` - Некорректные данные запроса

## Особенности реализации

1. **Фильтрация**: Все фильтры можно комбинировать между собой
2. **Поиск**: Поиск работает по частичному совпадению (ILIKE) для госномера и названия автомобиля
3. **Статусы**: Смена статуса доступна только админу и поддержке
4. **Безопасность**: Все эндпоинты проверяют роль пользователя
5. **Производительность**: Используются оптимизированные SQL-запросы с индексами
