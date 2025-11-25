-- ============================================================
-- СКРИПТ ДЛЯ СОЗДАНИЯ ФЕЙКОВЫХ ПОЕЗДОК
-- Владелец машин: 71231111111
-- Арендатор всех поездок: 77027227583
-- Машина 1: Changan UNI-V - 12 поездок (1-20 ноября 2025, доход 170-180 тыс)
-- Машина 2: Changan UNI-K - 10 поездок (доход 200-210 тыс)
-- ============================================================

-- Шаг 1: Найти владельца и его машины
-- Сначала выполните эти SELECT запросы для проверки данных:

-- Проверяем владельца
SELECT id, first_name, last_name, phone_number, role 
FROM users 
WHERE phone_number = '71231111111';

-- Проверяем машины владельца
SELECT c.id, c.name, c.plate_number, c.owner_id, u.phone_number as owner_phone
FROM cars c
JOIN users u ON c.owner_id = u.id
WHERE u.phone_number = '71231111111' 
  AND (c.name ILIKE '%UNI-V%' OR c.name ILIKE '%UNI V%' OR c.name ILIKE '%UNIV%');

SELECT c.id, c.name, c.plate_number, c.owner_id, u.phone_number as owner_phone
FROM cars c
JOIN users u ON c.owner_id = u.id
WHERE u.phone_number = '71231111111' 
  AND (c.name ILIKE '%UNI-K%' OR c.name ILIKE '%UNI K%' OR c.name ILIKE '%UNIK%');

-- ============================================================
-- ПОСЛЕ ПРОВЕРКИ ЗАМЕНИТЕ ЗНАЧЕНИЯ НИЖЕ НА РЕАЛЬНЫЕ ID
-- ============================================================

-- ВАЖНО! Замените эти значения на реальные UUID из вашей базы:
DO $$
DECLARE
    owner_uuid UUID;
    car_univ_uuid UUID;
    car_unik_uuid UUID;
    renter_uuid UUID;
    rental_uuid UUID;
    base_price INTEGER;
    total_amount INTEGER;
    start_date TIMESTAMP;
    end_date TIMESTAMP;
    duration_hours INTEGER;
BEGIN
    -- Получаем UUID владельца машин
    SELECT id INTO owner_uuid FROM users WHERE phone_number = '71231111111' LIMIT 1;
    
    IF owner_uuid IS NULL THEN
        RAISE EXCEPTION 'Владелец с номером 71231111111 не найден!';
    END IF;
    
    -- Получаем UUID арендатора (пользователь который будет арендовать)
    SELECT id INTO renter_uuid FROM users WHERE phone_number = '77027227583' LIMIT 1;
    
    IF renter_uuid IS NULL THEN
        RAISE EXCEPTION 'Арендатор с номером 77027227583 не найден!';
    END IF;
    
    -- Получаем UUID машины Changan UNI-V
    SELECT id INTO car_univ_uuid 
    FROM cars 
    WHERE owner_id = owner_uuid 
      AND (name ILIKE '%UNI-V%' OR name ILIKE '%UNI V%' OR name ILIKE '%UNIV%')
    LIMIT 1;
    
    -- Получаем UUID машины Changan UNI-K
    SELECT id INTO car_unik_uuid 
    FROM cars 
    WHERE owner_id = owner_uuid 
      AND (name ILIKE '%UNI-K%' OR name ILIKE '%UNI K%' OR name ILIKE '%UNIK%')
    LIMIT 1;
    
    IF car_univ_uuid IS NULL THEN
        RAISE NOTICE 'Машина Changan UNI-V не найдена для владельца 71231111111';
    END IF;
    
    IF car_unik_uuid IS NULL THEN
        RAISE NOTICE 'Машина Changan UNI-K не найдена для владельца 71231111111';
    END IF;
    
    -- ============================================================
    -- ПОЕЗДКИ ДЛЯ CHANGAN UNI-V (12 поездок, 170-180 тыс тенге)
    -- ============================================================
    
    IF car_univ_uuid IS NOT NULL THEN
        RAISE NOTICE 'Создаем поездки для Changan UNI-V...';
        
        -- Поездка 1: 1 ноября, 3 дня (14,000 тг)
        start_date := '2025-11-01 09:00:00'::timestamp;
        end_date := start_date + interval '3 days';
        duration_hours := 72;
        base_price := 14000;
        total_amount := 14000;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_univ_uuid, 'DAYS', 3,
            43.238293, 76.945465, 43.240000, 76.950000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            45.5, 38.2, 12450, 12780,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 2: 2 ноября, 2 дня (15,500 тг)
        start_date := '2025-11-02 10:30:00'::timestamp;
        end_date := start_date + interval '2 days';
        duration_hours := 48;
        base_price := 15500;
        total_amount := 15500;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_univ_uuid, 'DAYS', 2,
            43.240000, 76.950000, 43.235000, 76.945000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            38.2, 32.5, 12780, 13050,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 3: 4 ноября, 1 день (14,200 тг)
        start_date := '2025-11-04 14:00:00'::timestamp;
        end_date := start_date + interval '1 day';
        duration_hours := 24;
        base_price := 14200;
        total_amount := 14200;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_univ_uuid, 'DAYS', 1,
            43.235000, 76.945000, 43.245000, 76.955000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            32.5, 28.0, 13050, 13280,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 4: 6 ноября, 2 дня (15,800 тг)
        start_date := '2025-11-06 11:00:00'::timestamp;
        end_date := start_date + interval '2 days';
        duration_hours := 48;
        base_price := 15800;
        total_amount := 15800;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_univ_uuid, 'DAYS', 2,
            43.245000, 76.955000, 43.238000, 76.948000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            28.0, 22.5, 13280, 13620,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 5: 8 ноября, 3 дня (14,500 тг)
        start_date := '2025-11-08 08:30:00'::timestamp;
        end_date := start_date + interval '3 days';
        duration_hours := 72;
        base_price := 14500;
        total_amount := 14500;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_univ_uuid, 'DAYS', 3,
            43.238000, 76.948000, 43.242000, 76.952000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            22.5, 16.8, 13620, 14010,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 6: 10 ноября, 1 день (13,900 тг)
        start_date := '2025-11-10 15:00:00'::timestamp;
        end_date := start_date + interval '1 day';
        duration_hours := 24;
        base_price := 13900;
        total_amount := 13900;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_univ_uuid, 'DAYS', 1,
            43.242000, 76.952000, 43.236000, 76.946000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            16.8, 12.5, 14010, 14210,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 7: 12 ноября, 2 дня (15,200 тг)
        start_date := '2025-11-12 09:45:00'::timestamp;
        end_date := start_date + interval '2 days';
        duration_hours := 48;
        base_price := 15200;
        total_amount := 15200;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_univ_uuid, 'DAYS', 2,
            43.236000, 76.946000, 43.244000, 76.954000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            12.5, 8.0, 14210, 14580,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 8: 14 ноября, 3 дня (14,800 тг)
        start_date := '2025-11-14 12:00:00'::timestamp;
        end_date := start_date + interval '3 days';
        duration_hours := 72;
        base_price := 14800;
        total_amount := 14800;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_univ_uuid, 'DAYS', 3,
            43.244000, 76.954000, 43.239000, 76.949000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            8.0, 3.5, 14580, 14970,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 9: 16 ноября, 1 день (14,300 тг)
        start_date := '2025-11-16 10:30:00'::timestamp;
        end_date := start_date + interval '1 day';
        duration_hours := 24;
        base_price := 14300;
        total_amount := 14300;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_univ_uuid, 'DAYS', 1,
            43.239000, 76.949000, 43.241000, 76.951000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            45.0, 40.5, 14970, 15180,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 10: 17 ноября, 2 дня (15,600 тг)
        start_date := '2025-11-17 13:15:00'::timestamp;
        end_date := start_date + interval '2 days';
        duration_hours := 48;
        base_price := 15600;
        total_amount := 15600;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_univ_uuid, 'DAYS', 2,
            43.241000, 76.951000, 43.237000, 76.947000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            40.5, 35.0, 15180, 15480,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 11: 18 ноября, 1 день (14,100 тг)
        start_date := '2025-11-18 11:00:00'::timestamp;
        end_date := start_date + interval '1 day';
        duration_hours := 24;
        base_price := 14100;
        total_amount := 14100;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_univ_uuid, 'DAYS', 1,
            43.237000, 76.947000, 43.243000, 76.953000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            35.0, 30.2, 15480, 15690,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 12: 19 ноября, 2 дня (15,400 тг)
        start_date := '2025-11-19 14:30:00'::timestamp;
        end_date := start_date + interval '2 days';
        duration_hours := 48;
        base_price := 15400;
        total_amount := 15400;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_univ_uuid, 'DAYS', 2,
            43.243000, 76.953000, 43.240000, 76.950000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            30.2, 25.5, 15690, 15920,
            total_amount, total_amount, 'completed'
        );
        
        RAISE NOTICE 'Создано 12 поездок для Changan UNI-V. Общая сумма: 176,300 тг';
    END IF;
    
    -- ============================================================
    -- ПОЕЗДКИ ДЛЯ CHANGAN UNI-K (10 поездок, 200-210 тыс тенге)
    -- ============================================================
    
    IF car_unik_uuid IS NOT NULL THEN
        RAISE NOTICE 'Создаем поездки для Changan UNI-K...';
        
        -- Поездка 1: 1 ноября, 3 дня (20,500 тг)
        start_date := '2025-11-01 10:00:00'::timestamp;
        end_date := start_date + interval '3 days';
        duration_hours := 72;
        base_price := 20500;
        total_amount := 20500;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_unik_uuid, 'DAYS', 3,
            43.238293, 76.945465, 43.240000, 76.950000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            48.5, 42.0, 18450, 18820,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 2: 3 ноября, 2 дня (21,200 тг)
        start_date := '2025-11-03 12:00:00'::timestamp;
        end_date := start_date + interval '2 days';
        duration_hours := 48;
        base_price := 21200;
        total_amount := 21200;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_unik_uuid, 'DAYS', 2,
            43.240000, 76.950000, 43.235000, 76.945000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            42.0, 36.5, 18820, 19110,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 3: 5 ноября, 3 дня (20,800 тг)
        start_date := '2025-11-05 09:30:00'::timestamp;
        end_date := start_date + interval '3 days';
        duration_hours := 72;
        base_price := 20800;
        total_amount := 20800;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_unik_uuid, 'DAYS', 3,
            43.235000, 76.945000, 43.245000, 76.955000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            36.5, 30.0, 19110, 19520,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 4: 7 ноября, 2 дня (21,500 тг)
        start_date := '2025-11-07 11:15:00'::timestamp;
        end_date := start_date + interval '2 days';
        duration_hours := 48;
        base_price := 21500;
        total_amount := 21500;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_unik_uuid, 'DAYS', 2,
            43.245000, 76.955000, 43.238000, 76.948000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            30.0, 24.5, 19520, 19820,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 5: 9 ноября, 3 дня (20,300 тг)
        start_date := '2025-11-09 08:45:00'::timestamp;
        end_date := start_date + interval '3 days';
        duration_hours := 72;
        base_price := 20300;
        total_amount := 20300;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_unik_uuid, 'DAYS', 3,
            43.238000, 76.948000, 43.242000, 76.952000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            24.5, 18.0, 19820, 20230,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 6: 11 ноября, 2 дня (21,800 тг)
        start_date := '2025-11-11 14:00:00'::timestamp;
        end_date := start_date + interval '2 days';
        duration_hours := 48;
        base_price := 21800;
        total_amount := 21800;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_unik_uuid, 'DAYS', 2,
            43.242000, 76.952000, 43.236000, 76.946000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            18.0, 12.5, 20230, 20510,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 7: 13 ноября, 3 дня (20,600 тг)
        start_date := '2025-11-13 10:30:00'::timestamp;
        end_date := start_date + interval '3 days';
        duration_hours := 72;
        base_price := 20600;
        total_amount := 20600;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_unik_uuid, 'DAYS', 3,
            43.236000, 76.946000, 43.244000, 76.954000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            12.5, 7.0, 20510, 20940,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 8: 15 ноября, 2 дня (21,100 тг)
        start_date := '2025-11-15 13:00:00'::timestamp;
        end_date := start_date + interval '2 days';
        duration_hours := 48;
        base_price := 21100;
        total_amount := 21100;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_unik_uuid, 'DAYS', 2,
            43.244000, 76.954000, 43.239000, 76.949000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            45.0, 40.0, 20940, 21220,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 9: 17 ноября, 3 дня (20,900 тг)
        start_date := '2025-11-17 09:00:00'::timestamp;
        end_date := start_date + interval '3 days';
        duration_hours := 72;
        base_price := 20900;
        total_amount := 20900;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_unik_uuid, 'DAYS', 3,
            43.239000, 76.949000, 43.241000, 76.951000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            40.0, 34.5, 21220, 21630,
            total_amount, total_amount, 'completed'
        );
        
        -- Поездка 10: 19 ноября, 2 дня (21,400 тг)
        start_date := '2025-11-19 12:30:00'::timestamp;
        end_date := start_date + interval '2 days';
        duration_hours := 48;
        base_price := 21400;
        total_amount := 21400;
        
        INSERT INTO rental_history (
            id, user_id, car_id, rental_type, duration,
            start_latitude, start_longitude, end_latitude, end_longitude,
            start_time, end_time, reservation_time,
            base_price, open_fee, delivery_fee, waiting_fee, overtime_fee, distance_fee,
            fuel_before, fuel_after, mileage_before, mileage_after,
            already_payed, total_price, rental_status
        ) VALUES (
            gen_random_uuid(), renter_uuid, car_unik_uuid, 'DAYS', 2,
            43.241000, 76.951000, 43.237000, 76.947000,
            start_date, end_date, start_date,
            base_price, 500, 0, 0, 0, 0,
            34.5, 29.0, 21630, 21910,
            total_amount, total_amount, 'completed'
        );
        
        RAISE NOTICE 'Создано 10 поездок для Changan UNI-K. Общая сумма: 210,100 тг';
    END IF;
    
    RAISE NOTICE '==========================================';
    RAISE NOTICE 'ИТОГО:';
    RAISE NOTICE 'Changan UNI-V: 12 поездок, 176,300 тг';
    RAISE NOTICE 'Changan UNI-K: 10 поездок, 210,100 тг';
    RAISE NOTICE 'ОБЩАЯ СУММА: 386,400 тг';
    RAISE NOTICE '==========================================';
    
END $$;

-- Проверка результата
SELECT 
    c.name as car_name,
    COUNT(rh.id) as total_rentals,
    SUM(rh.total_price) as total_revenue,
    MIN(rh.start_time) as first_rental,
    MAX(rh.end_time) as last_rental
FROM rental_history rh
JOIN cars c ON rh.car_id = c.id
JOIN users u ON c.owner_id = u.id
WHERE u.phone_number = '71231111111'
  AND rh.start_time >= '2025-11-01 00:00:00'
  AND rh.start_time <= '2025-11-20 23:59:59'
  AND rh.rental_status = 'completed'
GROUP BY c.id, c.name
ORDER BY c.name;

