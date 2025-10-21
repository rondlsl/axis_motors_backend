#!/bin/bash

# для восстановления базы данных PostgreSQL из бэкапа
# Использование: ./restore_database.sh [путь_к_файлу_бэкапа] [новая_имя_бд]

DB_HOST="localhost"
DB_PORT="5432"
DB_USER="postgres"
DEFAULT_DB_NAME="azv_motors_db_restored"
# Определяем контейнер для текущего проекта
DOCKER_CONTAINER=$(docker ps --filter "name=azv_motors_backend-db-1" --format "{{.Names}}" | head -1)
if [ -z "$DOCKER_CONTAINER" ]; then
    echo "Ошибка: Контейнер PostgreSQL для azv_motors_backend не найден"
    echo "Доступные контейнеры PostgreSQL:"
    docker ps --filter "ancestor=postgres" --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
    exit 1
fi
echo "Используется контейнер: $DOCKER_CONTAINER"

BACKUP_FILE="$1"
NEW_DB_NAME="${2:-$DEFAULT_DB_NAME}"

if [ -z "$BACKUP_FILE" ]; then
    echo "Ошибка: Укажите путь к файлу бэкапа"
    echo "Использование: $0 <путь_к_файлу_бэкапа> [новая_имя_бд]"
    exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "Ошибка: Файл бэкапа не найден: $BACKUP_FILE"
    exit 1
fi

echo "Восстановление базы данных из файла: $BACKUP_FILE"
echo "Новая база данных: $NEW_DB_NAME"

create_database() {
    echo "Создание новой базы данных: $NEW_DB_NAME"
    
    docker exec "$DOCKER_CONTAINER" dropdb -U "$DB_USER" --if-exists "$NEW_DB_NAME"
    
    docker exec "$DOCKER_CONTAINER" createdb -U "$DB_USER" "$NEW_DB_NAME"
    
    if [ $? -eq 0 ]; then
        echo "База данных создана: $NEW_DB_NAME"
    else
        echo "Ошибка при создании базы данных"
        exit 1
    fi
}

restore_from_gzip() {
    echo "Восстановление из сжатого файла..."
    
    gunzip -c "$BACKUP_FILE" | docker exec -i "$DOCKER_CONTAINER" psql -U "$DB_USER" -d "$NEW_DB_NAME"
    
    if [ $? -eq 0 ]; then
        echo "База данных восстановлена из сжатого файла"
    else
        echo "Ошибка при восстановлении из сжатого файла"
        exit 1
    fi
}

restore_from_plain() {
    echo "Восстановление из обычного файла..."
    
    docker exec -i "$DOCKER_CONTAINER" psql -U "$DB_USER" -d "$NEW_DB_NAME" < "$BACKUP_FILE"
    
    if [ $? -eq 0 ]; then
        echo "База данных восстановлена из обычного файла"
    else
        echo "Ошибка при восстановлении из обычного файла"
        exit 1
    fi
}

verify_restore() {
    echo "Проверка восстановления..."
 
    TABLE_COUNT=$(docker exec "$DOCKER_CONTAINER" psql -U "$DB_USER" -d "$NEW_DB_NAME" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" | xargs)
    
    USER_COUNT=$(docker exec "$DOCKER_CONTAINER" psql -U "$DB_USER" -d "$NEW_DB_NAME" -t -c "SELECT COUNT(*) FROM users;" 2>/dev/null | xargs || echo "0")
    CAR_COUNT=$(docker exec "$DOCKER_CONTAINER" psql -U "$DB_USER" -d "$NEW_DB_NAME" -t -c "SELECT COUNT(*) FROM cars;" 2>/dev/null | xargs || echo "0")
    
    echo "Статистика восстановления:"
    echo "Таблиц: $TABLE_COUNT"
    echo "Пользователей: $USER_COUNT"
    echo "Автомобилей: $CAR_COUNT"
    
    if [ "$TABLE_COUNT" -gt 0 ]; then
        echo "Восстановление прошло успешно"
    else
        echo "Ошибка: Таблицы не найдены"
        exit 1
    fi
}

echo "ВНИМАНИЕ: Этот процесс удалит существующую базу данных '$NEW_DB_NAME' если она есть!"
read -p "Продолжить? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Отменено пользователем"
    exit 1
fi

create_database

if [[ "$BACKUP_FILE" == *.gz ]]; then
    restore_from_gzip
else
    restore_from_plain
fi

verify_restore

echo "Восстановление завершено успешно!"
echo "База данных готова к использованию: $NEW_DB_NAME"
echo "Не забудьте обновить конфигурацию приложения для подключения к новой БД"
