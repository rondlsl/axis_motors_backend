# AZV Motors Backend — Архитектура системы

> Версия документа: 2026-01-28
> Стек: Python 3.12 · FastAPI · PostgreSQL 15 · APScheduler · MinIO (S3) · Telegram Bot · WebSocket
> Деплой: Docker Compose · Uvicorn · порт 7139

---

## Оглавление

1. [Обзор системы](#1-обзор-системы)
2. [Компонентная диаграмма](#2-компонентная-диаграмма)
3. [Входные точки (Entry Points)](#3-входные-точки)
4. [Application Layer](#4-application-layer)
5. [Domain Layer](#5-domain-layer)
6. [Infrastructure Layer](#6-infrastructure-layer)
7. [Async / Background Processing](#7-async--background-processing)
8. [Auth / Security](#8-auth--security)
9. [Logging / Monitoring / Error Handling](#9-logging--monitoring--error-handling)
10. [Configuration и ENV](#10-configuration-и-env)
11. [Data Flow диаграммы](#11-data-flow-диаграммы)
12. [Sequence-диаграммы ключевых сценариев](#12-sequence-диаграммы-ключевых-сценариев)
13. [Структура директорий](#13-структура-директорий)
14. [Summary — Как читать эту архитектуру](#14-summary--как-читать-эту-архитектуру)

---

## 1. Обзор системы

AZV Motors — платформа каршеринга в Алматы (Казахстан). Backend обслуживает:

- **Мобильное приложение** (iOS/Android) — клиенты арендуют автомобили
- **Админ-панель** (Web) — управление парком, пользователями, финансами
- **Telegram-ботов** — мониторинг ошибок, техподдержка
- **GPS-сервис** — внешний микросервис для телеметрии автомобилей

### Ключевые бизнес-потоки

| Поток | Описание |
|-------|----------|
| Регистрация | SMS-верификация → загрузка документов → проверка финансистом → проверка МВД |
| Аренда | Бронирование → старт (selfie) → поминутный биллинг → завершение → расчёт |
| Доставка | Механик доставляет авто клиенту по координатам |
| Поддержка | Telegram-бот принимает сообщения → операторы отвечают через веб-панель |
| Кошелёк | Пополнение через ForteBank → списание за аренду → история транзакций |

---

## 2. Компонентная диаграмма

```mermaid
graph TB
    subgraph Clients["Клиенты"]
        MA["📱 Mobile App<br/>iOS / Android"]
        WA["🖥 Admin Panel<br/>Web"]
        TG["💬 Telegram Bot<br/>Support + Monitoring"]
    end

    subgraph Entry["Входные точки (FastAPI)"]
        REST["REST API<br/>/auth /rent /vehicles /wallet ..."]
        WS["WebSocket<br/>/ws/vehicles /ws/user /ws/support"]
        WH["Telegram Webhook<br/>/support/webhook"]
        HEALTH["Health Checks<br/>/ /health /health/cars"]
    end

    subgraph App["Application Layer"]
        AUTH["Auth Router"]
        RENT["Rent Router"]
        VEH["Vehicle/GPS Router"]
        ADMIN["Admin Router"]
        WALL["Wallet Router"]
        SUP["Support Router"]
        OWN["Owner Router"]
        MECH["Mechanic Router"]
        FIN["Financier Router"]
        MVD["MVD Router"]
        ACC["Accountant Router"]
        CON["Contracts Router"]
        PUSH["Push Router"]
        MON["Monitoring Router"]
    end

    subgraph Services["Service Layer"]
        SS["SupportService"]
        MS["MinIOService"]
        FV["FaceVerifyService"]
        BIL["BillingJob"]
        TL["TelegramLogger"]
    end

    subgraph Infra["Infrastructure"]
        DB[("PostgreSQL 15<br/>21 таблица")]
        MINIO["MinIO (S3)<br/>msmain.azvmotors.kz"]
        GPS_EXT["GlonassSoft API<br/>GPS телеметрия"]
        FORTE["ForteBank API<br/>Платежи"]
        MOBI["Mobizon API<br/>SMS"]
        FCM["Firebase FCM<br/>Push"]
        TG_API["Telegram API<br/>Bots"]
    end

    subgraph Scheduler["APScheduler Jobs"]
        J1["billing_job<br/>каждые 60 сек"]
        J2["check_vehicle_conditions<br/>каждые 1 сек"]
        J3["update_cars_availability<br/>каждые 1 мин"]
        J4["auto_close_support_chats<br/>каждые 1 час"]
        J5["marketing_notifications<br/>cron"]
    end

    MA --> REST
    MA --> WS
    WA --> REST
    WA --> WS
    TG --> WH

    REST --> App
    WS --> App
    WH --> SUP

    App --> Services
    App --> DB
    Services --> DB
    Services --> MINIO
    Services --> GPS_EXT
    Services --> FORTE
    Services --> MOBI
    Services --> FCM
    Services --> TG_API

    Scheduler --> DB
    Scheduler --> GPS_EXT
    Scheduler --> FCM

    style Clients fill:#e1f5fe
    style Entry fill:#fff3e0
    style App fill:#e8f5e9
    style Services fill:#f3e5f5
    style Infra fill:#fce4ec
    style Scheduler fill:#fff9c4
```

---

## 3. Входные точки

### 3.1 REST API Routers

Все роутеры регистрируются в `main.py` через `app.include_router(...)`.

| Router | Prefix | Роль | Кол-во эндпоинтов |
|--------|--------|------|-------------------|
| `Auth_router` | `/auth` | Регистрация, SMS, JWT, документы | ~12 |
| `Vehicle_Router` | `/vehicles` | GPS, телеметрия, команды авто | ~5 |
| `RentRouter` | `/rent` | Бронирование, аренда, биллинг | ~8 |
| `PushRouter` | `/notifications` | FCM токены, broadcast | ~4 |
| `WalletRouter` | `/wallet` | Баланс, транзакции, выписки | ~5 |
| `ContractsRouter` | `/contracts` | Загрузка/подпись договоров | ~6 |
| `HTMLContractsRouter` | `/contracts` | HTML-генерация договоров | ~3 |
| `SupportRouter` | `/support` | Чаты поддержки, Telegram | ~5 |
| `OwnerRouter` | `/owner` | Управление авто для владельцев | ~4 |
| `MechanicRouter` | `/mechanic` | Инспекции, обслуживание | ~3 |
| `MechanicDeliveryRouter` | `/mechanic-delivery` | Доставка авто | ~4 |
| `guarantor_router` | `/guarantor` | Поручительство | ~5 |
| `FinancierRouter` | `/financier` | Проверка заявок | ~3 |
| `MvdRouter` | `/mvd` | Проверка МВД | ~3 |
| `accountant_router` | `/accountant` | Финансовые отчёты | ~3 |
| `admin_router` | `/admin` | Админ-панель (cars, users, rentals, analytics) | ~20+ |
| `MonitoringRouter` | `/monitoring` | Метрики, статус сервисов | ~3 |
| `AppVersionsRouter` | `/app-versions` | Версии мобильного приложения | ~3 |
| `ErrorLogsRouter` | `/admin/error_logs` | Логи ошибок | ~3 |
| `websocket_router` | `/ws` | WebSocket подключения | 3 |

### 3.2 WebSocket

```mermaid
graph LR
    subgraph WebSocket Endpoints
        WS1["/ws/vehicles/telemetry/{car_id}<br/>GPS координаты в реальном времени"]
        WS2["/ws/user/status/{user_id}<br/>Обновления профиля"]
        WS3["/ws/support/chats/{chat_id}<br/>Чат поддержки"]
    end

    subgraph ConnectionManager
        CM["manager.py<br/>- группировка по subscription_key<br/>- tracking user_id + metadata<br/>- broadcast в группы"]
    end

    WS1 --> CM
    WS2 --> CM
    WS3 --> CM
```

**Файлы:**
- `app/websocket/manager.py` — менеджер соединений
- `app/websocket/router.py` — WebSocket роутер
- `app/websocket/handlers.py` — обработчики сообщений
- `app/websocket/auth.py` — аутентификация WebSocket
- `app/websocket/notifications.py` — push в WebSocket-каналы

### 3.3 Telegram Webhook

Telegram-бот поддержки принимает входящие сообщения от пользователей:

1. Пользователь пишет боту в Telegram
2. Telegram отправляет webhook на `/support/webhook`
3. `telegram_bot.py` создаёт/обновляет `SupportChat` в БД
4. Операторы видят сообщение в веб-панели через WebSocket

### 3.4 Health Checks

| Endpoint | Назначение |
|----------|-----------|
| `GET /` | Базовая проверка (`{"message": "salam?"}`) |
| `GET /health` | Статус с timestamp |
| `GET /health/cars` | Проверка GPS-сервиса, алерт в Telegram при недоступности |
| `GET /test-websocket` | Список WebSocket эндпоинтов |
| `GET /list_routes` | Все зарегистрированные маршруты |

---

## 4. Application Layer

### 4.1 Архитектурный паттерн

Проект использует **Router-centric** архитектуру (не Clean Architecture). Бизнес-логика находится непосредственно в обработчиках роутеров. Сервисный слой выделен частично — только для сложных интеграций.

```
Request → Middleware Chain → Router Handler → SQLAlchemy ORM → Response
                                    ↓
                              Service (при необходимости)
                                    ↓
                        External API / MinIO / Telegram
```

### 4.2 Ответственности роутеров

**Auth Router** (`app/auth/router.py`):
- Отправка SMS через Mobizon API
- Верификация SMS-кода, создание JWT
- Загрузка документов (ID, права, selfie) → MinIO
- Управление профилем, refresh token, email-верификация

**Rent Router** (`app/rent/router.py`):
- Калькулятор стоимости аренды
- Бронирование с предоплатой
- Старт/завершение аренды (с фото)
- Продление, отмена, штрафы
- Верификация платежей ForteBank

**Vehicle/GPS Router** (`app/gps_api/router.py`):
- Список доступных автомобилей с телеметрией
- Команды GPS (lock/unlock, engine on/off, двери)
- Интеграция с GlonassSoft API

**Admin Router** (`app/admin/router.py`):
- CRUD автомобилей, пользователей, аренд
- Аналитика (депозиты, расходы, доходы)
- Управление поручителями, SMS-рассылки

### 4.3 Зависимости между слоями

```mermaid
graph TD
    R["Routers<br/>(app/auth, app/rent, app/admin, ...)"]
    S["Services<br/>(app/services/)"]
    U["Utils<br/>(app/utils/)"]
    M["Models<br/>(app/models/)"]
    SC["Schemas<br/>(app/schemas/)"]
    D["Database<br/>(app/dependencies/database/)"]
    EXT["External APIs"]

    R --> S
    R --> M
    R --> SC
    R --> D
    R --> U
    R --> EXT
    S --> M
    S --> D
    S --> EXT
    U --> M
    U --> D

    style R fill:#c8e6c9
    style S fill:#e1bee7
    style M fill:#ffccbc
    style D fill:#b3e5fc
```

**Допустимые зависимости:**
- Router → Service, Model, Schema, Utils, DB
- Service → Model, DB, External API
- Utils → Model, DB (вспомогательные функции)

**Недопустимые зависимости:**
- Model → Router (модели не знают о роутерах)
- Schema → Service (схемы — чистые DTO)
- DB config → бизнес-логика

---

## 5. Domain Layer

### 5.1 Доменные сущности (21 таблица)

```mermaid
erDiagram
    User ||--o{ RentalHistory : "арендует"
    User ||--o{ Car : "владеет"
    User ||--o| Car : "арендует сейчас"
    User ||--o| Application : "заявка"
    User ||--o{ WalletTransaction : "транзакции"
    User ||--o{ UserDevice : "устройства"
    User ||--o{ Notification : "уведомления"
    User ||--o{ UserPromoCode : "промокоды"
    User ||--o{ GuarantorRequest : "поручительство"
    User ||--o{ SupportChat : "чаты поддержки"
    User ||--o{ UserContractSignature : "подписи"
    User ||--o{ CarComment : "комментарии"

    Car ||--o{ RentalHistory : "история аренд"
    Car ||--o{ CarAvailabilityHistory : "доступность"
    Car ||--o{ CarComment : "комментарии"

    RentalHistory ||--o| RentalReview : "отзыв"
    RentalHistory ||--o{ RentalAction : "действия"
    RentalHistory ||--o{ UserContractSignature : "договоры"

    GuarantorRequest ||--o| Guarantor : "активное поручительство"
    Guarantor ||--o{ UserContractSignature : "договоры"

    ContractFile ||--o{ UserContractSignature : "подписи"
    PromoCode ||--o{ UserPromoCode : "использования"
    SupportChat ||--o{ SupportMessage : "сообщения"

    User {
        UUID id PK
        String phone_number
        Enum role "CLIENT|USER|ADMIN|MECHANIC|..."
        Numeric wallet_balance
        Boolean documents_verified
        Boolean is_active
    }

    Car {
        UUID id PK
        String plate_number UK
        Enum status "FREE|IN_USE|SERVICE|..."
        Float latitude
        Float longitude
        Integer price_per_minute
    }

    RentalHistory {
        UUID id PK
        UUID user_id FK
        UUID car_id FK
        Enum rental_status "RESERVED|IN_USE|COMPLETED|..."
        Integer total_price
        DateTime start_time
        DateTime end_time
    }

    WalletTransaction {
        UUID id PK
        UUID user_id FK
        Numeric amount
        Enum transaction_type
        Numeric balance_before
        Numeric balance_after
    }

    Application {
        UUID id PK
        UUID user_id FK
        Enum financier_status
        Enum mvd_status
    }
```

### 5.2 Ключевые бизнес-правила

**Регистрация пользователя — конечный автомат ролей:**

```mermaid
stateDiagram-v2
    [*] --> CLIENT: SMS верификация
    CLIENT --> PENDINGTOFIRST: Загрузка документов
    PENDINGTOFIRST --> PENDINGTOSECOND: Одобрено финансистом
    PENDINGTOFIRST --> REJECTFIRSTDOC: Документы отклонены
    PENDINGTOFIRST --> REJECTFIRSTCERT: Нет справок
    PENDINGTOFIRST --> REJECTFIRST: Отклонено (можно с поручителем)
    REJECTFIRSTDOC --> PENDINGTOFIRST: Повторная загрузка
    REJECTFIRSTCERT --> PENDINGTOFIRST: Повторная загрузка
    REJECTFIRST --> PENDINGTOFIRST: Поручитель предоставлен
    PENDINGTOSECOND --> USER: Одобрено МВД
    PENDINGTOSECOND --> REJECTSECOND: Отклонено МВД (финал)
    USER --> [*]: Полный доступ к аренде
    REJECTSECOND --> [*]: Блокировка
```

**Жизненный цикл аренды:**

```mermaid
stateDiagram-v2
    [*] --> RESERVED: Бронирование
    RESERVED --> IN_USE: Старт аренды
    RESERVED --> CANCELLED: Отмена
    RESERVED --> SCHEDULED: Предварительное бронирование
    SCHEDULED --> RESERVED: Время подошло
    IN_USE --> COMPLETED: Завершение
    IN_USE --> DELIVERING: Нужна доставка
    DELIVERING --> DELIVERY_RESERVED: Механик назначен
    DELIVERY_RESERVED --> DELIVERING_IN_PROGRESS: Механик едет
    DELIVERING_IN_PROGRESS --> IN_USE: Доставлено
```

**Статусы автомобиля:**

| Статус | Значение |
|--------|---------|
| `FREE` | Доступен для аренды |
| `PENDING` | Ожидает подтверждения |
| `IN_USE` | В аренде |
| `DELIVERING` | Доставляется механиком |
| `SERVICE` | На обслуживании |
| `RESERVED` | Забронирован |
| `SCHEDULED` | Запланирована аренда |
| `OWNER` | У владельца |
| `OCCUPIED` | Занят (другая причина) |

### 5.3 Идентификаторы

Все сущности используют **UUID** как внутренний PK, но для API отдают **Short ID (SID)** — компактное представление UUID. Конвертация через `app/utils/sid_converter.py` и миксин `SidMixin` в Pydantic-схемах.

---

## 6. Infrastructure Layer

### 6.1 PostgreSQL

```
Engine: postgresql+psycopg2
Pool size: 50 connections
Max overflow: 50 (итого до 100)
Pool timeout: 10 сек
Pool recycle: 1800 сек (30 мин)
Statement timeout: 180 сек
Lock timeout: 60 сек
```

**Файлы:**
- `app/dependencies/database/database.py` — engine, SessionLocal, `get_db()`
- `app/dependencies/database/base.py` — SQLAlchemy `declarative_base()`
- `migrations/` — Alembic миграции

**Dependency Injection:**
```python
# FastAPI Depends
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Использование в роутере
@router.get("/something")
async def handler(db: Session = Depends(get_db)):
    ...
```

### 6.2 MinIO (S3-совместимое хранилище)

| Параметр | Значение |
|----------|---------|
| Endpoint | `https://msmain.azvmotors.kz` |
| Buckets | `uploads` (основной), `backups` (архив) |
| Формат | WebP (конвертация из JPEG/PNG, качество 85%) |
| Клиент | boto3 S3, singleton pattern |

**Обработка изображений:**
1. Получение файла через multipart form
2. Чтение EXIF-ориентации → коррекция поворота (Pillow)
3. Конвертация в WebP
4. Загрузка в MinIO
5. Возврат публичного URL: `https://msmain.azvmotors.kz/uploads/...`

### 6.3 Внешние API

```mermaid
graph LR
    subgraph Backend
        B["AZV Motors API"]
    end

    subgraph External["Внешние сервисы"]
        GL["GlonassSoft<br/>GPS трекинг"]
        FB["ForteBank<br/>Платежи"]
        MZ["Mobizon<br/>SMS"]
        FC["Firebase<br/>Push FCM"]
        TG["Telegram API<br/>Боты"]
        GPS_SVC["Vehicles API<br/>195.93.152.69:8667"]
    end

    B -->|"auth + telemetry<br/>каждые 1 сек"| GL
    B -->|"verify transaction"| FB
    B -->|"send SMS"| MZ
    B -->|"push notification"| FC
    B -->|"send message<br/>error alerts"| TG
    B -->|"get vehicles data<br/>каждые 1 сек"| GPS_SVC
```

**GlonassSoft (GPS):**
- Аутентификация по логину/паролю, токен обновляется каждые 30 мин
- Телеметрия: координаты, топливо, пробег, скорость, курс
- Команды: блокировка/разблокировка двигателя, двери
- HTTP-клиент с rate limiting: `app/RateLimitedHTTPClient.py`

**ForteBank (Платежи):**
- Endpoint: `https://gateway.fortebank.com/v2/transactions/tracking_id/{id}`
- Верификация: проверка `tracking_id` → подтверждение суммы → зачисление на кошелёк
- Авторизация: `FORTE_SHOP_ID` + `FORTE_SECRET_KEY`

**Mobizon (SMS):**
- Endpoint: `https://api.mobizon.kz/service/message/sendsmsmessage`
- Rate limiting: 60 сек cooldown, максимум 5 SMS/час на номер
- Тест-режим: `SMS_TOKEN=6666` — SMS не отправляются

**Firebase (Push):**
- `firebase-admin` SDK
- Device token management: `app/push/`
- Семафор: максимум 10 одновременных push-отправок
- Локализованные уведомления: ru/en/kz/zh

---

## 7. Async / Background Processing

Проект **не использует Celery**. Вместо него — **APScheduler** (AsyncIOScheduler) с часовым поясом GMT+5 (Алматы).

### 7.1 Scheduled Jobs

```mermaid
gantt
    title APScheduler — периодические задачи
    dateFormat X
    axisFormat %s

    section Критические
    billing_job (60 сек)           :active, 0, 60
    check_vehicle_conditions (1 сек) :active, 0, 1

    section Регулярные
    update_cars_availability (1 мин) :active, 0, 60
    auto_close_support_chats (1 час) :active, 0, 3600

    section Маркетинг (cron)
    check_birthdays (09:00)        :milestone, 0, 0
    check_holidays (08:00)         :milestone, 0, 0
    check_weekend_promotions       :milestone, 0, 0
    check_new_cars (каждый час)    :milestone, 0, 0
```

| Job | Интервал | Что делает | Файл |
|-----|----------|-----------|------|
| `billing_job` | 60 сек | Поминутное списание за аренду | `app/rent/utils/billing.py` |
| `check_vehicle_conditions` | 1 сек | Опрос GPS-сервера, обновление координат/топлива/пробега, детекция заправки | `main.py` |
| `update_cars_availability_job` | 1 мин | Обновление доступности автомобилей | `app/owner/availability.py` |
| `auto_close_support_chats` | 1 час | Закрытие resolved-чатов через 12 часов | `main.py` |
| `check_birthdays` | cron 09:00 | Push-уведомления в день рождения | `app/scheduler/marketing_notifications.py` |
| `check_holidays` | cron 08:00 | Поздравления с праздниками | `app/scheduler/marketing_notifications.py` |
| `check_weekend_promotions` | Пт 19:00, Пн 08:00 | Промо выходного дня | `app/scheduler/marketing_notifications.py` |
| `check_new_cars` | cron каждый час | Уведомления о новых авто | `app/scheduler/marketing_notifications.py` |

### 7.2 Паттерн выполнения фоновых задач

Так как APScheduler работает в asyncio event loop, CPU-bound операции выполняются через `run_in_executor`:

```
APScheduler trigger
    → async function (coroutine)
        → loop.run_in_executor(None, sync_function)
            → sync_function получает новый DB session
            → выполняет ORM-операции
            → commit / rollback
            → session.close()
```

### 7.3 HangWatchdog

Отдельный фоновый процесс мониторит отзывчивость event loop:
- Проверка каждые 5 сек
- Порог зависания: 10 сек
- При обнаружении — логирование активных запросов

---

## 8. Auth / Security

### 8.1 Аутентификация

```mermaid
sequenceDiagram
    participant C as Client
    participant API as FastAPI
    participant SMS as Mobizon
    participant DB as PostgreSQL

    C->>API: POST /auth/send_sms {phone}
    API->>DB: Найти/создать User
    API->>SMS: Отправить SMS-код
    API-->>C: 200 OK

    C->>API: POST /auth/verify_sms {phone, code}
    API->>DB: Проверить код + срок
    API->>DB: Сохранить TokenRecord
    API-->>C: {access_token, refresh_token}

    Note over C,API: Все последующие запросы с Bearer token

    C->>API: GET /auth/user/me [Bearer token]
    API->>API: JWTBearer → verify_token()
    API->>API: Fernet decrypt phone
    API->>DB: Query User by phone
    API-->>C: User profile
```

**JWT конфигурация:**
- Алгоритм: HS256
- Access token: 140 минут
- Refresh token: 30 дней
- Номер телефона шифруется Fernet в payload токена
- Токены хранятся в таблице `token_records` для отзыва

### 8.2 Авторизация (RBAC)

16 ролей. Проверка в роутерах через `get_current_user()` + проверка `user.role`:

| Роль | Доступ |
|------|--------|
| `CLIENT` | Только профиль, загрузка документов |
| `USER` | Полный доступ: аренда, кошелёк, поддержка |
| `MECHANIC` | Инспекции, обслуживание |
| `OWNER` | Управление своими автомобилями |
| `FINANCIER` | Проверка заявок на регистрацию |
| `MVD` | Проверка по базам МВД |
| `ADMIN` | Полный доступ ко всем ресурсам |
| `ACCOUNTANT` | Финансовые отчёты |
| `SUPPORT` | Чаты поддержки |
| `DRIVER` | Аренда с водителем |
| `GARANT` | Поручительство |

### 8.3 Swagger UI Protection

- HTTP Basic Auth для `/docs`, `/redoc`, `/openapi.json`
- Middleware `SwaggerAuthMiddleware` проверяет credentials
- Логин/пароль из ENV: `SWAGGER_USERNAME`, `SWAGGER_PASSWORD`

### 8.4 CORS

```python
CORSMiddleware(
    allow_origins=["*"],       # Все источники
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 8.5 Системные номера

Захардкожены в коде — обходят SMS-верификацию, фиксированный код. Используются для тестирования и служебных аккаунтов:

```
70000000000  — admin
71234567890  — mechanic
71234567898  — MVD
71234567899  — financier
79999999999  — accountant
71231111111  — owner
```

---

## 9. Logging / Monitoring / Error Handling

### 9.1 Middleware Chain

Middleware выполняются в **обратном порядке** регистрации (последний добавленный — первый в цепочке).

```mermaid
graph TB
    REQ["Incoming Request"] --> PM
    PM["PerformanceMonitoringMiddleware<br/>Трекинг длительности<br/>slow > 3s, alert > 10s"] --> SA
    SA["SwaggerAuthMiddleware<br/>HTTP Basic для /docs"] --> EL
    EL["ErrorLoggerMiddleware<br/>Отлов исключений → Telegram + DB"] --> HD
    HD["HangDetectorMiddleware<br/>Трекинг активных запросов"] --> RL
    RL["RequestLoggerMiddleware<br/>Логирование: method, path, status, duration, trace_id"] --> CORS
    CORS["CORSMiddleware<br/>allow_origins=*"] --> HANDLER
    HANDLER["Route Handler"]

    HANDLER --> CORS
    CORS --> RL
    RL --> HD
    HD --> EL
    EL --> SA
    SA --> PM
    PM --> RESP["Response"]
```

### 9.2 Logging

Два формата, переключаемых через `LOG_FORMAT`:

| Формат | Когда | Описание |
|--------|-------|---------|
| `ColoredFormatter` | development (default) | Цветной вывод: время, уровень, модуль.функция, сообщение |
| `JSONFormatter` | production (`LOG_FORMAT=json`) | Структурированный JSON для агрегации |

**Extra fields:** `user_id`, `phone`, `rental_id`, `car_id`, `amount`, `status`, `duration`, `request_id`

**Файл:** `app/core/logging_config.py`

### 9.3 Error Handling

```mermaid
flowchart TD
    E["Exception в handler"] --> ELM["ErrorLoggerMiddleware"]
    ELM --> LOG["logger.error()"]
    ELM --> TG["Telegram Alert<br/>бот отправляет в группу мониторинга"]
    ELM --> DBL["ErrorLog в PostgreSQL<br/>error_type, traceback, endpoint, user_id"]
    ELM --> RESP["Response 500"]

    RESP -->|"DEBUG_API_ERRORS=1"| DETAIL["JSON: detail + traceback"]
    RESP -->|"DEBUG_API_ERRORS=0"| GENERIC["JSON: Internal Server Error"]
```

**Telegram Alert формат:**
```
🚨 Error: ValueError
📍 Endpoint: POST /rent/start-rental
👤 User: +7777XXXXXXX
📋 Traceback: ...
```

Длинные сообщения (>4096 символов) разбиваются на несколько Telegram-сообщений.

**Файлы:**
- `app/middleware/error_logger_middleware.py` — middleware
- `app/utils/telegram_logger.py` — отправка в Telegram
- `app/models/error_log_model.py` — модель ErrorLog

### 9.4 Action Logging

Административные действия записываются в `action_logs`:

```python
ActionLog(
    actor_id=admin.id,
    action="approve_user",
    entity_type="User",
    entity_id=user.id,
    details={"old_role": "PENDING", "new_role": "USER"}
)
```

### 9.5 HangWatchdog

Независимый поток мониторинга:
- Проверяет отзывчивость asyncio event loop каждые 5 сек
- Если loop не ответил за 10 сек — лог с перечнем активных запросов
- Настраивается через ENV: `HANG_WATCHDOG_CHECK_INTERVAL`, `HANG_WATCHDOG_THRESHOLD`

---

## 10. Configuration и ENV

### 10.1 Файл конфигурации

`app/core/config.py` — все переменные окружения читаются через `os.getenv()` с `python-dotenv`.

### 10.2 Переменные окружения

| Группа | Переменные |
|--------|-----------|
| **Database** | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB` |
| **JWT** | `SECRET_KEY`, `ALGORITHM` |
| **GPS** | `GLONASSSOFT_USERNAME`, `GLONASSSOFT_PASSWORD`, `VEHICLES_API_URL` |
| **SMS** | `SMS_TOKEN` |
| **Telegram** | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_TOKEN_2`, `TELEGRAM_BOT_MONITOR`, `SUPPORT_GROUP_ID`, `MONITOR_GROUP_ID` |
| **MinIO** | `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET_UPLOADS`, `MINIO_BUCKET_BACKUPS`, `MINIO_PUBLIC_URL`, `MINIO_USE_SSL` |
| **Payments** | `FORTE_SHOP_ID`, `FORTE_SECRET_KEY` |
| **Swagger** | `SWAGGER_USERNAME`, `SWAGGER_PASSWORD` |
| **Debug** | `DEBUG_API_ERRORS`, `LOG_LEVEL`, `LOG_FORMAT` |
| **Watchdog** | `HANG_WATCHDOG_CHECK_INTERVAL`, `HANG_WATCHDOG_THRESHOLD` |

### 10.3 Feature Flags

| Flag | Значение | Эффект |
|------|---------|--------|
| `SMS_TOKEN=6666` | Тест-режим | SMS не отправляются, любой код проходит |
| `DEBUG_API_ERRORS=1` | Debug | Полные трейсбеки в HTTP-ответах |
| `LOG_FORMAT=json` | Production | JSON-формат логов |

### 10.4 Docker

```yaml
# docker-compose.yml
services:
  back:
    build: .                            # Dockerfile → Python 3.12
    ports: ["7139:7139"]
    command: uvicorn main:app --host 0.0.0.0 --port 7139 --ws auto
    healthcheck:
      test: curl -sf http://localhost:7139/health
      interval: 15s
    depends_on: [db]

  db:
    image: postgres:15
    ports: ["5434:5432"]               # Внешний порт 5434
    volumes: [postgres_data_v2:/var/lib/postgresql/data]
```

**Startup sequence:**
1. PostgreSQL запускается
2. Backend ждёт DB → запускает Alembic миграции
3. Инициализирует MinIO клиент
4. Запускает APScheduler jobs
5. Запускает Telegram Support bot
6. Запускает HangWatchdog

---

## 11. Data Flow диаграммы

### 11.1 Поток аренды автомобиля

```mermaid
flowchart TD
    subgraph Client["Мобильное приложение"]
        C1["Выбор авто"]
        C2["Бронирование"]
        C3["Старт аренды"]
        C4["Поездка"]
        C5["Завершение"]
    end

    subgraph API["Backend API"]
        A1["GET /vehicles/"]
        A2["POST /rent/booking/advanced"]
        A3["POST /rent/start-rental"]
        A4["billing_job (каждые 60 сек)"]
        A5["POST /rent/complete-rental"]
    end

    subgraph DB["PostgreSQL"]
        D1["cars → status: FREE"]
        D2["rental_history → RESERVED<br/>cars → RESERVED"]
        D3["rental_history → IN_USE<br/>cars → IN_USE"]
        D4["wallet_transactions<br/>balance -= price_per_minute"]
        D5["rental_history → COMPLETED<br/>cars → FREE"]
    end

    subgraph Ext["External"]
        GPS["GPS: координаты"]
        FORTE["ForteBank: оплата"]
        FCM_N["FCM: push"]
    end

    C1 --> A1
    A1 --> D1
    A1 --> GPS

    C2 --> A2
    A2 --> D2
    A2 -->|"проверка баланса"| D4

    C3 --> A3
    A3 -->|"selfie проверка"| A3
    A3 --> D3
    A3 -->|"unlock car"| GPS

    C4 --> A4
    A4 --> D4
    A4 -->|"баланс < 0"| FCM_N

    C5 --> A5
    A5 -->|"lock car"| GPS
    A5 --> D5
    A5 -->|"финальный расчёт"| D4
```

### 11.2 Поток регистрации пользователя

```mermaid
flowchart TD
    subgraph Client
        U1["Ввод телефона"]
        U2["Ввод SMS-кода"]
        U3["Загрузка документов"]
    end

    subgraph API
        S1["POST /auth/send_sms"]
        S2["POST /auth/verify_sms"]
        S3["POST /auth/upload-documents"]
    end

    subgraph Admin["Админ-панель"]
        F1["Финансист проверяет"]
        M1["МВД проверяет"]
    end

    subgraph External
        SMS_EXT["Mobizon → SMS"]
        MINIO_EXT["MinIO → фото"]
        FCM_REG["FCM → push"]
    end

    subgraph DB
        DB1["User → role: CLIENT"]
        DB2["User → sms_code verified"]
        DB3["User → role: PENDINGTOFIRST"]
        DB4["Application → financier_status"]
        DB5["User → role: PENDINGTOSECOND"]
        DB6["Application → mvd_status"]
        DB7["User → role: USER"]
    end

    U1 --> S1
    S1 --> SMS_EXT
    S1 --> DB1

    U2 --> S2
    S2 --> DB2
    S2 -->|"JWT tokens"| U3

    U3 --> S3
    S3 --> MINIO_EXT
    S3 --> DB3

    F1 --> DB4
    DB4 -->|"approved"| DB5
    DB4 -->|"rejected"| DB3

    M1 --> DB6
    DB6 -->|"approved"| DB7
    DB6 -->|"rejected"| DB3

    DB5 --> FCM_REG
    DB7 --> FCM_REG
```

### 11.3 Поток данных GPS-телеметрии

```mermaid
flowchart LR
    subgraph GPS["GPS-трекеры в авто"]
        T1["Трекер 1"]
        T2["Трекер 2"]
        TN["Трекер N"]
    end

    subgraph GS["GlonassSoft Cloud"]
        GS1["API сервер"]
    end

    subgraph VehiclesAPI["Vehicles API<br/>195.93.152.69:8667"]
        VA["Кеш GPS данных"]
    end

    subgraph Backend["AZV Backend"]
        SCH["APScheduler<br/>каждую 1 сек"]
        UPD["update_vehicle_data()"]
        THR["run_in_executor<br/>(отдельный поток)"]
    end

    subgraph Store["Хранилище"]
        PG["PostgreSQL<br/>cars таблица"]
        WSN["WebSocket<br/>notify_vehicles_list_update"]
    end

    subgraph Consumers["Потребители"]
        APP["Mobile App<br/>(WebSocket)"]
        ADM["Admin Panel<br/>(WebSocket)"]
    end

    T1 & T2 & TN --> GS1
    GS1 --> VA
    SCH --> UPD
    UPD -->|"HTTP GET"| VA
    UPD --> THR
    THR -->|"UPDATE cars SET lat, lon, fuel, mileage"| PG
    THR -->|"fuel +10%?"| FCM2["FCM: Уведомление о заправке"]
    THR --> WSN
    WSN --> APP
    WSN --> ADM
```

---

## 12. Sequence-диаграммы ключевых сценариев

### 12.1 Полный цикл аренды

```mermaid
sequenceDiagram
    actor U as Пользователь
    participant API as FastAPI
    participant DB as PostgreSQL
    participant GPS as GlonassSoft
    participant FB as ForteBank
    participant BJ as BillingJob

    U->>API: POST /rent/booking/advanced
    API->>DB: Проверить баланс кошелька
    API->>DB: Создать RentalHistory (RESERVED)
    API->>DB: Обновить Car (status=RESERVED)
    API-->>U: booking_id

    U->>API: POST /rent/start-rental (selfie)
    API->>API: Сравнить selfie (если включено)
    API->>GPS: Разблокировать двери
    API->>DB: RentalHistory (IN_USE), записать photos_before
    API->>DB: Car (status=IN_USE)
    API-->>U: rental started

    loop Каждые 60 секунд
        BJ->>DB: Найти все IN_USE аренды
        BJ->>DB: Списать price_per_minute с кошелька
        BJ->>DB: Создать WalletTransaction
    end

    U->>API: POST /rent/complete-rental (photos)
    API->>GPS: Заблокировать двери + двигатель
    API->>DB: Записать photos_after, fuel_after, mileage_after
    API->>DB: Рассчитать total_price (base + overtime + distance + fuel)
    API->>DB: RentalHistory (COMPLETED)
    API->>DB: Car (status=FREE)
    API-->>U: receipt (total_price breakdown)

    opt Если баланс отрицательный
        U->>FB: Пополнить через ForteBank
        FB-->>U: tracking_id
        U->>API: POST /rent/verify-forte-transaction
        API->>FB: Проверить статус платежа
        API->>DB: Пополнить wallet_balance
    end
```

### 12.2 Поддержка через Telegram

```mermaid
sequenceDiagram
    actor TU as Telegram User
    participant TG as Telegram API
    participant BOT as Support Bot
    participant DB as PostgreSQL
    participant WS as WebSocket
    actor OP as Оператор (Web)

    TU->>TG: Сообщение боту
    TG->>BOT: Webhook → /support/webhook
    BOT->>DB: Найти/создать SupportChat
    BOT->>DB: Создать SupportMessage (sender_type=client)
    BOT->>WS: Notify: новое сообщение
    WS->>OP: WebSocket push

    OP->>API: POST /support/chats/{id}/messages
    API->>DB: Создать SupportMessage (sender_type=support)
    API->>TG: Отправить ответ пользователю
    TG->>TU: Ответ оператора

    Note over DB: Через 12 часов без активности
    Note over DB: auto_close_support_chats → closed
```

---

## 13. Структура директорий

```
azv_motors_backend_v2/
├── main.py                          # Entry point: FastAPI app, middleware, scheduler
├── alembic.ini                      # Alembic config
├── requirements.txt                 # Python dependencies
├── Dockerfile                       # Python 3.12 image
├── docker-compose.yml               # back + db services
├── docker-compose.test.yml          # Test environment
│
├── app/
│   ├── core/
│   │   ├── config.py                # ENV variables, constants, polygon coords
│   │   └── logging_config.py        # JSON/Colored formatters, setup_logging()
│   │
│   ├── dependencies/
│   │   └── database/
│   │       ├── database.py          # Engine, SessionLocal, get_db()
│   │       └── base.py              # SQLAlchemy declarative_base()
│   │
│   ├── models/                      # SQLAlchemy ORM models (21 таблица)
│   │   ├── user_model.py            # User (16 ролей, документы, кошелёк)
│   │   ├── car_model.py             # Car (GPS, статус, цены)
│   │   ├── history_model.py         # RentalHistory + RentalReview
│   │   ├── wallet_transaction_model.py  # WalletTransaction (20+ типов)
│   │   ├── application_model.py     # Application (финансист + МВД)
│   │   ├── guarantor_model.py       # GuarantorRequest + Guarantor
│   │   ├── contract_model.py        # ContractFile + UserContractSignature
│   │   ├── notification_model.py    # Notification
│   │   ├── support_chat_model.py    # SupportChat
│   │   ├── support_message_model.py # SupportMessage
│   │   ├── rental_actions_model.py  # RentalAction (open/close/lock/unlock)
│   │   ├── promo_codes_model.py     # PromoCode + UserPromoCode
│   │   ├── car_comment_model.py     # CarComment
│   │   ├── token_model.py           # TokenRecord
│   │   ├── user_device_model.py     # UserDevice (FCM tokens)
│   │   ├── verification_code_model.py # VerificationCode (SMS/email)
│   │   ├── action_log_model.py      # ActionLog (audit)
│   │   ├── error_log_model.py       # ErrorLog
│   │   ├── app_version_model.py     # AppVersion
│   │   └── support_action_model.py  # SupportAction
│   │
│   ├── schemas/                     # Pydantic DTO
│   │   ├── base.py                  # SidMixin, SidField (UUID ↔ ShortID)
│   │   └── support_schemas.py       # Support chat/message schemas
│   │
│   ├── services/                    # Сервисный слой
│   │   ├── support_service.py       # CRUD чатов, auto-close, Telegram relay
│   │   ├── minio_service.py         # S3 upload, WebP conversion, EXIF
│   │   └── face_verify.py           # DeepFace verification (отключено)
│   │
│   ├── middleware/                   # HTTP middleware
│   │   ├── error_logger_middleware.py    # Exception → Telegram + DB
│   │   ├── request_logger_middleware.py  # Request logging с trace_id
│   │   ├── hang_detector_middleware.py   # Active request tracking
│   │   └── performance_monitor.py       # Slow/alert request detection
│   │
│   ├── auth/                        # Аутентификация
│   │   └── router.py                # SMS, JWT, документы, профиль
│   │
│   ├── rent/                        # Аренда
│   │   ├── router.py                # Booking, start, complete, extend
│   │   └── utils/
│   │       └── billing.py           # Поминутный биллинг (APScheduler job)
│   │
│   ├── gps_api/                     # GPS / Vehicles
│   │   ├── router.py                # Vehicle list, GPS commands
│   │   ├── schemas.py               # Vehicle DTOs
│   │   ├── schemas_telemetry.py     # Telemetry DTOs
│   │   └── utils/
│   │       └── get_active_rental.py # Helper: найти активную аренду по car_id
│   │
│   ├── wallet/                      # Кошелёк
│   │   ├── router.py                # Balance, transactions, statement
│   │   ├── schemas.py               # Wallet DTOs
│   │   └── utils.py                 # Transaction helpers
│   │
│   ├── admin/                       # Админ-панель
│   │   ├── router.py                # Cars, users, rentals, analytics
│   │   ├── analytics/               # Отчёты: deposits, expenses
│   │   └── error_logs/
│   │       └── router.py            # Error log browser
│   │
│   ├── support/                     # Поддержка
│   │   ├── router.py                # Chat API endpoints
│   │   ├── telegram_bot.py          # Telegram webhook handler
│   │   └── notification_service.py  # WebSocket notifications
│   │
│   ├── websocket/                   # WebSocket
│   │   ├── manager.py               # ConnectionManager
│   │   ├── router.py                # WS endpoints
│   │   ├── handlers.py              # Message handlers
│   │   ├── admin_handlers.py        # Admin-specific handlers
│   │   ├── auth.py                  # WS auth
│   │   └── notifications.py         # Broadcast helpers
│   │
│   ├── push/                        # Push-уведомления
│   │   ├── router.py                # FCM token management
│   │   └── utils.py                 # send_localized_notification
│   │
│   ├── contracts/                   # Договоры
│   │   ├── router.py                # Upload, sign, download
│   │   ├── html_router.py           # HTML generation
│   │   ├── schemas.py               # Contract DTOs
│   │   └── utils.py                 # PDF/DOCX helpers
│   │
│   ├── guarantor/                   # Поручительство
│   │   ├── router.py                # Request, accept, reject
│   │   ├── schemas.py               # Guarantor DTOs
│   │   └── sms_utils.py             # SMS приглашение поручителю
│   │
│   ├── owner/                       # Владельцы авто
│   │   ├── router.py                # Car management
│   │   ├── schemas.py               # Owner DTOs
│   │   ├── availability.py          # Car availability tracking
│   │   └── utils.py                 # Owner helpers
│   │
│   ├── mechanic/                    # Механики
│   │   ├── router.py                # Inspections
│   │   └── utils.py                 # Mechanic helpers
│   │
│   ├── mechanic_delivery/           # Доставка авто
│   │   └── router.py                # Delivery management
│   │
│   ├── financier/                   # Финансисты
│   │   └── router.py                # Application review
│   │
│   ├── mvd/                         # МВД проверки
│   │   └── router.py                # MVD review
│   │
│   ├── accountant/                  # Бухгалтерия
│   │   └── router.py                # Financial reports
│   │
│   ├── monitoring/                  # Мониторинг
│   │   └── router.py                # Service health, metrics
│   │
│   ├── app_versions/                # Версии приложения
│   │   ├── router.py                # Version management
│   │   └── schemas.py               # Version DTOs
│   │
│   ├── scheduler/                   # Планировщик
│   │   └── marketing_notifications.py  # Birthday, holiday, promo pushes
│   │
│   ├── translations/                # Локализация
│   │   ├── notifications.py         # Push-уведомления ru/en/kz/zh
│   │   └── excel_headers.py         # Заголовки Excel-отчётов
│   │
│   ├── utils/                       # Утилиты
│   │   ├── telegram_logger.py       # Error → Telegram group
│   │   ├── sid_converter.py         # UUID ↔ Short ID
│   │   ├── short_id.py              # Short ID generation
│   │   ├── time_utils.py            # get_local_time() (GMT+5)
│   │   ├── action_logger.py         # ActionLog writer
│   │   ├── digital_signature.py     # Digital signature generation
│   │   ├── plate_normalizer.py      # License plate normalization
│   │   ├── fcm_token.py             # FCM helpers
│   │   ├── user_activity.py         # Last activity tracker
│   │   ├── user_data.py             # User data helpers
│   │   ├── atomic_operations.py     # DB atomic operation helpers
│   │   ├── hang_watchdog.py         # Event loop watchdog
│   │   ├── hang_logger.py           # Hang event logger
│   │   └── error_logger_decorator.py # Error logging decorator
│   │
│   ├── seed/                        # Seed data
│   │   └── init_data.py             # Test data initialization
│   │
│   └── RateLimitedHTTPClient.py     # HTTP client с rate limiting
│
├── migrations/                      # Alembic migrations
│   ├── env.py                       # Migration environment
│   └── versions/                    # Migration files
│       ├── 001_initial_migration.py
│       ├── 002_add_speed_to_cars.py
│       ├── 003_add_accountant_role.py
│       └── 004_add_open_fee_to_cars.py
│
└── scripts/                         # Maintenance scripts
    ├── convert_car_photos_jpeg_to_webp.py
    ├── convert_images_to_webp.py
    ├── fix_selfie_orientation.py
    └── backfill_availability_history.py
```

---

## 14. Summary — Как читать эту архитектуру

### Принципы организации

1. **Router-centric**: бизнес-логика живёт в роутерах (не в сервисах). Сервисы выделены только для сложных интеграций (MinIO, Support, Face Verify).

2. **Feature-based folders**: каждый модуль (rent, auth, wallet, support) — отдельная папка с router.py + utils. Не слоёная архитектура (не Clean Architecture).

3. **Shared models**: все ORM-модели в `app/models/`, все DTO в `app/schemas/`. Роутеры импортируют модели напрямую.

4. **Scheduled jobs вместо очередей**: APScheduler заменяет Celery/RabbitMQ. Все фоновые задачи выполняются в том же процессе.

5. **Монолит в одном контейнере**: API, WebSocket, Scheduler, Telegram bot — всё в одном Uvicorn-процессе.

### Lifecycle запроса: от входа до БД и обратно

```
1. HTTP Request приходит на порт 7139 (Uvicorn)
      ↓
2. PerformanceMonitoringMiddleware: засекает время
      ↓
3. SwaggerAuthMiddleware: проверка Basic Auth для /docs
      ↓
4. ErrorLoggerMiddleware: try/except → Telegram + DB при ошибке
      ↓
5. HangDetectorMiddleware: регистрирует активный запрос
      ↓
6. RequestLoggerMiddleware: генерирует trace_id, логирует
      ↓
7. CORSMiddleware: добавляет CORS headers
      ↓
8. FastAPI Router: сопоставление URL → handler function
      ↓
9. Dependencies: get_db() → SessionLocal, get_current_user() → JWT verify
      ↓
10. Handler: бизнес-логика
    - Валидация Pydantic (автоматическая)
    - ORM-запросы к PostgreSQL
    - Вызовы внешних API (HTTP)
    - Загрузка файлов в MinIO
      ↓
11. Response: Pydantic → JSON (ORJSONResponse)
      ↓
12. Middleware chain (обратный путь):
    - RequestLogger: логирует status + duration
    - PerformanceMonitor: предупреждает, если > 3 сек
      ↓
13. HTTP Response → клиент
```

### Как онбордить нового разработчика

1. **Начни с `main.py`** — здесь видно все роутеры, middleware, scheduler jobs
2. **Изучи `app/models/`** — 21 модель = полная схема данных
3. **Прочитай интересующий роутер** (например, `app/rent/router.py`) — вся логика внутри
4. **Посмотри middleware** — поймёшь как работает error handling и logging
5. **Настрой `.env`** по списку из раздела 10 этого документа
6. **Запусти `docker-compose up`** — поднимется API + PostgreSQL

### Известные архитектурные решения, которые стоит учитывать

| Решение | Следствие |
|---------|----------|
| Бизнес-логика в роутерах | Тестирование требует HTTP-вызовов, нельзя протестировать логику изолированно |
| Нет репозиторного слоя | ORM-запросы разбросаны по всем роутерам |
| Один процесс для всего | Scheduler и API делят один event loop; тяжёлая задача может заблокировать API |
| APScheduler вместо Celery | Нет retry, нет distributed workers, нет приоритетов задач |
| `CORS allow_origins=["*"]` | Открыто для любых доменов |
| GPS-опрос каждую 1 секунду | Высокая нагрузка на GPS-сервис и БД |
| Wallet balance в User модели | Критичные финансовые данные без optimistic locking |