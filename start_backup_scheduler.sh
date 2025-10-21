#!/bin/bash

# для запуска планировщика бэкапов
# Использование: ./start_backup_scheduler.sh [--test]

echo "Запуск планировщика бэкапов AZV Motors..."

# Проверяем, что Docker доступен
if ! command -v docker &> /dev/null; then
    echo "Ошибка: Docker не найден"
    exit 1
fi

# Проверяем, что контейнер БД запущен
DOCKER_CONTAINER=$(docker ps --filter "name=azv_motors_backend-db-1" --format "{{.Names}}" | head -1)
if [ -z "$DOCKER_CONTAINER" ]; then
    echo "Ошибка: Контейнер PostgreSQL для azv_motors_backend не найден"
    echo "Доступные контейнеры PostgreSQL:"
    docker ps --filter "ancestor=postgres" --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
    exit 1
fi

echo "Используется контейнер: $DOCKER_CONTAINER"

# Проверяем, что Python и зависимости установлены
if ! command -v python3 &> /dev/null; then
    echo "Ошибка: Python3 не найден"
    exit 1
fi

# Устанавливаем зависимости если нужно
if [ ! -f "scripts/requirements_backup.txt" ]; then
    echo "Файл requirements_backup.txt не найден"
    exit 1
fi

# Переходим в директорию скриптов
cd scripts

# Устанавливаем зависимости
echo "Установка зависимостей..."
pip3 install --break-system-packages -r requirements_backup.txt

# Запускаем планировщик
echo "Запуск планировщика..."
if [ "$1" = "--test" ]; then
    echo "Тестовый режим - создание одного бэкапа"
    python3 backup_schedule.py --test
else
    echo "Запуск в режиме планировщика"
    echo "Для остановки нажмите Ctrl+C"
    python3 backup_schedule.py
fi
