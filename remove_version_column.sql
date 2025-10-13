-- SQL команда для удаления колонки version из таблицы contract_files
-- Выполните эту команду напрямую в PostgreSQL БЕЗ создания миграции Alembic

-- Удаление колонки version
ALTER TABLE contract_files DROP COLUMN IF EXISTS version;

-- Проверка что колонка удалена
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'contract_files';

