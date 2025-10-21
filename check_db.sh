#!/bin/bash

# для проверки подключения к базе данных

echo "Проверка подключения к базе данных..."

# Определяем контейнер для текущего проекта
DOCKER_CONTAINER=$(docker ps --filter "name=azv_motors_backend-db-1" --format "{{.Names}}" | head -1)
if [ -z "$DOCKER_CONTAINER" ]; then
    echo "Ошибка: Контейнер PostgreSQL для azv_motors_backend не найден"
    echo "Доступные контейнеры PostgreSQL:"
    docker ps --filter "ancestor=postgres" --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
    exit 1
fi

echo "Используется контейнер: $DOCKER_CONTAINER"

echo "Проверка подключения к базе данных..."
docker exec "$DOCKER_CONTAINER" psql -U postgres -d postgres -c "SELECT version();"

if [ $? -eq 0 ]; then
    echo "Подключение к базе данных успешно!"
    
    echo "Информация о базе данных:"
    docker exec "$DOCKER_CONTAINER" psql -U postgres -d postgres -c "
        SELECT 
            datname as database_name,
            pg_size_pretty(pg_database_size(datname)) as size
        FROM pg_database 
        WHERE datname = 'postgres';
    "
    
    echo "Количество таблиц:"
    docker exec "$DOCKER_CONTAINER" psql -U postgres -d postgres -c "
        SELECT COUNT(*) as table_count 
        FROM information_schema.tables 
        WHERE table_schema = 'public';
    "
    
    echo "Количество записей в основных таблицах:"
    docker exec "$DOCKER_CONTAINER" psql -U postgres -d postgres -c "
        SELECT 
            'users' as table_name, 
            COUNT(*) as record_count 
        FROM users
        UNION ALL
        SELECT 
            'cars' as table_name, 
            COUNT(*) as record_count 
        FROM cars
        UNION ALL
        SELECT 
            'rental_history' as table_name, 
            COUNT(*) as record_count 
        FROM rental_history
        UNION ALL
        SELECT 
            'rental_actions' as table_name, 
            COUNT(*) as record_count 
        FROM rental_actions;
    "
else
    echo "Ошибка подключения к базе данных"
    exit 1
fi
