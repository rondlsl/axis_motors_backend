# Инструкции по развертыванию изменений

## После запуска `docker compose up -d --build`

### 1. Применить миграцию базы данных

```bash
# Войти в контейнер с приложением
docker exec -it azv_motors_backend-back-1 bash

# Применить миграцию
alembic upgrade head
```

### 2. Проверить статус миграций

```bash
# Проверить текущую версию
alembic current

# Проверить историю миграций
alembic history
```

### 3. Проверить логи приложения

```bash
# Проверить логи backend
docker compose logs back

# Проверить логи в реальном времени
docker compose logs -f back
```

## Что изменилось

### Модели базы данных:
- `users.full_name` → `users.first_name` + `users.last_name`
- `guarantor_requests.guarantor_name` → `guarantor_requests.guarantor_first_name` + `guarantor_requests.guarantor_last_name`

### API изменения:
- Все API endpoints теперь возвращают разделенные имена
- Swagger документация обновлена
- SMS отправляется с правильным форматом имени

### Проверка работы:
1. Проверить Swagger документацию: `http://your-server:8000/docs`
2. Протестировать API гарантов
3. Проверить отправку SMS
4. Проверить регистрацию пользователей

## Откат изменений (если нужно)

```bash
# Откатить миграцию
alembic downgrade -1

# Или откатить до конкретной версии
alembic downgrade <revision_id>
```
