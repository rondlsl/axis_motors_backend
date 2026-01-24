#!/bin/bash

# Скрипт для резервного копирования базы данных PostgreSQL с загрузкой в MinIO
# Использование: ./backup_database.sh [тип_бэкапа] [период]
# Типы: full, incremental, schema-only
# Периоды: daily, weekly, monthly, manual

# Загружаем переменные из .env файла (если есть)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -f "$PROJECT_ROOT/.env" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${line// }" ]] && continue
        if [[ "$line" =~ ^[[:space:]]*(POSTGRES_|MINIO_)[A-Z_]+=(.*)$ ]]; then
            eval "export $line" 2>/dev/null || true
        fi
    done < "$PROJECT_ROOT/.env"
fi

# Database configuration
DB_HOST="${POSTGRES_HOST:-db}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_NAME="${POSTGRES_DB:-postgres}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_PASSWORD="${POSTGRES_PASSWORD}"

# MinIO configuration
MINIO_ENDPOINT="${MINIO_ENDPOINT:-https://msmain.azvmotors.kz}"
MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-minio_admin}"
MINIO_SECRET_KEY="${MINIO_SECRET_KEY}"
MINIO_BUCKET="${MINIO_BUCKET_BACKUPS:-backups}"
MINIO_ALIAS="azvminio_backup"

# Temporary local directory for creating backups
TEMP_BACKUP_DIR="/tmp/azv_backups"

USE_DOCKER=true
if ! command -v docker >/dev/null 2>&1; then
    USE_DOCKER=false
    if ! command -v pg_dump >/dev/null 2>&1; then
        echo "Ошибка: не найден docker и не найден pg_dump"
        exit 1
    fi
    echo "Docker не найден, используется локальный pg_dump (host: $DB_HOST)"
else
    DOCKER_CONTAINER=$(docker ps --filter "name=azv_motors_backend_v2-db-1" --format "{{.Names}}" | head -1)
    if [ -z "$DOCKER_CONTAINER" ]; then
        DOCKER_CONTAINER=$(docker ps --filter "name=db" --filter "ancestor=postgres" --format "{{.Names}}" | head -1)
    fi
    if [ -z "$DOCKER_CONTAINER" ]; then
        DOCKER_CONTAINER=$(docker ps --filter "ancestor=postgres" --format "{{.Names}}" | head -1)
    fi
    if [ -z "$DOCKER_CONTAINER" ]; then
        echo "Ошибка: Контейнер PostgreSQL не найден"
        echo "Доступные контейнеры PostgreSQL:"
        docker ps --filter "ancestor=postgres" --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
        exit 1
    fi
    echo "Используется контейнер: $DOCKER_CONTAINER"
fi

run_pg_dump() {
    if [ "$USE_DOCKER" = "true" ]; then
        docker exec "$DOCKER_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" "$@"
    else
        PGPASSWORD="$DB_PASSWORD" pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" "$@"
    fi
}

# Retention periods
RETENTION_DAYS=30
RETENTION_WEEKS=12
RETENTION_MONTHS=12

BACKUP_TYPE=${1:-"full"}
BACKUP_PERIOD=${2:-"daily"}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Setup MinIO client
setup_minio_client() {
    echo "Настройка MinIO клиента..."
    
    # Check if mc is installed
    if ! command -v mc >/dev/null 2>&1; then
        echo "MinIO Client не установлен, скачиваю..."
        curl -sL https://dl.min.io/client/mc/release/linux-amd64/mc -o /tmp/mc
        chmod +x /tmp/mc
        MC_CMD="/tmp/mc"
    else
        MC_CMD="mc"
    fi
    
    # Configure alias
    $MC_CMD alias set "$MINIO_ALIAS" "$MINIO_ENDPOINT" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" --api S3v4 >/dev/null 2>&1
    
    if [ $? -ne 0 ]; then
        echo "Ошибка: Не удалось настроить подключение к MinIO"
        exit 1
    fi
    
    echo "✅ MinIO клиент настроен"
}

# Upload backup to MinIO
upload_to_minio() {
    local filepath="$1"
    local filename=$(basename "$filepath")
    local minio_path="$MINIO_ALIAS/$MINIO_BUCKET/$BACKUP_PERIOD/$filename"
    
    echo "Загрузка в MinIO: $minio_path"
    
    if $MC_CMD cp "$filepath" "$minio_path" >/dev/null 2>&1; then
        echo "✅ Backup загружен в MinIO: $MINIO_ENDPOINT/$MINIO_BUCKET/$BACKUP_PERIOD/$filename"
        
        # Remove local temp file after successful upload
        rm -f "$filepath"
        echo "✅ Локальный временный файл удалён"
        return 0
    else
        echo "❌ Ошибка загрузки в MinIO"
        return 1
    fi
}

# Cleanup old backups in MinIO
cleanup_old_backups_minio() {
    echo "Очистка старых бэкапов в MinIO..."
    
    local retention_days
    case "$BACKUP_PERIOD" in
        "daily")
            retention_days=$RETENTION_DAYS
            ;;
        "weekly")
            retention_days=$((RETENTION_WEEKS * 7))
            ;;
        "monthly")
            retention_days=$((RETENTION_MONTHS * 30))
            ;;
        *)
            retention_days=$RETENTION_DAYS
            ;;
    esac
    
    # List and delete old files
    local cutoff_date=$(date -d "-${retention_days} days" +%Y%m%d 2>/dev/null || date -v-${retention_days}d +%Y%m%d 2>/dev/null)
    
    if [ -n "$cutoff_date" ]; then
        local deleted_count=0
        
        # Get list of files older than retention period
        while IFS= read -r line; do
            # Extract filename and check date
            local file_date=$(echo "$line" | grep -oE 'backup_[a-z]+_([0-9]{8})' | grep -oE '[0-9]{8}')
            if [ -n "$file_date" ] && [ "$file_date" -lt "$cutoff_date" ]; then
                local file_path=$(echo "$line" | awk '{print $NF}')
                if [ -n "$file_path" ]; then
                    $MC_CMD rm "$MINIO_ALIAS/$MINIO_BUCKET/$BACKUP_PERIOD/$file_path" >/dev/null 2>&1
                    ((deleted_count++))
                fi
            fi
        done < <($MC_CMD ls "$MINIO_ALIAS/$MINIO_BUCKET/$BACKUP_PERIOD/" 2>/dev/null | grep "\.sql\.gz")
        
        if [ "$deleted_count" -gt 0 ]; then
            echo "Удалено старых бэкапов: $deleted_count"
        else
            echo "Старые бэкапы не найдены"
        fi
    fi
    
    echo "Очистка завершена"
}

# Create temp directory
mkdir -p "$TEMP_BACKUP_DIR"

validate_backup() {
    local filepath="$1"
    
    if [ ! -f "$filepath" ]; then
        echo "Ошибка: Файл backup не создан: $filepath"
        return 1
    fi
    
    local file_size=$(stat -f%z "$filepath" 2>/dev/null || stat -c%s "$filepath" 2>/dev/null)
    if [ "$file_size" -eq 0 ]; then
        echo "Ошибка: Файл backup пустой: $filepath"
        rm -f "$filepath"
        return 1
    fi
    
    if ! gzip -t "$filepath" 2>/dev/null; then
        echo "Ошибка: Backup файл поврежден (gzip test failed): $filepath"
        return 1
    fi
    
    return 0
}

create_full_backup() {
    local filename="backup_full_${TIMESTAMP}.sql.gz"
    local filepath="$TEMP_BACKUP_DIR/$filename"
    
    echo "Создание полного бэкапа: $filename"
    echo "Время начала: $(date '+%Y-%m-%d %H:%M:%S')"
    
    local temp_filepath="${filepath}.tmp"
    rm -f "$temp_filepath"
    
    if ! run_pg_dump \
        --no-password \
        --format=plain \
        --create \
        --clean \
        --if-exists \
        --exclude-table-data='alembic_version' 2>/dev/null | gzip > "$temp_filepath"; then
        echo "Ошибка при создании полного бэкапа"
        rm -f "$temp_filepath"
        exit 1
    fi
    
    local dump_exit_code=${PIPESTATUS[0]:-0}
    local gzip_exit_code=${PIPESTATUS[1]:-0}
    
    if [ ${dump_exit_code} -ne 0 ]; then
        echo "Ошибка: pg_dump завершился с кодом $dump_exit_code"
        rm -f "$temp_filepath"
        exit 1
    fi
    
    if [ ${gzip_exit_code} -ne 0 ]; then
        echo "Ошибка: gzip завершился с кодом $gzip_exit_code"
        rm -f "$temp_filepath"
        exit 1
    fi
    
    if ! mv "$temp_filepath" "$filepath"; then
        echo "Ошибка: Не удалось переименовать временный файл"
        rm -f "$temp_filepath"
        exit 1
    fi
    
    if ! validate_backup "$filepath"; then
        exit 1
    fi
    
    local file_size=$(du -h "$filepath" | cut -f1)
    echo "Полный бэкап создан: $filepath"
    echo "Размер файла: $file_size"
    
    # Upload to MinIO
    upload_to_minio "$filepath"
    
    echo "Время завершения: $(date '+%Y-%m-%d %H:%M:%S')"
}

create_incremental_backup() {
    local filename="backup_incremental_${TIMESTAMP}.sql.gz"
    local filepath="$TEMP_BACKUP_DIR/$filename"
    local temp_filepath="${filepath}.tmp"
    
    echo "Создание инкрементального бэкапа: $filename"
    echo "Время начала: $(date '+%Y-%m-%d %H:%M:%S')"
    
    rm -f "$temp_filepath"
    
    if ! run_pg_dump \
        --no-password \
        --data-only \
        --inserts \
        --exclude-table='alembic_version' 2>/dev/null | gzip > "$temp_filepath"; then
        echo "Ошибка при создании инкрементального бэкапа"
        rm -f "$temp_filepath"
        exit 1
    fi
    
    local dump_exit_code=${PIPESTATUS[0]:-0}
    local gzip_exit_code=${PIPESTATUS[1]:-0}
    
    if [ ${dump_exit_code} -ne 0 ] || [ ${gzip_exit_code} -ne 0 ]; then
        echo "Ошибка при создании инкрементального бэкапа (pg_dump: $dump_exit_code, gzip: $gzip_exit_code)"
        rm -f "$temp_filepath"
        exit 1
    fi
    
    if ! mv "$temp_filepath" "$filepath"; then
        echo "Ошибка: Не удалось переименовать временный файл"
        rm -f "$temp_filepath"
        exit 1
    fi
    
    if ! validate_backup "$filepath"; then
        exit 1
    fi
    
    local file_size=$(du -h "$filepath" | cut -f1)
    echo "Инкрементальный бэкап создан: $filepath"
    echo "Размер файла: $file_size"
    
    # Upload to MinIO
    upload_to_minio "$filepath"
    
    echo "Время завершения: $(date '+%Y-%m-%d %H:%M:%S')"
}

create_schema_backup() {
    local filename="backup_schema_${TIMESTAMP}.sql.gz"
    local filepath="$TEMP_BACKUP_DIR/$filename"
    local temp_filepath="${filepath}.tmp"
    
    echo "Создание бэкапа схемы: $filename"
    echo "Время начала: $(date '+%Y-%m-%d %H:%M:%S')"
    
    rm -f "$temp_filepath"
    
    if ! run_pg_dump \
        --no-password \
        --schema-only \
        --create \
        --clean \
        --if-exists 2>/dev/null | gzip > "$temp_filepath"; then
        echo "Ошибка при создании бэкапа схемы"
        rm -f "$temp_filepath"
        exit 1
    fi
    
    local dump_exit_code=${PIPESTATUS[0]:-0}
    local gzip_exit_code=${PIPESTATUS[1]:-0}
    
    if [ ${dump_exit_code} -ne 0 ] || [ ${gzip_exit_code} -ne 0 ]; then
        echo "Ошибка при создании бэкапа схемы (pg_dump: $dump_exit_code, gzip: $gzip_exit_code)"
        rm -f "$temp_filepath"
        exit 1
    fi
    
    if ! mv "$temp_filepath" "$filepath"; then
        echo "Ошибка: Не удалось переименовать временный файл"
        rm -f "$temp_filepath"
        exit 1
    fi
    
    if ! validate_backup "$filepath"; then
        exit 1
    fi
    
    local file_size=$(du -h "$filepath" | cut -f1)
    echo "Бэкап схемы создан: $filepath"
    echo "Размер файла: $file_size"
    
    # Upload to MinIO
    upload_to_minio "$filepath"
    
    echo "Время завершения: $(date '+%Y-%m-%d %H:%M:%S')"
}

# Setup MinIO client first
setup_minio_client

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

cleanup_old_backups_minio

echo ""
echo "=== Статистика backup'ов в MinIO ==="
echo "Bucket: $MINIO_BUCKET/$BACKUP_PERIOD"
echo "Количество файлов: $($MC_CMD ls "$MINIO_ALIAS/$MINIO_BUCKET/$BACKUP_PERIOD/" 2>/dev/null | grep "\.sql\.gz" | wc -l | tr -d ' ')"
echo "Список файлов:"
$MC_CMD ls "$MINIO_ALIAS/$MINIO_BUCKET/$BACKUP_PERIOD/" 2>/dev/null | grep "\.sql\.gz" | tail -5
echo ""

# Cleanup temp directory
rm -rf "$TEMP_BACKUP_DIR"

echo "✅ Бэкап завершен успешно!"
