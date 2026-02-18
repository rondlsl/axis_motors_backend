-- Пометить email как bounced, чтобы на него больше не отправляли (репутация)
-- После выполнения отправка на этот адрес будет блокироваться в приложении.

-- 1. Найти пользователя: точное совпадение и без учёта регистра
SELECT id, email, email_status, is_verified_email
FROM users
WHERE LOWER(TRIM(email)) = LOWER('musakhan.alibek@gmail.com');

-- 2. Если пусто — поиск по части (например опечатка при сохранении)
SELECT id, email, email_status, is_verified_email
FROM users
WHERE email ILIKE '%musakhan%' OR email ILIKE '%alibek%gmail%';

-- 3. Кто в последнее время получал коды на этот адрес (verification_codes)
SELECT DISTINCT vc.email, u.id AS user_id, u.email AS user_email, u.email_status
FROM verification_codes vc
LEFT JOIN users u ON LOWER(TRIM(u.email)) = LOWER(TRIM(vc.email))
WHERE vc.email ILIKE '%musakhan.alibek%' OR vc.email ILIKE '%alibek%gmail%'
ORDER BY vc.email
LIMIT 20;

-- 4. Пометить как bounced (остановить отправку на musakhan.alibek@gmail.con — опечатка .con)
UPDATE users SET email_status = 'bounced' WHERE id = 'ccd9cdc0-3de7-482c-8a9d-32bdb35a1593';

-- 5. (по желанию) Исправить опечатку .con → .com, чтобы пользователь мог верифицировать с правильным адресом
-- UPDATE users SET email = 'musakhan.alibek@gmail.com', email_status = 'pending' WHERE id = 'ccd9cdc0-3de7-482c-8a9d-32bdb35a1593';
