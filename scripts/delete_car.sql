-- ============================================================
-- СКРИПТ ДЛЯ УДАЛЕНИЯ МАШИНЫ ИЗ БД
-- ============================================================
-- ВАЖНО: Замени 'ID_МАШИНЫ' на реальный UUID машины
-- ============================================================

-- 1. ПРОВЕРКА: Найти машину
SELECT 
    id,
    name,
    plate_number,
    status,
    owner_id,
    (SELECT COUNT(*) FROM rental_history WHERE car_id = cars.id) as rentals_count,
    (SELECT COUNT(*) FROM car_comments WHERE car_id = cars.id) as comments_count,
    (SELECT COUNT(*) FROM car_availability_history WHERE car_id = cars.id) as availability_count
FROM cars 
WHERE id = 'ID_МАШИНЫ';  -- <-- ЗАМЕНИ НА UUID

-- 2. ПРОВЕРКА: Посмотреть связанные аренды (рекомендуется НЕ удалять)
SELECT id, user_id, rental_status, started_at, ended_at
FROM rental_history
WHERE car_id = 'ID_МАШИНЫ';  -- <-- ЗАМЕНИ НА UUID

-- 2a. ПРОСМОТР: Все связанные фотографии машины
-- (1) Фотки карточки машины — галерея в объявлении (cars.photos)
SELECT 'car_gallery' as source, NULL::uuid as rental_id, jsonb_array_elements_text(COALESCE(photos::jsonb, '[]'::jsonb))::text as photo_path
FROM cars WHERE id = '11082b5c-1550-481c-a6da-8a0bb7aee4a2';

-- (2) Фотки из аренд этой машины (до/после клиента, доставка, механик): до/после клиента, доставка, механик (по одной строке на каждое фото)
SELECT 'rental_' || rh.id::text as source, rh.id as rental_id, 'photos_before' as photo_type, unnest(COALESCE(rh.photos_before, '{}')) as photo_path
FROM rental_history rh WHERE rh.car_id = '11082b5c-1550-481c-a6da-8a0bb7aee4a2'
UNION ALL
SELECT 'rental_' || rh.id::text, rh.id, 'photos_after', unnest(COALESCE(rh.photos_after, '{}'))
FROM rental_history rh WHERE rh.car_id = '11082b5c-1550-481c-a6da-8a0bb7aee4a2'
UNION ALL
SELECT 'rental_' || rh.id::text, rh.id, 'delivery_photos_before', unnest(COALESCE(rh.delivery_photos_before, '{}'))
FROM rental_history rh WHERE rh.car_id = '11082b5c-1550-481c-a6da-8a0bb7aee4a2'
UNION ALL
SELECT 'rental_' || rh.id::text, rh.id, 'delivery_photos_after', unnest(COALESCE(rh.delivery_photos_after, '{}'))
FROM rental_history rh WHERE rh.car_id = '11082b5c-1550-481c-a6da-8a0bb7aee4a2'
UNION ALL
SELECT 'rental_' || rh.id::text, rh.id, 'mechanic_photos_before', unnest(COALESCE(rh.mechanic_photos_before, '{}'))
FROM rental_history rh WHERE rh.car_id = '11082b5c-1550-481c-a6da-8a0bb7aee4a2'
UNION ALL
SELECT 'rental_' || rh.id::text, rh.id, 'mechanic_photos_after', unnest(COALESCE(rh.mechanic_photos_after, '{}'))
FROM rental_history rh WHERE rh.car_id = '11082b5c-1550-481c-a6da-8a0bb7aee4a2';

-- 3. УДАЛЕНИЕ: Удалить связанные данные
-- ВНИМАНИЕ: rental_history лучше НЕ удалять (история важна!)
-- Если всё же нужно - раскомментируй строку ниже:
-- DELETE FROM rental_history WHERE car_id = 'ID_МАШИНЫ';

DELETE FROM car_availability_history WHERE car_id = 'ID_МАШИНЫ';  -- <-- ЗАМЕНИ НА UUID
DELETE FROM car_comments WHERE car_id = 'ID_МАШИНЫ';  -- <-- ЗАМЕНИ НА UUID

-- 4. УДАЛЕНИЕ: Удалить саму машину
DELETE FROM cars WHERE id = 'ID_МАШИНЫ';  -- <-- ЗАМЕНИ НА UUID

-- 5. ПРОВЕРКА: Убедиться что удалено
SELECT COUNT(*) as remaining FROM cars WHERE id = 'ID_МАШИНЫ';  -- Должно быть 0

-- ============================================================
-- АЛЬТЕРНАТИВА: Удаление по номеру (plate_number)
-- ============================================================

-- Найти ID по номеру
SELECT id, name, plate_number 
FROM cars 
WHERE plate_number = '096ADC10';  -- <-- ЗАМЕНИ НА НОМЕР

-- Затем используй найденный ID в запросах выше

-- ============================================================
-- ПРИМЕР: Все фотки машины BMW 530i 096ADC10
-- (uuid 11082b5c-1550-481c-a6da-8a0bb7aee4a2)
-- ============================================================

-- Фотки карточки (галерея)
SELECT 'car_gallery' as source, NULL::uuid as rental_id, jsonb_array_elements_text(COALESCE(photos::jsonb, '[]'::jsonb))::text as photo_path
FROM cars WHERE id = '11082b5c-1550-481c-a6da-8a0bb7aee4a2';

-- Фотки из аренд (до/после, доставка, механик)
SELECT 'rental_' || rh.id::text as source, rh.id as rental_id, 'photos_before' as photo_type, unnest(COALESCE(rh.photos_before, '{}')) as photo_path
FROM rental_history rh WHERE rh.car_id = '11082b5c-1550-481c-a6da-8a0bb7aee4a2'
UNION ALL
SELECT 'rental_' || rh.id::text, rh.id, 'photos_after', unnest(COALESCE(rh.photos_after, '{}'))
FROM rental_history rh WHERE rh.car_id = '11082b5c-1550-481c-a6da-8a0bb7aee4a2'
UNION ALL
SELECT 'rental_' || rh.id::text, rh.id, 'delivery_photos_before', unnest(COALESCE(rh.delivery_photos_before, '{}'))
FROM rental_history rh WHERE rh.car_id = '11082b5c-1550-481c-a6da-8a0bb7aee4a2'
UNION ALL
SELECT 'rental_' || rh.id::text, rh.id, 'delivery_photos_after', unnest(COALESCE(rh.delivery_photos_after, '{}'))
FROM rental_history rh WHERE rh.car_id = '11082b5c-1550-481c-a6da-8a0bb7aee4a2'
UNION ALL
SELECT 'rental_' || rh.id::text, rh.id, 'mechanic_photos_before', unnest(COALESCE(rh.mechanic_photos_before, '{}'))
FROM rental_history rh WHERE rh.car_id = '11082b5c-1550-481c-a6da-8a0bb7aee4a2'
UNION ALL
SELECT 'rental_' || rh.id::text, rh.id, 'mechanic_photos_after', unnest(COALESCE(rh.mechanic_photos_after, '{}'))
FROM rental_history rh WHERE rh.car_id = '11082b5c-1550-481c-a6da-8a0bb7aee4a2';
