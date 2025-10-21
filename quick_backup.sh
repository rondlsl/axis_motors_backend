#!/bin/bash

# для создания бэкапа
# Использование: ./quick_backup.sh

echo "Создание быстрого бэкапа AZV Motors DB..."

mkdir -p backups/manual

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="backups/manual/quick_backup_${TIMESTAMP}.sql.gz"

echo "Создание бэкапа: $BACKUP_FILE"

# Определяем контейнер для текущего проекта
DOCKER_CONTAINER=$(docker ps --filter "name=azv_motors_backend-db-1" --format "{{.Names}}" | head -1)
if [ -z "$DOCKER_CONTAINER" ]; then
    echo "Ошибка: Контейнер PostgreSQL для azv_motors_backend не найден"
    echo "Доступные контейнеры PostgreSQL:"
    docker ps --filter "ancestor=postgres" --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
    exit 1
fi
echo "Используется контейнер: $DOCKER_CONTAINER"

docker exec "$DOCKER_CONTAINER" pg_dump -U postgres -d postgres \
    --verbose \
    --no-password \
    --format=plain \
    --create \
    --clean \
    --if-exists | gzip > "$BACKUP_FILE"

if [ $? -eq 0 ]; then
    echo "Бэкап создан успешно!"
    echo "Файл: $BACKUP_FILE"
    echo "Размер: $(du -h "$BACKUP_FILE" | cut -f1)"
    echo "Время: $(date)"
else
    echo "Ошибка при создании бэкапа"
    exit 1
fi
