#!/bin/bash

# для резервного копирования базы данных PostgreSQL
# Использование: ./backup_database.sh [тип_бэкапа] [период]
# Типы: full, incremental, schema-only
# Периоды: daily, weekly, monthly, manual

DB_HOST="localhost"
DB_PORT="5432"
DB_NAME="postgres"
DB_USER="postgres"
BACKUP_DIR="../backups"
# Определяем контейнер для текущего проекта
DOCKER_CONTAINER=$(docker ps --filter "name=azv_motors_backend_v2-db-1" --format "{{.Names}}" | head -1)
if [ -z "$DOCKER_CONTAINER" ]; then
    echo "Ошибка: Контейнер PostgreSQL для azv_motors_backend_v2 не найден"
    echo "Доступные контейнеры PostgreSQL:"
    docker ps --filter "ancestor=postgres" --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
    exit 1
fi
echo "Используется контейнер: $DOCKER_CONTAINER"
RETENTION_DAYS=30
RETENTION_WEEKS=12
RETENTION_MONTHS=12

BACKUP_TYPE=${1:-"full"}
BACKUP_PERIOD=${2:-"daily"}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR/$BACKUP_PERIOD"

create_full_backup() {
    local filename="backup_full_${TIMESTAMP}.sql.gz"
    local filepath="$BACKUP_DIR/$BACKUP_PERIOD/$filename"
    
    echo "Создание полного бэкапа: $filepath"
    
    docker exec "$DOCKER_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" \
        --verbose \
        --no-password \
        --format=plain \
        --create \
        --clean \
        --if-exists \
        --exclude-table-data='alembic_version' | gzip > "$filepath"
    
    if [ $? -eq 0 ]; then
        echo "Полный бэкап создан: $filepath"
        echo "Размер файла: $(du -h "$filepath" | cut -f1)"
    else
        echo "Ошибка при создании полного бэкапа"
        exit 1
    fi
}

create_incremental_backup() {
    local filename="backup_incremental_${TIMESTAMP}.sql.gz"
    local filepath="$BACKUP_DIR/$BACKUP_PERIOD/$filename"
    
    echo "Создание инкрементального бэкапа: $filepath"
    
    docker exec "$DOCKER_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" \
        --verbose \
        --no-password \
        --data-only \
        --inserts \
        --exclude-table='alembic_version' | gzip > "$filepath"
    
    if [ $? -eq 0 ]; then
        echo "Инкрементальный бэкап создан: $filepath"
        echo "Размер файла: $(du -h "$filepath" | cut -f1)"
    else
        echo "Ошибка при создании инкрементального бэкапа"
        exit 1
    fi
}

create_schema_backup() {
    local filename="backup_schema_${TIMESTAMP}.sql.gz"
    local filepath="$BACKUP_DIR/$BACKUP_PERIOD/$filename"
    
    echo "Создание бэкапа схемы: $filepath"
    
    docker exec "$DOCKER_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" \
        --verbose \
        --no-password \
        --schema-only \
        --create \
        --clean \
        --if-exists | gzip > "$filepath"
    
    if [ $? -eq 0 ]; then
        echo "Бэкап схемы создан: $filepath"
        echo "Размер файла: $(du -h "$filepath" | cut -f1)"
    else
        echo "Ошибка при создании бэкапа схемы"
        exit 1
    fi
}

cleanup_old_backups() {
    echo "Очистка старых бэкапов..."
    
    case "$BACKUP_PERIOD" in
        "daily")
            find "$BACKUP_DIR/daily" -name "*.sql.gz" -mtime +$RETENTION_DAYS -delete 2>/dev/null
            ;;
        "weekly")
            find "$BACKUP_DIR/weekly" -name "*.sql.gz" -mtime +$((RETENTION_WEEKS * 7)) -delete 2>/dev/null
            ;;
        "monthly")
            find "$BACKUP_DIR/monthly" -name "*.sql.gz" -mtime +$((RETENTION_MONTHS * 30)) -delete 2>/dev/null
            ;;
    esac
    
    echo "Очистка завершена"
}

upload_to_cloud() {
    local filepath="$1"
    echo "Бэкап готов для загрузки в облако: $filepath"
}

case "$BACKUP_TYPE" in
    "full")
        create_full_backup
        ;;
    "incremental")
        create_incremental_backup
        ;;
    "schema")
        create_schema_backup
        ;;
    *)
        echo "Неизвестный тип бэкапа: $BACKUP_TYPE"
        echo "Доступные типы: full, incremental, schema"
        exit 1
        ;;
esac

cleanup_old_backups

echo "Бэкап завершен успешно!"
