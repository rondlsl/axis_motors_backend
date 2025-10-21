# 🔄 Система резервного копирования базы данных

Этот набор скриптов обеспечивает автоматическое резервное копирование и восстановление базы данных PostgreSQL для проекта AZV Motors.

## 📁 Структура файлов

```
scripts/
├── backup_database.sh      # Основной скрипт создания бэкапов
├── restore_database.sh     # Скрипт восстановления из бэкапа
├── backup_schedule.py      # Python скрипт для автоматического планирования
├── requirements_backup.txt # Зависимости для Python скриптов
└── README_backup.md        # Документация (этот файл)
```

## 🚀 Быстрый старт

### 1. Создание бэкапа

```bash
# Полный бэкап
./backup_database.sh full daily

# Инкрементальный бэкап
./backup_database.sh incremental daily

# Бэкап только схемы
./backup_database.sh schema daily
```

### 2. Восстановление из бэкапа

```bash
# Восстановление в новую базу данных
./restore_database.sh backups/daily/backup_full_20241201_020000.sql.gz new_database_name

# Восстановление в существующую базу
./restore_database.sh backups/daily/backup_full_20241201_020000.sql.gz azv_motors_db
```

### 3. Автоматическое планирование

```bash
# Установка зависимостей
pip install -r requirements_backup.txt

# Запуск планировщика
python backup_schedule.py

# Тестовый режим
python backup_schedule.py --test
```

## 📋 Типы бэкапов

### Полный бэкап (Full Backup)
- Содержит всю структуру и данные
- Рекомендуется для ежедневных/еженедельных бэкапов
- Размер: ~100-500MB (зависит от объема данных)

### Инкрементальный бэкап (Incremental Backup)
- Содержит только изменения данных
- Рекомендуется для частых бэкапов
- Размер: ~10-50MB

### Бэкап схемы (Schema-only Backup)
- Содержит только структуру БД (таблицы, индексы, функции)
- Полезен для развертывания на новых серверах
- Размер: ~1-5MB

## ⏰ Рекомендуемое расписание

| Тип бэкапа | Частота | Время | Хранение |
|------------|---------|-------|----------|
| Полный | Ежедневно | 02:00 | 30 дней |
| Полный | Еженедельно | Воскресенье 01:00 | 12 недель |
| Полный | Ежемесячно | 1 число 00:00 | 12 месяцев |
| Инкрементальный | Каждый час | :00 | 7 дней |

## 🔧 Настройка

### Переменные окружения

Создайте файл `.env` в корне проекта:

```env
# Настройки базы данных
DB_HOST=localhost
DB_PORT=5432
DB_NAME=azv_motors_db
DB_USER=postgres
DB_PASSWORD=your_password

# Настройки бэкапов
BACKUP_DIR=./backups
RETENTION_DAYS=30
RETENTION_WEEKS=12
RETENTION_MONTHS=12
```

### Настройка прав доступа

```bash
# Сделать скрипты исполняемыми
chmod +x backup_database.sh
chmod +x restore_database.sh

# Создать директории для бэкапов
mkdir -p backups/{daily,weekly,monthly,manual}
```

## 📦 Хранение бэкапов

### Локальное хранение
```
backups/
├── daily/          # Ежедневные бэкапы (30 дней)
├── weekly/         # Еженедельные бэкапы (12 недель)
├── monthly/        # Ежемесячные бэкапы (12 месяцев)
└── manual/         # Ручные бэкапы
```

### Облачное хранение (рекомендуется)

#### AWS S3
```bash
# Установка AWS CLI
pip install awscli

# Настройка
aws configure

# Автоматическая загрузка в S3 (добавить в скрипт)
aws s3 cp backup_file.sql.gz s3://your-backup-bucket/azv_motors_db/
```

#### Google Cloud Storage
```bash
# Установка gsutil
pip install gsutil

# Загрузка в GCS
gsutil cp backup_file.sql.gz gs://your-backup-bucket/azv_motors_db/
```

## 🔐 Безопасность

### Шифрование бэкапов
```bash
# Создание зашифрованного бэкапа
pg_dump -h localhost -U postgres -d azv_motors_db | gzip | openssl enc -aes-256-cbc -salt -out backup_encrypted.sql.gz.enc

# Расшифровка
openssl enc -aes-256-cbc -d -in backup_encrypted.sql.gz.enc | gunzip | psql -h localhost -U postgres -d restored_db
```

### Настройка PostgreSQL для бэкапов
```sql
-- Включение WAL архивирования
ALTER SYSTEM SET wal_level = replica;
ALTER SYSTEM SET archive_mode = on;
ALTER SYSTEM SET archive_command = 'cp %p /var/lib/postgresql/archive/%f';
```

## 🚨 Мониторинг и уведомления

### Проверка статуса бэкапов
```bash
# Проверка последнего бэкапа
ls -la backups/daily/ | tail -5

# Проверка размера бэкапов
du -sh backups/*

# Проверка целостности бэкапа
gunzip -t backups/daily/backup_full_20241201_020000.sql.gz
```

### Email уведомления
Добавьте в `backup_database.sh`:
```bash
# Отправка уведомления об ошибке
if [ $? -ne 0 ]; then
    echo "Ошибка бэкапа $(date)" | mail -s "Ошибка бэкапа AZV Motors" admin@example.com
fi
```

## 🔄 Восстановление в продакшене

### Пошаговое восстановление

1. **Остановить приложение**
```bash
sudo systemctl stop azv_motors_backend
```

2. **Создать бэкап текущей БД**
```bash
./backup_database.sh full manual
```

3. **Восстановить из бэкапа**
```bash
./restore_database.sh backups/manual/backup_full_YYYYMMDD_HHMMSS.sql.gz azv_motors_db
```

4. **Запустить приложение**
```bash
sudo systemctl start azv_motors_backend
```

### Проверка после восстановления
```bash
# Проверка подключения
psql -h localhost -U postgres -d azv_motors_db -c "SELECT COUNT(*) FROM users;"

# Проверка миграций
alembic current

# Запуск тестов
pytest tests/
```

## 🛠️ Troubleshooting

### Частые проблемы

1. **Ошибка прав доступа**
```bash
sudo chown postgres:postgres backups/
chmod 755 backups/
```

2. **Недостаток места на диске**
```bash
# Проверка места
df -h

# Очистка старых бэкапов
find backups/ -name "*.sql.gz" -mtime +30 -delete
```

3. **Ошибка подключения к БД**
```bash
# Проверка статуса PostgreSQL
sudo systemctl status postgresql

# Проверка подключения
psql -h localhost -U postgres -d azv_motors_db
```

## 📞 Поддержка

При возникновении проблем:
1. Проверьте логи: `tail -f backup_scheduler.log`
2. Проверьте права доступа к файлам
3. Убедитесь в корректности настроек БД
4. Проверьте доступное место на диске
