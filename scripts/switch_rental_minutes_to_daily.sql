-- ============================================================
-- Перевести активную аренду пользователя с поминутного на суточный тариф (1 день)
-- Начало суточного тарифа = момент начала текущей (поминутной) аренды
-- ============================================================
-- User ID: ef94e4e3-fa85-401e-bdea-7f5eca401d74
-- ============================================================

-- 0. ДИАГНОСТИКА: Все последние аренды пользователя (если шаг 1 дал 0 rows — смотри сюда)
SELECT 
    rh.id AS rental_id,
    rh.rental_type,
    rh.duration,
    rh.start_time,
    rh.end_time,
    rh.base_price,
    rh.rental_status,
    c.name AS car_name,
    c.plate_number
FROM rental_history rh
JOIN cars c ON c.id = rh.car_id
WHERE rh.user_id = 'ef94e4e3-fa85-401e-bdea-7f5eca401d74'
ORDER BY rh.start_time DESC NULLS LAST
LIMIT 10;

-- 1. ПРОВЕРКА: Найти активную аренду пользователя (rental_status = 'in_use')
SELECT 
    rh.id AS rental_id,
    rh.user_id,
    rh.car_id,
    rh.rental_type,
    rh.duration,
    rh.start_time,
    rh.end_time,
    rh.base_price,
    rh.rental_status,
    c.name AS car_name,
    c.plate_number,
    c.price_per_day
FROM rental_history rh
JOIN cars c ON c.id = rh.car_id
WHERE rh.user_id = 'ef94e4e3-fa85-401e-bdea-7f5eca401d74'
  AND rh.rental_status IN ('in_use', 'IN_USE')
ORDER BY rh.start_time DESC NULLS LAST
LIMIT 1;

-- 2. ОБНОВЛЕНИЕ: Поменять тариф на суточный, 1 день (start_time не трогаем — он уже есть)
-- Вариант A: по активной аренде (in_use)
UPDATE rental_history rh
SET 
    rental_type = 'DAYS',
    duration = 1,
    base_price = c.price_per_day
FROM cars c
WHERE rh.car_id = c.id
  AND rh.user_id = 'ef94e4e3-fa85-401e-bdea-7f5eca401d74'
  AND rh.rental_status IN ('in_use', 'IN_USE');

-- Вариант B: если активной нет — укажи rental_id из шага 0 и раскомментируй:
-- UPDATE rental_history rh
-- SET rental_type = 'days', duration = 1, base_price = c.price_per_day
-- FROM cars c
-- WHERE rh.car_id = c.id AND rh.id = 'UUID_АРЕНДЫ';

-- 3. ПРОВЕРКА: Убедиться, что обновилось
SELECT 
    id,
    rental_type,
    duration,
    start_time,
    base_price,
    rental_status
FROM rental_history
WHERE user_id = 'ef94e4e3-fa85-401e-bdea-7f5eca401d74'
  AND rental_status IN ('in_use', 'IN_USE');
