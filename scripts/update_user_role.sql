-- ============================================================
-- СМЕНА РОЛИ ПОЛЬЗОВАТЕЛЯ
-- ============================================================
-- Подключение: psql "postgresql://USER:PASSWORD@HOST:5432/azv_motors_backend_v2"
-- ============================================================

-- Текущий пользователь и роль
SELECT id, phone_number, email, first_name, last_name, role
FROM users
WHERE id = 'af8579f4-4fca-492d-b036-ea16e1945290';

-- Доступные роли (значение для SET role = '...'):
--   'admin'       — администратор
--   'user'        — одобренный клиент (может арендовать)
--   'client'      — новый/не заполнил документы
--   'SUPPORT'     — поддержка
--   'MECHANIC'    — механик
--   'FINANCIER'   — финансист
--   'ACCOUNTANT'  — бухгалтер
--   'PENDINGTOFIRST'   — ждёт проверки финансиста
--   'PENDINGTOSECOND'  — ждёт проверки МВД
--   'REJECTFIRST'      — отказ финансиста
--   'REJECTSECOND'     — отказ МВД (полный блок)
--   'REJECTFIRSTDOC'   — отказ: документы
--   'REJECTFIRSTCERT'  — отказ: сертификаты
--   'rejected', 'pending', 'GARANT', 'mvd', 'DRIVER'

-- Сменить роль (подставь нужную роль из списка выше):
UPDATE users
SET role = 'user'
WHERE id = 'af8579f4-4fca-492d-b036-ea16e1945290';

-- Проверка
SELECT id, phone_number, email, first_name, last_name, role
FROM users
WHERE id = 'af8579f4-4fca-492d-b036-ea16e1945290';
