# Email Reputation & Deliverability (AZV Motors)

Архитектура системы репутации email: валидация, suppression по статусу, проверка перед отправкой.

## Цепочка

```
User → EmailService (validation + should_send) → Resend → Webhook POST /webhooks/email → process_webhook → User.email_status
```

## 1. Поля пользователя (User)

| Поле            | Назначение |
|-----------------|------------|
| `email_status`  | `pending` \| `verified` \| `bounced` \| `complaint` \| `suppressed` |
| `bounce_count`  | Количество bounce; при >3 (soft) или 1 (hard) → `bounced` |
| `last_bounce_at`| Время последнего bounce |

Не отправляем письма на адреса со статусом `bounced`, `complaint`, `suppressed`.

## 2. Валидация перед отправкой

- **Синтаксис** — базовый regex.
- **Disposable-домены** — блоклист (mailinator, tempmail, 10minutemail, …).
- Опционально: MX-проверка (при необходимости добавить `dnspython`).

Вызов: `email_reputation.validate_email(email)` → `(ok, error_message)`.

## 3. Отправка (EmailService)

- При вызове с `db` выполняется проверка: `validate_email` и `should_send_to_email(db, email)`.
- При запрете отправки (bounce/complaint/validation) выбрасывается `EmailServiceError`.
- Resend возвращает `message_id` — логируется для отладки/метрик.

Роуты админки/саппорта передают `db=db` в `send_plain_email(..., db=db)`.

## 4. Webhook Resend

- **URL:** `POST https://api.azvmotors.kz/webhooks/email`
- В Resend: **Settings → Webhooks** → добавить endpoint, события: `email.sent`, `email.delivered`, `email.bounced`, `email.complained`.
- Подпись: Svix (`RESEND_WEBHOOK_SECRET`). Без секрета в dev payload принимается без проверки.

Обработка:
- **email.bounced** — `bounce.type === "Permanent"` → сразу `email_status = "bounced"`; Temporary → `bounce_count += 1`, при >3 → `bounced`.
- **email.complained** → `email_status = "complaint"`.

## 5. Конфиг (.env)

```env
RESEND_API_KEY=re_...
EMAIL_FROM=Azv Motors <noreply@azvmotors.kz>
RESEND_WEBHOOK_SECRET=whsec_...   # из Resend → Webhooks → Signing secret
```

## 6. Double opt-in

- До подтверждения кода: `email_status` остаётся `pending` (или `verified` после подтверждения).
- Массовые рассылки только на `verified`; перед отправкой проверка `should_send_to_user(user)`.

## 7. Метрики (рекомендации)

- Bounce rate < 2%
- Complaint rate < 0.1%
- Delivery rate > 98%

При росте bounce — чистка базы и проверка валидации/MX.

## Файлы

| Компонент              | Файл |
|------------------------|------|
| Модель User           | `app/models/user_model.py` (email_status, bounce_count, last_bounce_at) |
| Репутация/валидация    | `app/services/email_reputation.py` |
| Отправка + проверки   | `app/services/email_service.py` |
| Webhook Resend        | `app/webhooks/router.py` |
| Миграция               | `migrations/versions/011_add_email_reputation_fields.py` |
