# Исправление проблем с Push-уведомлениями

## Проблема

Push-уведомления не отправляются из-за сетевых ошибок:
- `Timeout while connecting to Expo Push Service`
- `ConnectError: [Errno -5] No address associated with hostname`

## Причины

1. **DNS проблемы** - Docker контейнер не может разрешить имя хоста `exp.host`
2. **Сетевые ограничения** - блокировка исходящих соединений
3. **Таймауты** - слишком короткий таймаут для соединения

## Что было исправлено

### 1. Обновлен код отправки push-уведомлений (`app/push/utils.py`)

✅ **Увеличены таймауты:**
- Таймаут подключения: 10s → 30s
- Таймаут чтения: 10s → 30s
- Таймаут записи: добавлен 30s

✅ **Добавлена retry логика:**
- Максимум 3 попытки отправки
- Exponential backoff: 1s, 2s, 4s между попытками
- Автоматический retry при сетевых ошибках

✅ **Fallback endpoint:**
- Основной: `https://exp.host/--/api/v2/push/send`
- Запасной: `https://api.expo.dev/v2/push/send`

✅ **Лучшая обработка ошибок:**
- Отдельная обработка для TimeoutException
- Отдельная обработка для ConnectError/NetworkError
- Детальное логирование каждой попытки

### 2. Обновлен Docker Compose (`docker-compose.yml`)

✅ **Настроены DNS серверы:**
```yaml
dns:
  - 8.8.8.8  # Google DNS
  - 8.8.4.4  # Google DNS secondary
  - 1.1.1.1  # Cloudflare DNS
```

✅ **Создана кастомная сеть:**
```yaml
networks:
  app-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.25.0.0/16
```

## Как применить исправления

### Шаг 1: Пересоберите и перезапустите контейнеры

```bash
cd /Users/meyirman/Desktop/azv/azv_motors_backend

# Остановите контейнеры
docker-compose down

# Пересоберите образ с новыми изменениями
docker-compose build --no-cache

# Запустите контейнеры
docker-compose up -d

# Проверьте логи
docker-compose logs -f back
```

### Шаг 2: Проверьте DNS в контейнере

```bash
# Зайдите в контейнер
docker-compose exec back sh

# Проверьте DNS
cat /etc/resolv.conf

# Проверьте доступность Expo
ping -c 3 exp.host
ping -c 3 api.expo.dev

# Проверьте curl
curl -v https://exp.host/--/api/v2/push/send

# Выйдите из контейнера
exit
```

### Шаг 3: Тестирование

Попробуйте отправить push-уведомление и проверьте логи:

```bash
docker-compose logs -f back | grep -E "(📱|📤|📥|✅|❌|🔄|⏱️|🌐)"
```

## Дополнительные решения (если проблема сохраняется)

### Вариант 1: Использование host network (только для Linux)

```yaml
services:
  back:
    network_mode: host
```

⚠️ **Внимание:** Это не работает на macOS/Windows!

### Вариант 2: Проверка firewall/proxy

Если используется корпоративный firewall или proxy:

```yaml
services:
  back:
    environment:
      - HTTP_PROXY=http://your-proxy:port
      - HTTPS_PROXY=http://your-proxy:port
      - NO_PROXY=localhost,127.0.0.1,db
```

### Вариант 3: Добавление extra_hosts

```yaml
services:
  back:
    extra_hosts:
      - "exp.host:104.18.34.162"
      - "api.expo.dev:104.18.35.162"
```

⚠️ **Внимание:** IP адреса могут измениться!

### Вариант 4: Использование VPN/Tunnel (если заблокирован Expo)

Если Expo заблокирован в вашей стране/сети, рассмотрите:
- VPN в Docker контейнере
- Tunnel сервис (ngrok, cloudflared)
- Proxy сервер

## Мониторинг

Добавьте мониторинг успешности отправки:

```python
# В вашем коде
result = await send_push_notification_async(token, title, body)
if not result:
    # Логирование в файл/базу/мониторинг
    logger.error(f"Failed to send push to {token}")
```

## Поддержка

Если проблема не решена:
1. Проверьте логи Docker: `docker-compose logs back`
2. Проверьте сетевые настройки хоста
3. Убедитесь, что Expo не заблокирован
4. Попробуйте запустить без Docker для теста

