# 🔍 Диагностика проблемы с Push-уведомлениями

## Текущая ситуация

Из скриншота видно:
- ✅ Запрос `/notifications/test_push_by_phone` выполнен успешно (200 OK)
- ❌ `"success": false` - Push НЕ отправлен
- ❌ `"message": "Failed to send push notification"`
- ✅ Пользователь найден: phone "71111111111"
- ✅ FCM токен есть: `ExponentPushToken[LlTmi6IZ6dUh...]`

**Вывод**: Проблема не в API endpoint, а в отправке через Expo Push Service.

---

## 🛠️ Шаги диагностики

### 1. Проверьте логи Docker контейнера

```bash
# Следить за логами в реальном времени
docker logs -f azv_motors_backend_v2-back-1

# Или последние 200 строк
docker logs --tail 200 azv_motors_backend_v2-back-1
```

**Что искать в логах:**
```
📱 Sending push to token: ExponentPushToken[...]
📤 Sending to Expo: {...}
📥 Expo response status: ...
📥 Expo response body: ...
```

### 2. Типичные ошибки и их причины

#### Ошибка: `DeviceNotRegistered`
```json
{
  "status": "error",
  "message": "\"ExponentPushToken[...]\" is not a registered push notification recipient"
}
```
**Решение**: Токен устарел или неверен. Пользователь должен заново войти в приложение.

#### Ошибка: `InvalidCredentials`
```json
{
  "status": "error",  
  "message": "Invalid credentials"
}
```
**Решение**: Неправильный Project ID. Проверьте что в `app.json` и `FirebaseMessagingService.ts` один и тот же project ID.

#### Ошибка: `Timeout` или `Network Error`
```
⏱️ Push timeout error
🌐 Push network error
```
**Решение**: Сервер не может достучаться до Expo API. Проверьте:
- Интернет-соединение на сервере
- Firewall не блокирует исходящие запросы к `exp.host` и `api.expo.dev`
- DNS работает корректно

---

## 🧪 Тестирование

### Тест 1: Прямой тест с сервера

Создан скрипт `test_push_direct.py` для прямой проверки:

```bash
# Войдите в контейнер
docker exec -it azv_motors_backend_v2-back-1 /bin/bash

# Или выполните напрямую
docker exec azv_motors_backend_v2-back-1 python3 test_push_direct.py "ExponentPushToken[LlTmi6IZ6dUh...]"
```

Этот скрипт:
- ✅ Проверяет сетевое подключение
- ✅ Отправляет тестовый push напрямую в Expo API
- ✅ Показывает детальные логи

### Тест 2: Проверка сети из контейнера

```bash
# Войдите в контейнер
docker exec -it azv_motors_backend_v2-back-1 /bin/bash

# Проверьте DNS
ping -c 3 exp.host
ping -c 3 api.expo.dev

# Проверьте HTTP доступ
curl -v https://exp.host/--/api/v2/push/send

# Попробуйте отправить тестовый push
curl -X POST "https://exp.host/--/api/v2/push/send" \
  -H "Content-Type: application/json" \
  -d '{
    "to": "ExponentPushToken[LlTmi6IZ6dUh...]",
    "title": "Test",
    "body": "Testing from curl"
  }'
```

### Тест 3: Проверка через Python в контейнере

```bash
docker exec -it azv_motors_backend_v2-back-1 python3 -c "
import httpx
import asyncio

async def test():
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get('https://exp.host')
            print(f'✅ exp.host доступен: {r.status_code}')
        except Exception as e:
            print(f'❌ Ошибка: {e}')

asyncio.run(test())
"
```

---

## 🔧 Возможные решения

### Решение 1: Проверьте httpx версию

```bash
docker exec azv_motors_backend_v2-back-1 pip list | grep httpx
```

Если версия старая, обновите:
```bash
docker exec azv_motors_backend_v2-back-1 pip install --upgrade httpx
```

### Решение 2: Увеличьте timeout

В файле `app/push/utils.py` уже установлены большие timeout'ы (30 секунд), но можно еще увеличить.

### Решение 3: Проверьте Firewall

Убедитесь что сервер может делать исходящие HTTPS запросы:

```bash
# На хост-машине (не в контейнере)
sudo iptables -L -n | grep DROP
sudo ufw status
```

Если есть блокировка, разрешите:
```bash
sudo ufw allow out to any port 443
```

### Решение 4: Используйте альтернативный endpoint

В `app/push/utils.py` уже есть два URL:
- `https://exp.host/--/api/v2/push/send` (primary)
- `https://api.expo.dev/v2/push/send` (fallback)

Попробуйте поменять их местами.

---

## 📊 Проверка результата

После исправления, повторите запрос:

```bash
curl -X POST 'https://api.azvmotors.kz/notifications/test_push_by_phone' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "phone": "71111111111",
    "title": "Тест после исправления",
    "body": "Проверка работы push-уведомлений"
  }'
```

Должны увидеть:
```json
{
  "success": true,
  "message": "Push notification sent successfully"
}
```

И в логах:
```
✅ Expo push sent successfully: <ticket-id>
```

---

## 🆘 Если ничего не помогает

1. Проверьте что Expo Push Service работает:
   - https://status.expo.dev/

2. Попробуйте отправить push через Expo web tool:
   - https://expo.dev/notifications

3. Проверьте квоты Expo (есть ли лимиты):
   - Бесплатный план: без ограничений, но с rate limits

4. Соберите полные логи и отправьте:
```bash
docker logs azv_motors_backend_v2-back-1 > push_logs.txt
```

