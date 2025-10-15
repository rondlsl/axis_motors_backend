# 🧪 Тестовые Endpoints для Push-уведомлений

## Обзор

Добавлены два тестовых endpoint для удобного тестирования push-уведомлений:

1. **`POST /notifications/test_push_by_phone`** - Отправка push по номеру телефона
2. **`GET /notifications/test_users_with_tokens`** - Получение списка пользователей с токенами

## 1. Отправка Push по номеру телефона

### Endpoint
```
POST /notifications/test_push_by_phone
```

### Требования
- ✅ Авторизация (Bearer token)
- ✅ Роль: `ADMIN` или `MECHANIC`

### Request Body
```json
{
  "phone": "77777777772",
  "title": "Тестовое уведомление",
  "body": "Это тестовое push-уведомление для проверки работы системы"
}
```

### Параметры
| Параметр | Тип | Обязательный | Описание |
|----------|-----|--------------|----------|
| phone | string | ✅ Да | Номер телефона пользователя |
| title | string | ❌ Нет | Заголовок (по умолчанию: "Тестовое уведомление") |
| body | string | ❌ Нет | Текст уведомления |

### Response (Success)
```json
{
  "success": true,
  "user": {
    "id": "uuid-string",
    "phone": "77777777772",
    "name": "Иван Иванов",
    "fcm_token": "ExponentPushToken[SVQJNvMGv5...]..."
  },
  "message": "Push notification sent successfully"
}
```

### Response (Errors)

**403 Forbidden - Нет прав доступа**
```json
{
  "detail": "Only admins and mechanics can use test endpoints"
}
```

**404 Not Found - Пользователь не найден**
```json
{
  "detail": "User with phone 77777777772 not found"
}
```

**400 Bad Request - Нет FCM токена**
```json
{
  "detail": "User 77777777772 doesn't have FCM token. User needs to login to the app first."
}
```

### Примеры использования

#### cURL
```bash
curl -X POST "http://localhost:7138/notifications/test_push_by_phone" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "77777777772",
    "title": "Привет!",
    "body": "Тестовое сообщение"
  }'
```

#### Python (httpx)
```python
import httpx
import asyncio

async def test_push():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:7138/notifications/test_push_by_phone",
            headers={"Authorization": f"Bearer {YOUR_TOKEN}"},
            json={
                "phone": "77777777772",
                "title": "Тест",
                "body": "Проверка push-уведомлений"
            }
        )
        print(response.json())

asyncio.run(test_push())
```

#### JavaScript (fetch)
```javascript
fetch('http://localhost:7138/notifications/test_push_by_phone', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer YOUR_TOKEN',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    phone: '77777777772',
    title: 'Тест',
    body: 'Проверка push-уведомлений'
  })
})
.then(res => res.json())
.then(data => console.log(data));
```

---

## 2. Получение списка пользователей с токенами

### Endpoint
```
GET /notifications/test_users_with_tokens
```

### Требования
- ✅ Авторизация (Bearer token)
- ✅ Роль: `ADMIN` или `MECHANIC`

### Response
```json
{
  "total_users_with_tokens": 15,
  "users": [
    {
      "id": "uuid-string",
      "phone": "77777777772",
      "name": "Иван Иванов",
      "role": "CLIENT",
      "fcm_token_preview": "ExponentPushToken[SVQJNvMGv5...]...",
      "fcm_token": "ExponentPushToken[SVQJNvMGv5tQLb3FIuGYY4]"
    },
    {
      "id": "uuid-string-2",
      "phone": "77777777773",
      "name": "Петр Петров",
      "role": "CLIENT",
      "fcm_token_preview": "ExponentPushToken[jrAZnBAYhA...]...",
      "fcm_token": "ExponentPushToken[jrAZnBAYhABMx3GKoLgt2q]"
    }
  ]
}
```

### Примеры использования

#### cURL
```bash
curl -X GET "http://localhost:7138/notifications/test_users_with_tokens" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### Python
```python
import httpx
import asyncio

async def get_users_with_tokens():
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "http://localhost:7138/notifications/test_users_with_tokens",
            headers={"Authorization": f"Bearer {YOUR_TOKEN}"}
        )
        data = response.json()
        print(f"Всего пользователей с токенами: {data['total_users_with_tokens']}")
        for user in data['users']:
            print(f"- {user['phone']}: {user['name']} ({user['role']})")

asyncio.run(get_users_with_tokens())
```

---

## Workflow тестирования

### Шаг 1: Получите список пользователей с токенами
```bash
GET /notifications/test_users_with_tokens
```

### Шаг 2: Выберите пользователя и отправьте push
```bash
POST /notifications/test_push_by_phone
{
  "phone": "77777777772",
  "title": "Тест",
  "body": "Сообщение"
}
```

### Шаг 3: Проверьте логи
```bash
docker-compose logs -f back | grep -E "(📱|📤|📥|✅|❌)"
```

### Шаг 4: Проверьте на устройстве
- Откройте мобильное приложение
- Проверьте, пришло ли уведомление
- Проверьте в списке уведомлений: `GET /notifications/`

---

## Swagger UI

Эти endpoints доступны в Swagger UI:
```
http://localhost:7138/docs
```

1. Авторизуйтесь через кнопку "Authorize"
2. Найдите раздел `notifications`
3. Используйте endpoints с UI

---

## Troubleshooting

### Ошибка: "User doesn't have FCM token"
**Решение:** Пользователь должен войти в мобильное приложение хотя бы один раз, чтобы токен был сохранён.

### Ошибка: "Only admins and mechanics can use test endpoints"
**Решение:** Используйте токен пользователя с ролью ADMIN или MECHANIC.

### Push не приходит на устройство
**Решение:** 
1. Проверьте логи: `docker-compose logs -f back`
2. Убедитесь, что Expo токен валидный
3. Проверьте сетевое подключение (см. `FIX_PUSH_NOTIFICATIONS.md`)
4. Убедитесь, что приложение установлено и уведомления разрешены

### Timeout или ConnectError
**Решение:** См. документацию `FIX_PUSH_NOTIFICATIONS.md` и пересоберите контейнер с новыми настройками DNS.

---

## Безопасность

⚠️ **Важно:** Эти endpoints предназначены только для тестирования!

- Доступны только для `ADMIN` и `MECHANIC` ролей
- Не используйте в production без дополнительной защиты
- Рассмотрите возможность отключения в production через environment variable

Пример отключения в production:
```python
if os.getenv("ENABLE_TEST_ENDPOINTS", "false") == "true":
    # Регистрация тестовых endpoints
```

