#!/bin/bash

# для проверки общего статуса системы
# Использование: ./system_status.sh

echo "=== СТАТУС СИСТЕМЫ AZV MOTORS ==="
echo "Время: $(date)"
echo

# 1. Статус контейнеров
echo "1. СТАТУС DOCKER КОНТЕЙНЕРОВ:"
echo "================================"
docker ps --filter "name=azv_motors" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo

# 2. Статус базы данных
echo "2. СТАТУС БАЗЫ ДАННЫХ:"
echo "================================"
bash check_db.sh
echo

# 3. Статус миграций и бэкапов
echo "3. СТАТУС МИГРАЦИЙ И БЭКАПОВ:"
echo "================================"
bash check_migrations.sh
echo

# 4. Использование дискового пространства
echo "4. ИСПОЛЬЗОВАНИЕ ДИСКОВОГО ПРОСТРАНСТВА:"
echo "================================"
echo "Общее использование:"
df -h | grep -E "(Filesystem|/dev/)"
echo

echo "Использование в текущей директории:"
du -sh . 2>/dev/null
echo

# 5. Статус приложения
echo "5. СТАТУС ПРИЛОЖЕНИЯ:"
echo "================================"
echo "Проверка доступности API..."
if curl -s http://localhost:7138/health > /dev/null 2>&1; then
    echo "API доступен на порту 7138"
else
    echo "API недоступен на порту 7138"
fi
echo

# 6. Последние логи
echo "6. ПОСЛЕДНИЕ ЛОГИ ПРИЛОЖЕНИЯ:"
echo "================================"
docker logs azv_motors_backend-back-1 --tail 10 2>/dev/null || echo "Логи недоступны"
echo

echo "=== ПРОВЕРКА ЗАВЕРШЕНА ==="
