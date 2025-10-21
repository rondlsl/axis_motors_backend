#!/bin/bash

# для проверки статуса планировщика бэкапов
# Использование: ./check_scheduler.sh

echo "=== ПРОВЕРКА СТАТУСА ПЛАНИРОВЩИКА БЭКАПОВ ==="
echo

# Определяем контейнер приложения
DOCKER_CONTAINER=$(docker ps --filter "name=azv_motors_backend_v2-back-1" --format "{{.Names}}" | head -1)
if [ -z "$DOCKER_CONTAINER" ]; then
    echo "Ошибка: Контейнер приложения azv_motors_backend_v2 не найден"
    exit 1
fi

echo "Используется контейнер: $DOCKER_CONTAINER"
echo

# 1. Проверка процессов планировщика в контейнере
echo "1. ПРОЦЕССЫ ПЛАНИРОВЩИКА В КОНТЕЙНЕРЕ:"
echo "================================"
docker exec "$DOCKER_CONTAINER" ps aux | grep backup_schedule.py | grep -v grep || echo "Планировщик не запущен в контейнере"
echo

# 2. Проверка процессов планировщика на хосте
echo "2. ПРОЦЕССЫ ПЛАНИРОВЩИКА НА ХОСТЕ:"
echo "================================"
ps aux | grep backup_schedule.py | grep -v grep || echo "Планировщик не запущен на хосте"
echo

# 3. Проверка логов планировщика
echo "3. ЛОГИ ПЛАНИРОВЩИКА:"
echo "================================"
if docker exec "$DOCKER_CONTAINER" test -f /app/backup_scheduler.log; then
    echo "Последние 10 записей из лога планировщика:"
    docker exec "$DOCKER_CONTAINER" tail -10 /app/backup_scheduler.log
else
    echo "Лог планировщика не найден в контейнере"
fi
echo

# 4. Проверка установленных зависимостей
echo "4. ЗАВИСИМОСТИ ПЛАНИРОВЩИКА:"
echo "================================"
echo "Проверка APScheduler:"
docker exec "$DOCKER_CONTAINER" python -c "import apscheduler; print('APScheduler установлен:', apscheduler.__version__)" 2>/dev/null || echo "APScheduler не установлен"
echo

# 5. Проверка доступности скриптов в контейнере
echo "5. СКРИПТЫ В КОНТЕЙНЕРЕ:"
echo "================================"
echo "backup_schedule.py:"
docker exec "$DOCKER_CONTAINER" test -f /app/backup_schedule.py && echo "✅ Найден" || echo "❌ Не найден"
echo "backup_database.sh:"
docker exec "$DOCKER_CONTAINER" test -f /app/backup_database.sh && echo "✅ Найден" || echo "❌ Не найден"
echo "requirements_backup.txt:"
docker exec "$DOCKER_CONTAINER" test -f /app/requirements_backup.txt && echo "✅ Найден" || echo "❌ Не найден"
echo

# 6. Проверка последних бэкапов
echo "6. ПОСЛЕДНИЕ БЭКАПЫ:"
echo "================================"
echo "Ежедневные бэкапы:"
ls -la backups/daily/ 2>/dev/null | tail -3 || echo "Нет ежедневных бэкапов"
echo

echo "Еженедельные бэкапы:"
ls -la backups/weekly/ 2>/dev/null | tail -3 || echo "Нет еженедельных бэкапов"
echo

echo "Ежемесячные бэкапы:"
ls -la backups/monthly/ 2>/dev/null | tail -3 || echo "Нет ежемесячных бэкапов"
echo

echo "Ручные бэкапы:"
ls -la backups/manual/ 2>/dev/null | tail -3 || echo "Нет ручных бэкапов"
echo

# 7. Проверка cron задач
echo "7. CRON ЗАДАЧИ:"
echo "================================"
crontab -l 2>/dev/null | grep -i backup || echo "Нет cron задач для бэкапов"
echo

echo "=== ПРОВЕРКА ЗАВЕРШЕНА ==="
