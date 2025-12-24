#!/bin/bash

# для резервного копирования базы данных PostgreSQL
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
        if [[ "$line" =~ ^[[:space:]]*POSTGRES_(HOST|PORT|DB|USER|PASSWORD)=(.*)$ ]]; then
            eval "export $line" 2>/dev/null || true
        fi
    done < "$PROJECT_ROOT/.env"
fi

DB_HOST="${POSTGRES_HOST:-db}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_NAME="${POSTGRES_DB:-postgres}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_PASSWORD="${POSTGRES_PASSWORD}"

if [ -z "$BACKUP_DIR" ]; then
    BACKUP_DIR="$PROJECT_ROOT/backups"
else
    if [[ ! "$BACKUP_DIR" = /* ]]; then
        BACKUP_DIR="$PROJECT_ROOT/$BACKUP_DIR"
    fi
fi

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
RETENTION_DAYS=30
RETENTION_WEEKS=12
RETENTION_MONTHS=12

BACKUP_TYPE=${1:-"full"}
BACKUP_PERIOD=${2:-"daily"}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

if [ ! -d "$BACKUP_DIR" ]; then
    if ! mkdir -p "$BACKUP_DIR" 2>/dev/null; then
        if command -v sudo >/dev/null 2>&1 && [ "$(id -u)" != "0" ]; then
            echo "Попытка создать директорию через sudo..."
            if sudo mkdir -p "$BACKUP_DIR" 2>/dev/null; then
                sudo chown -R "$(whoami):$(whoami)" "$BACKUP_DIR" 2>/dev/null
                sudo chmod 755 "$BACKUP_DIR" 2>/dev/null
            else
                echo "Ошибка: Не удалось создать директорию $BACKUP_DIR"
                echo "Выполните вручную:"
                echo "  sudo mkdir -p $BACKUP_DIR"
                echo "  sudo chown -R \$(whoami):\$(whoami) $BACKUP_DIR"
                exit 1
            fi
        else
            echo "Ошибка: Не удалось создать директорию $BACKUP_DIR"
            exit 1
        fi
    fi
fi

if [ ! -d "$BACKUP_DIR/$BACKUP_PERIOD" ]; then
    if ! mkdir -p "$BACKUP_DIR/$BACKUP_PERIOD" 2>/dev/null; then
        if command -v sudo >/dev/null 2>&1 && [ "$(id -u)" != "0" ]; then
            echo "Попытка создать директорию через sudo..."
            if sudo mkdir -p "$BACKUP_DIR/$BACKUP_PERIOD" 2>/dev/null; then
                sudo chown -R "$(whoami):$(whoami)" "$BACKUP_DIR" 2>/dev/null
                sudo chmod -R 755 "$BACKUP_DIR" 2>/dev/null
            else
                echo "Ошибка: Не удалось создать директорию $BACKUP_DIR/$BACKUP_PERIOD"
                echo "Текущий пользователь: $(whoami)"
                echo "Права на родительскую директорию:"
                ls -ld "$BACKUP_DIR" 2>/dev/null || echo "  (не удалось получить информацию)"
                echo ""
                echo "Выполните вручную:"
                echo "  sudo mkdir -p $BACKUP_DIR/$BACKUP_PERIOD"
                echo "  sudo chown -R \$(whoami):\$(whoami) $BACKUP_DIR"
                exit 1
            fi
        else
            echo "Ошибка: Не удалось создать директорию $BACKUP_DIR/$BACKUP_PERIOD"
            exit 1
        fi
    fi
fi

if [ ! -w "$BACKUP_DIR/$BACKUP_PERIOD" ]; then
    echo "Нет прав на запись в директорию $BACKUP_DIR/$BACKUP_PERIOD"
    echo "Текущий пользователь: $(whoami)"
    echo "Владелец директории: $(stat -c '%U:%G' "$BACKUP_DIR/$BACKUP_PERIOD" 2>/dev/null || echo 'неизвестно')"
    
    if command -v sudo >/dev/null 2>&1 && [ "$(id -u)" != "0" ]; then
        echo "Попытка исправить права доступа через sudo..."
        if sudo chown -R "$(whoami):$(whoami)" "$BACKUP_DIR" 2>/dev/null && \
           sudo chmod -R 755 "$BACKUP_DIR" 2>/dev/null; then
            echo "Права доступа успешно исправлены"
        else
            echo "Ошибка: Не удалось исправить права доступа"
            echo "Выполните вручную:"
            echo "  sudo chown -R \$(whoami):\$(whoami) $BACKUP_DIR"
            echo "  sudo chmod -R 755 $BACKUP_DIR"
            exit 1
        fi
    else
        echo "Ошибка: Нет прав на запись и невозможно исправить автоматически"
        echo "Выполните вручную:"
        echo "  chown -R \$(whoami):\$(whoami) $BACKUP_DIR"
        echo "  chmod -R 755 $BACKUP_DIR"
        exit 1
    fi
fi

check_disk_space() {
    local available_space=$(df "$BACKUP_DIR" | tail -1 | awk '{print $4}')
    local min_space_kb=1048576  
    
    if [ "$available_space" -lt "$min_space_kb" ]; then
        echo "ВНИМАНИЕ: Мало свободного места на диске: $(df -h "$BACKUP_DIR" | tail -1 | awk '{print $4}')"
        echo "Рекомендуется освободить место перед созданием backup"
        return 1
    fi
    return 0
}

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
    local filepath="$BACKUP_DIR/$BACKUP_PERIOD/$filename"
    
    echo "Создание полного бэкапа: $filepath"
    echo "Время начала: $(date '+%Y-%m-%d %H:%M:%S')"
    
    if ! check_disk_space; then
        echo "Продолжаем создание backup несмотря на предупреждение..."
    fi
    
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
    
    if [ ${dump_exit_code} -ne 0 ]; then
        echo "Ошибка при создании полного бэкапа (pg_dump exit code: $dump_exit_code)"
        rm -f "$filepath"
        exit 1
    fi
    
    if ! validate_backup "$filepath"; then
        exit 1
    fi
    
    local file_size=$(du -h "$filepath" | cut -f1)
    echo "Полный бэкап создан успешно: $filepath"
    echo "Размер файла: $file_size"
    echo "Время завершения: $(date '+%Y-%m-%d %H:%M:%S')"
}

create_incremental_backup() {
    local filename="backup_incremental_${TIMESTAMP}.sql.gz"
    local filepath="$BACKUP_DIR/$BACKUP_PERIOD/$filename"
    local temp_filepath="${filepath}.tmp"
    
    echo "Создание инкрементального бэкапа: $filepath"
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
    echo "Инкрементальный бэкап создан успешно: $filepath"
    echo "Размер файла: $file_size"
    echo "Время завершения: $(date '+%Y-%m-%d %H:%M:%S')"
}

create_schema_backup() {
    local filename="backup_schema_${TIMESTAMP}.sql.gz"
    local filepath="$BACKUP_DIR/$BACKUP_PERIOD/$filename"
    local temp_filepath="${filepath}.tmp"
    
    echo "Создание бэкапа схемы: $filepath"
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
    echo "Бэкап схемы создан успешно: $filepath"
    echo "Размер файла: $file_size"
    echo "Время завершения: $(date '+%Y-%m-%d %H:%M:%S')"
}

cleanup_old_backups() {
    echo "Очистка старых бэкапов..."
    
    local deleted_count=0
    case "$BACKUP_PERIOD" in
        "daily")
            deleted_count=$(find "$BACKUP_DIR/daily" -name "*.sql.gz" -mtime +$RETENTION_DAYS -delete -print 2>/dev/null | wc -l | tr -d ' ')
            ;;
        "weekly")
            deleted_count=$(find "$BACKUP_DIR/weekly" -name "*.sql.gz" -mtime +$((RETENTION_WEEKS * 7)) -delete -print 2>/dev/null | wc -l | tr -d ' ')
            ;;
        "monthly")
            deleted_count=$(find "$BACKUP_DIR/monthly" -name "*.sql.gz" -mtime +$((RETENTION_MONTHS * 30)) -delete -print 2>/dev/null | wc -l | tr -d ' ')
            ;;
    esac
    
    if [ "$deleted_count" -gt 0 ]; then
        echo "Удалено старых бэкапов: $deleted_count"
    else
        echo "Старые бэкапы не найдены"
    fi
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

echo ""
echo "=== Статистика backup'ов ==="
echo "Директория: $BACKUP_DIR/$BACKUP_PERIOD"
echo "Количество файлов: $(find "$BACKUP_DIR/$BACKUP_PERIOD" -name "*.sql.gz" 2>/dev/null | wc -l | tr -d ' ')"
echo "Общий размер: $(du -sh "$BACKUP_DIR/$BACKUP_PERIOD" 2>/dev/null | cut -f1)"
echo ""

echo "Бэкап завершен успешно!"
