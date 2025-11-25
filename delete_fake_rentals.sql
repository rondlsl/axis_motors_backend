-- ============================================================
-- СКРИПТ ДЛЯ УДАЛЕНИЯ ФЕЙКОВЫХ ПОЕЗДОК
-- Владелец машин: 71231111111
-- Арендатор: 77027227583
-- Удаляет поездки с 1 по 20 ноября 2025 года
-- ============================================================

-- ВНИМАНИЕ! Этот скрипт удалит все поездки для машин владельца 71231111111
-- в период с 1 по 20 ноября 2025 года

-- ============================================================
-- Шаг 1: ПРОВЕРКА - посмотрите, что будет удалено
-- ============================================================

-- Просмотр поездок, которые будут удалены
SELECT 
    rh.id,
    c.name as car_name,
    c.plate_number,
    u.first_name || ' ' || u.last_name as owner_name,
    u.phone_number as owner_phone,
    rh.start_time,
    rh.end_time,
    rh.total_price,
    rh.rental_status
FROM rental_history rh
JOIN cars c ON rh.car_id = c.id
JOIN users u ON c.owner_id = u.id
WHERE u.phone_number = '71231111111'
  AND (c.name ILIKE '%Changan%' OR c.name ILIKE '%UNI-V%' OR c.name ILIKE '%UNI-K%')
  AND rh.start_time >= '2025-11-01 00:00:00'
  AND rh.start_time <= '2025-11-20 23:59:59'
ORDER BY c.name, rh.start_time;

-- Статистика по поездкам
SELECT 
    c.name as car_name,
    COUNT(rh.id) as rentals_count,
    SUM(rh.total_price) as total_revenue
FROM rental_history rh
JOIN cars c ON rh.car_id = c.id
JOIN users u ON c.owner_id = u.id
WHERE u.phone_number = '71231111111'
  AND (c.name ILIKE '%Changan%' OR c.name ILIKE '%UNI-V%' OR c.name ILIKE '%UNI-K%')
  AND rh.start_time >= '2025-11-01 00:00:00'
  AND rh.start_time <= '2025-11-20 23:59:59'
GROUP BY c.id, c.name
ORDER BY c.name;

-- ============================================================
-- Шаг 2: УДАЛЕНИЕ (выполните только после проверки!)
-- ============================================================

-- Сохраним количество удаленных записей
DO $$
DECLARE
    deleted_rentals_count INTEGER;
    deleted_actions_count INTEGER;
    owner_uuid UUID;
BEGIN
    -- Получаем UUID владельца
    SELECT id INTO owner_uuid FROM users WHERE phone_number = '71231111111' LIMIT 1;
    
    IF owner_uuid IS NULL THEN
        RAISE EXCEPTION 'Владелец с номером 71231111111 не найден!';
    END IF;
    
    -- Сначала удаляем связанные действия из rental_actions
    WITH deleted_actions AS (
        DELETE FROM rental_actions
        WHERE rental_id IN (
            SELECT rh.id 
            FROM rental_history rh
            JOIN cars c ON rh.car_id = c.id
            WHERE c.owner_id = owner_uuid
              AND (c.name ILIKE '%Changan%' OR c.name ILIKE '%UNI-V%' OR c.name ILIKE '%UNI-K%')
              AND rh.start_time >= '2025-11-01 00:00:00'
              AND rh.start_time <= '2025-11-20 23:59:59'
        )
        RETURNING *
    )
    SELECT COUNT(*) INTO deleted_actions_count FROM deleted_actions;
    
    -- Теперь удаляем поездки
    WITH deleted_rentals AS (
        DELETE FROM rental_history
        WHERE car_id IN (
            SELECT c.id 
            FROM cars c
            WHERE c.owner_id = owner_uuid
              AND (c.name ILIKE '%Changan%' OR c.name ILIKE '%UNI-V%' OR c.name ILIKE '%UNI-K%')
        )
        AND start_time >= '2025-11-01 00:00:00'
        AND start_time <= '2025-11-20 23:59:59'
        RETURNING *
    )
    SELECT COUNT(*) INTO deleted_rentals_count FROM deleted_rentals;
    
    RAISE NOTICE '==========================================';
    RAISE NOTICE 'Удалено действий (rental_actions): %', deleted_actions_count;
    RAISE NOTICE 'Удалено поездок (rental_history): %', deleted_rentals_count;
    RAISE NOTICE '==========================================';
END $$;

-- ============================================================
-- Шаг 3: ПРОВЕРКА после удаления
-- ============================================================

-- Проверяем, что поездки удалены
SELECT 
    c.name as car_name,
    COUNT(rh.id) as remaining_rentals,
    SUM(rh.total_price) as remaining_revenue
FROM rental_history rh
JOIN cars c ON rh.car_id = c.id
JOIN users u ON c.owner_id = u.id
WHERE u.phone_number = '71231111111'
  AND (c.name ILIKE '%Changan%' OR c.name ILIKE '%UNI-V%' OR c.name ILIKE '%UNI-K%')
  AND rh.start_time >= '2025-11-01 00:00:00'
  AND rh.start_time <= '2025-11-20 23:59:59'
GROUP BY c.id, c.name
ORDER BY c.name;

-- Должен вернуть 0 записей для машин Changan

