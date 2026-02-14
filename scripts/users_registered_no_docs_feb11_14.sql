-- Номера и имена клиентов, которые зарегистрировались 11–14 февраля и не загрузили документы.
-- Год по умолчанию: 2026 (поменяйте в условии при необходимости).

SELECT
    u.phone_number AS "Номер",
    TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '') || ' ' || COALESCE(u.middle_name, '')) AS "ФИО",
    u.first_name  AS "Имя",
    u.last_name   AS "Фамилия",
    u.middle_name AS "Отчество",
    u.created_at  AS "Дата регистрации"
FROM users u
WHERE (u.created_at::date IN ('2026-02-11', '2026-02-12', '2026-02-13', '2026-02-14'))
  AND u.upload_document_at IS NULL
  AND u.is_deleted = false
ORDER BY u.created_at, u.phone_number;
