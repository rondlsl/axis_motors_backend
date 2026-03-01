# 🧩 План спринтов и распределение обязанностей

**Проект:** AZV Motors / Axis IoT  
**Backend:** axis_backend (FastAPI, PostgreSQL, MinIO)  
**Frontend:** axis_web_front (Next.js 15, React 19, TypeScript)  
**Команда:** Аружан (разработчик), Карина (разработчик), Мадина (фронтенд-разработчик, спринты 6–11)  
**Версия документа:** 2.0  
**Дата:** 28.02.2026

---

## Содержание

1. [Обзор спринтов](#обзор-спринтов)
2. [Спринты Аружан и Карина (1–11)](#спринты-аружан-и-карина)
3. [Спринты Мадина (6–11)](#спринты-мадина)
4. [Соответствие Backend и Frontend](#соответствие-backend-и-frontend)
5. [Рекомендации по разработке](#рекомендации-по-разработке)

---

## Обзор спринтов

| № | Спринт | Описание |
|---|--------|----------|
| 1 | Аутентификация и пользовательский доступ | Регистрация, авторизация, сессии |
| 2 | Загрузка и верификация документов | Загрузка документов, статус проверки |
| 3 | Бронирование автомобиля | Каталог, карточка авто, процесс бронирования |
| 4 | Аренда автомобиля | Начало и завершение аренды |
| 5 | Осмотр автомобиля | Начало/завершение осмотра, фиксация состояния |
| 6 | Заказ доставки (клиент) | Создание заявки на доставку, статус |
| 7 | Доставка автомобиля (механик) | Принятие заказа, управление статусами |
| 8 | Гарант | Поручительство |
| 9 | История поездок | Страница поездок, детализация |
| 10 | Уведомления, кошелёк и отзывы | Push, баланс, история транзакций, отзывы |
| 11 | Вспомогательные страницы | Поддержка, правила, профиль, политика конфиденциальности |

---

## Спринты Аружан и Карина

Задачи разбиты по **Backend** (axis_backend) и **Frontend** (axis_web_front).

---

### 🔹 Спринт 1 — Аутентификация и пользовательский доступ

**Backend API:** `POST /auth/send_sms/`, `POST /auth/verify_sms/`, `POST /auth/refresh_token/`, `GET /auth/user/me`, `DELETE /auth/delete_account/`

| Задача | Исполнитель | Backend | Frontend |
|--------|-------------|---------|----------|
| Экран ввода номера телефона | Аружан | — | `app/auth/page.tsx`, `_pages/auth/`, `shared/api/routes/auth.ts` → `sendSms`, UI формы, валидация номера |
| Экран ввода SMS-кода | Аружан | — | `app/auth/`, `auth.ts` → `verifySms`, UI для 6-значного кода (react-otp-input), таймер повторной отправки |
| Хранение JWT и refresh-логика | Карина | `app/auth/security/tokens.py`, `auth/dependencies/` | `shared/utils/tokenStorage.ts`, `shared/api/axios.ts` — interceptor, Bearer token, автообновление |
| Экран онбординга | Карина | — | `app/onboarding/page.tsx` — приветственный экран, логика первого запуска |
| Выход из аккаунта | Карина | — | `shared/utils/logout.ts`, `features/auth/provider/AuthContext.tsx`, кнопка в Drawer/Profile |

---

### 🔹 Спринт 2 — Загрузка и верификация документов

**Backend API:** `POST /auth/upload-documents/`, `POST /auth/upload-selfie/`, `GET /auth/user/registration-info`, `GET /auth/user/me`

| Задача | Исполнитель | Backend | Frontend |
|--------|-------------|---------|----------|
| Экран выбора типа документа | Аружан | — | `app/auth/registration/page.tsx`, `_pages/profile/ui/widgets/documents/` — навигация по типам |
| Камера / галерея для документов | Аружан | — | `shared/utils/flutter-camera.ts`, `widgets/upload-photo/`, съёмка, выбор, crop, валидация формата |
| Загрузка документов | Карина | `app/auth/dependencies/save_documents.py`, `app/services/minio_service.py` | `shared/api/routes/user.ts` → `uploadDocuments`, multipart upload, отображение прогресса |
| Экран статуса верификации | Карина | — | `_pages/profile/ui/widgets/documents/ModerationStatus.tsx`, статусы PENDING/APPROVED/REJECTED |
| Повторная загрузка при отклонении | Карина | — | `_pages/profile/ui/widgets/documents/` — кнопка «Загрузить заново», навигация к загрузке |

---

### 🔹 Спринт 3 — Бронирование автомобиля

**Backend API:** `GET /rent/available-cars`, `GET /vehicles/`, `POST /rent/calculator`, `POST /rent/reserve-car/`, `GET /rent/my-bookings`

| Задача | Исполнитель | Backend | Frontend |
|--------|-------------|---------|----------|
| Карта с маркерами авто | Аружан | — | `_pages/main/ui/widgets/`, `shared/ui/map/BaseMap.tsx`, `@vis.gl/react-google-maps`, маркеры, clustering |
| Список автомобилей | Аружан | — | `_pages/cars/free/page.tsx`, `entities/car-card/CarCard.tsx`, `shared/stores/carsListStore.ts` |
| Карточка автомобиля | Карина | — | `entities/car-card/`, детали: фото, характеристики, цена, кнопка «Забронировать» |
| Калькулятор стоимости | Карина | — | `shared/api/routes/rent.ts` → `calculator`, modals в `_pages/main/ui/widgets/modals/user/` |
| Процесс бронирования | Карина | `app/rent/router.py` (reserve-car) | `rentApi.reserveCar`, `rentalFlowStore.ts`, проверка баланса, подтверждение |

---

### 🔹 Спринт 4 — Аренда автомобиля

**Backend API:** `POST /rent/start/`, upload-photos-before/after, `POST /rent/complete`, `POST /rent/extend`, WebSocket `/ws/vehicles/telemetry/`

| Задача | Исполнитель | Backend | Frontend |
|--------|-------------|---------|----------|
| Экран «Начать аренду» | Аружан | — | `_pages/main/ui/widgets/screens/rental-screen/`, selfie, вызов `rentApi.startRent` |
| Съёмка фото до аренды | Аружан | — | `widgets/upload-photo/`, `shared/contexts/PhotoUploadContext.tsx`, экстерьер, интерьер |
| Активный экран аренды | Карина | — | `_pages/main/` — таймер, стоимость, кнопки GPS (open/close) |
| WebSocket телеметрия | Карина | `app/websocket/router.py` | Подключение к WS, отображение топлива, пробега, координат |
| Завершение аренды | Карина | — | `rentApi.completeRent`, `upload-photos-after`, `RentalCompletionGuideModal.tsx` |
| Продление аренды | Аружан | — | Кнопка продления, `rentApi.extend`, `shared/ui/date-picker/` |

---

### 🔹 Спринт 5 — Осмотр автомобиля

**Backend API:** `POST /mechanic/start/`, upload-photos-before/after, `POST /mechanic/complete`, `GET /mechanic/inspection-history`

| Задача | Исполнитель | Backend | Frontend |
|--------|-------------|---------|----------|
| Список авто для осмотра | Аружан | `app/mechanic/router.py` | `_pages/mechanic/pending/page.tsx`, `shared/api/routes/mechanic.ts`, `vechiclesStore.ts` |
| Начало осмотра | Аружан | — | `mechanicApi.checkCar`, `mechanicModalStore.ts`, фото до осмотра |
| Фиксация повреждений | Карина | — | `_pages/main/ui/widgets/modals/mechanic/`, запись состояния, фото с привязкой |
| Завершение осмотра | Карина | — | `mechanicApi.complete`, `widgets/upload-photo/`, summary |
| История осмотров | Карина | — | `mechanicApi.inspectionHistory`, `_pages/mechanic/in-rent/` — список, детализация |

---

### 🔹 Спринт 6 — Заказ доставки (клиент)

**Backend API:** `POST /rent/reserve-delivery/`, `POST /rent/cancel-delivery`, `GET /rent/my-bookings`

| Задача | Исполнитель | Backend | Frontend |
|--------|-------------|---------|----------|
| Экран выбора адреса доставки | Аружан | — | `_pages/main/ui/widgets/screens/delivery-screen/DeliveryAddressScreen.tsx`, `shared/ui/AddressInput.tsx`, геокодинг |
| Создание заявки на доставку | Аружан | `app/rent/router.py` (reserve-delivery) | `rentApi.reserveDelivery`, калькулятор с доставкой |
| Экран статуса доставки | Карина | — | `_pages/main/ui/widgets/screens/delivery-screen/`, статусы ожидание/в пути/прибыл |
| Отмена доставки | Карина | — | `rentApi.cancelDelivery`, кнопка отмены, модальное подтверждение |

---

### 🔹 Спринт 7 — Доставка (механик)

**Backend API:** `POST /mechanic/accept-delivery/`, `start-delivery`, `complete-delivery`, upload-delivery-photos

| Задача | Исполнитель | Backend | Frontend |
|--------|-------------|---------|----------|
| Список заказов на доставку | Аружан | `app/mechanic_delivery/router.py` | `_pages/mechanic/delivery/page.tsx`, `mechanicDeliveryModalStore.ts` |
| Принятие заказа | Аружан | — | `mechanicApi.acceptDelivery`, кнопка «Принять» |
| Навигация к клиенту | Карина | — | Отображение маршрута, точка на карте (`shared/ui/map/`) |
| Фото при передаче ключей | Карина | — | `mechanicApi.uploadDeliveryPhotos`, `widgets/upload-photo/` |
| Обновление статусов | Карина | — | Start delivery, Complete delivery, поллинг/обновление UI |

---

### 🔹 Спринт 8 — Гарант

**Backend API:** `POST /guarantor/invite`, accept/reject, `GET /guarantor/incoming`, contracts, dashboard

| Задача | Исполнитель | Backend | Frontend |
|--------|-------------|---------|----------|
| Экран «Пригласить поручителя» | Аружан | `app/guarantor/router.py` | `app/guarantor/page.tsx`, `_pages/guarantor/`, `shared/api/routes/guarantor.ts` → invite |
| Входящие запросы | Аружан | — | `guarantorApi.incoming`, список, карточка запроса |
| Принятие/отклонение | Карина | — | `guarantorApi.accept`, `guarantorApi.reject`, UI кнопок |
| Договоры поручителя | Карина | — | `guarantorApi.contracts`, просмотр, загрузка, подписание |
| Dashboard поручителя | Карина | — | `guarantorApi.dashboard`, обзор клиентов, статусы |

---

### 🔹 Спринт 9 — История поездок

**Backend API:** `GET /rent/history`, `GET /rent/history/{history_id}`

| Задача | Исполнитель | Backend | Frontend |
|--------|-------------|---------|----------|
| Список поездок | Аружан | — | `_pages/trips/ui/TripsAndFinesPage.tsx`, `shared/api/routes/history.ts`, карточки |
| Фильтры и сортировка | Аружан | — | По дате, статусу, поиск в `TripsAndFinesPage` |
| Детальная страница поездки | Карина | — | `_pages/trips/ui/RentalHistoryDetailPage.tsx`, маршрут, фото, разбивка стоимости |
| Интеграция с картой маршрута | Карина | — | `_pages/trips/ui/components/RouteMap.tsx`, `FullScreenMapModal.tsx`, `route_data` |

---

### 🔹 Спринт 10 — Уведомления, кошелёк и отзывы

**Backend API:** `POST /notifications/register`, `GET /wallet/balance`, `GET /wallet/transactions`, RentalReview

| Задача | Исполнитель | Backend | Frontend |
|--------|-------------|---------|----------|
| Регистрация FCM-токена | Аружан | `app/push/router.py` | `shared/api/routes/user.ts` → `fcmToken`, интеграция Firebase |
| Экран уведомлений | Аружан | — | `_pages/messages/`, `shared/api/routes/notifications.ts` |
| Экран баланса кошелька | Карина | `app/wallet/router.py` | `_pages/wallet/`, `app/wallet/page.tsx`, `shared/api/routes/wallet.ts` |
| Отзывы на поездки | Карина | `app/models/history_model.py` (RentalReview) | Форма отзыва в `RentalHistoryDetailPage`, рейтинг, текст |

---

### 🔹 Спринт 11 — Вспомогательные страницы

**Backend API:** `GET/POST /support/chats`, messages; `GET /auth/user/me`, `PATCH /auth/user/name`, `POST /auth/set_locale/`

| Задача | Исполнитель | Backend | Frontend |
|--------|-------------|---------|----------|
| Страница поддержки | Аружан | `app/support/router.py` | `_pages/support/ui/SupportPage.tsx` — чаты, REST-поллинг сообщений |
| Страница профиля | Карина | — | `_pages/profile/`, `userApi.getUser`, `updateName`, `shared/ui/language-selector/` |
| Правила сервиса | Карина | — | `_pages/terms/`, `app/` routes для terms |
| Политика конфиденциальности | Карина | — | `app/privacy-policy/page.tsx` — статическая страница |

---

## Спринты Мадина

**Роль:** фронтенд-разработчик, поддержка спринтов 6–11.

| № | Спринт | Задачи (Frontend — axis_web_front) |
|---|--------|------------------------------------|
| **6** | Заказ доставки (клиент) | UI/UX экрана выбора адреса: улучшение `AddressInput`, адаптивность, валидация. Стилизация экрана статуса доставки, скелетоны загрузки, анимации переходов |
| **7** | Доставка (механик) | UI экрана механика: карточки заказов, кнопки статусов, адаптивная вёрстка. Доработка модальных окон и формы загрузки фото |
| **8** | Гарант | Вёрстка страницы поручителя: формы приглашения, карточки входящих запросов, dashboard. Консистентность с общим дизайн-системой |
| **9** | История поездок | Стилизация списка поездок и детальной страницы: карточки, фильтры, карта маршрута. Доступность (a11y), responsive |
| **10** | Уведомления, кошелёк и отзывы | UI страницы уведомлений и кошелька: список транзакций, формы отзывов, компоненты рейтинга. Интеграция с `shared/ui/` |
| **11** | Вспомогательные страницы | Страницы правил, политики конфиденциальности, контактов. Вёрстка чата поддержки, страницы профиля. Типографика, читаемость, мобильная версия |

### Детализация задач Мадины по спринтам

#### Спринт 6
| Задача | Описание | Файлы |
|--------|----------|-------|
| UI экрана адреса доставки | Улучшение `AddressInput`, автодополнение, иконки, состояния (loading/error) | `shared/ui/AddressInput.tsx`, `delivery-screen/` |
| UI статуса доставки | Карточки статусов, индикаторы, скелетоны | `_pages/main/ui/widgets/screens/delivery-screen/` |

#### Спринт 7
| Задача | Описание | Файлы |
|--------|----------|-------|
| Карточки заказов механика | Вёрстка списка, badge статусов, кнопки | `_pages/mechanic/delivery/`, `mechanicDeliveryModalStore` |
| Модалки и формы | Стилизация модальных окон, форма фото | `shared/ui/modal/`, `widgets/upload-photo/` |

#### Спринт 8
| Задача | Описание | Файлы |
|--------|----------|-------|
| Формы и карточки гаранта | Input, кнопки, список запросов | `_pages/guarantor/`, `app/guarantor/` |
| Dashboard | Таблицы/карточки клиентов, статусы | `guarantor` dashboard UI |

#### Спринт 9
| Задача | Описание | Файлы |
|--------|----------|-------|
| Список поездок | Карточки, фильтры, empty state | `_pages/trips/ui/TripsAndFinesPage.tsx` |
| Детали поездки | Карта, табы, секции | `RentalHistoryDetailPage.tsx`, `RouteMap.tsx` |

#### Спринт 10
| Задача | Описание | Файлы |
|--------|----------|-------|
| Уведомления | Список, иконки, группировка по дате | `_pages/messages/` |
| Кошелёк и отзывы | Таблица транзакций, форма отзыва, рейтинг | `_pages/wallet/`, компоненты отзывов |

#### Спринт 11
| Задача | Описание | Файлы |
|--------|----------|-------|
| Статические страницы | Правила, политика, контакты | `_pages/terms/`, `app/privacy-policy/`, `app/contact/` |
| Профиль и поддержка | Вёрстка профиля, чат поддержки | `_pages/profile/`, `_pages/support/` |

---

## Соответствие Backend и Frontend

| Спринт | Backend (axis_backend) | Frontend (axis_web_front) |
|--------|------------------------|---------------------------|
| 1 | `app/auth/` | `app/auth/`, `features/auth/`, `shared/utils/tokenStorage.ts` |
| 2 | `app/auth/`, `save_documents.py` | `_pages/profile/ui/widgets/documents/`, `shared/api/user.ts` |
| 3 | `app/rent/`, `app/gps_api/` | `_pages/main/`, `_pages/cars/`, `entities/car-card/`, `rent.ts` |
| 4 | `app/rent/`, `app/websocket/` | `rental-screen/`, `widgets/upload-photo/`, `PhotoUploadContext` |
| 5 | `app/mechanic/` | `_pages/mechanic/`, `shared/api/mechanic.ts`, `mechanicModalStore` |
| 6 | `app/rent/` (reserve-delivery) | `delivery-screen/`, `AddressInput`, `rentApi.reserveDelivery` |
| 7 | `app/mechanic_delivery/` | `_pages/mechanic/delivery/`, `mechanicDeliveryModalStore` |
| 8 | `app/guarantor/` | `app/guarantor/`, `_pages/guarantor/`, `shared/api/guarantor.ts` |
| 9 | `app/rent/` (history) | `_pages/trips/`, `historyApi`, `RouteMap` |
| 10 | `app/push/`, `app/wallet/` | `_pages/messages/`, `_pages/wallet/`, `walletApi`, `notifications.ts` |
| 11 | `app/support/`, `app/auth/` | `_pages/support/`, `_pages/profile/`, `_pages/terms/`, `privacy-policy` |

---

## Рекомендации по разработке

### Общие принципы
1. **Синхронность:** Аружан и Карина работают параллельно; Мадина подключается с 6 спринта для фронтенд-поддержки.
2. **Code Review:** Перекрёстный review перед мержем. Мадина — фокус на UI/UX и вёрстке.
3. **Тестирование:** Smoke-тесты на backend (порт 7139) и frontend (Next.js dev).
4. **Документация:** Swagger (`/docs`), `ARCHITECTURE.md`, структура `axis_web_front` в `src/`.

### Зависимости
- Спринты 1–2 → 3 (авторизация и документы).
- Спринт 3 блокирует 4 и 6.
- Спринт 4 → 9 (история).
- Спринт 10 после 1–2.
- Мадина координирует с Аружан и Карина по UI-компонентам в спринтах 6–11.

### Риски
| Риск | Митигация |
|------|-----------|
| Долгая проверка документов | Poll для обновления статуса |
| Чаты без WebSocket | REST API с поллингом |

---

*Документ подготовлен на основе анализа `axis_backend` и `axis_web_front`.*
