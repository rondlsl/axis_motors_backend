-- ============================================================
-- УДАЛЕНИЕ ПОЛЬЗОВАТЕЛЯ ИЗ БД
-- ============================================================
-- Подключение (из корня проекта):
--   PGPASSWORD='kT9Wv2mX6Qp7Ld1Zr8nH4Ys3' psql -h 38.107.234.163 -p 5432 -U postgres -d azv_motors_backend_v2
-- Или одной строкой (подставь свои данные из .env):
--   psql "postgresql://postgres:ПАРОЛЬ@HOST:5432/azv_motors_backend_v2"
-- ============================================================

-- 1. НАЙТИ ПОЛЬЗОВАТЕЛЯ по номеру телефона
SELECT id, phone_number, email, first_name, last_name, role
FROM users
WHERE phone_number = '77088190662';  -- <-- замени на нужный номер

-- 2. НАЙТИ ПОЛЬЗОВАТЕЛЯ по почте
SELECT id, phone_number, email, first_name, last_name, role
FROM users
WHERE email = 'azvmotors.team@gmail.com';  -- <-- замени на нужный email

-- 3. УДАЛИТЬ по номеру телефона (один пользователь)
-- DELETE FROM users WHERE phone_number = '+77001234567';

-- 4. УДАЛИТЬ по почте (один пользователь)
-- DELETE FROM users WHERE email = 'user@example.com';

-- 5. УДАЛИТЬ по id (если уже знаешь uuid)
-- DELETE FROM users WHERE id = 'uuid-пользователя';

-- ВНИМАНИЕ: если есть связанные записи (аренды, заявки, токены и т.д.),
-- удаление может не пройти из‑за внешних ключей. Тогда сначала удали
-- связанные данные или раскомментируй блок ниже и выполни по шагам.

-- ========== Опционально: удаление связанных данных перед пользователем ==========
-- Замени 50a09bc4-4da2-48b2-9258-3f6dd6728bd7 на id пользователя из шага 1 или 2.

DELETE FROM token_records WHERE user_id = '50a09bc4-4da2-48b2-9258-3f6dd6728bd7';
DELETE FROM auth_tokens WHERE user_id = '50a09bc4-4da2-48b2-9258-3f6dd6728bd7';
DELETE FROM user_devices WHERE user_id = '50a09bc4-4da2-48b2-9258-3f6dd6728bd7';
DELETE FROM notifications WHERE user_id = '50a09bc4-4da2-48b2-9258-3f6dd6728bd7';
DELETE FROM wallet_transactions WHERE user_id = '50a09bc4-4da2-48b2-9258-3f6dd6728bd7';
DELETE FROM rental_actions WHERE user_id = '50a09bc4-4da2-48b2-9258-3f6dd6728bd7';
DELETE FROM rental_history WHERE user_id = '50a09bc4-4da2-48b2-9258-3f6dd6728bd7';  -- осторожно: история аренд
DELETE FROM applications WHERE user_id = '50a09bc4-4da2-48b2-9258-3f6dd6728bd7';
DELETE FROM user_contract_signatures WHERE user_id = '50a09bc4-4da2-48b2-9258-3f6dd6728bd7';
DELETE FROM action_logs WHERE actor_id = '50a09bc4-4da2-48b2-9258-3f6dd6728bd7';
DELETE FROM bonus_promo_usages WHERE user_id = '50a09bc4-4da2-48b2-9258-3f6dd6728bd7';
DELETE FROM users WHERE id = '50a09bc4-4da2-48b2-9258-3f6dd6728bd7';

