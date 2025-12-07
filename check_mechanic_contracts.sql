-- Проверка статуса подписания договоров для механика (phone_number: 71234567876)
-- Проверяет все 3 договора: rental_main_contract, appendix_7_1, appendix_7_2

SELECT 
    u.id as user_id,
    u.phone_number,
    u.first_name,
    u.last_name,
    u.role,
    
    -- Проверка основного договора аренды (rental_main_contract)
    EXISTS(
        SELECT 1 
        FROM user_contract_signatures ucs
        JOIN contract_files cf ON ucs.contract_file_id = cf.id
        WHERE ucs.user_id = u.id
        AND cf.contract_type = 'rental_main_contract'
        AND ucs.rental_id IS NOT NULL
    ) as rental_main_contract_signed,
    
    -- Проверка приложения 7.1 (appendix_7_1)
    EXISTS(
        SELECT 1 
        FROM user_contract_signatures ucs
        JOIN contract_files cf ON ucs.contract_file_id = cf.id
        WHERE ucs.user_id = u.id
        AND cf.contract_type = 'appendix_7_1'
        AND ucs.rental_id IS NOT NULL
    ) as appendix_7_1_signed,
    
    -- Проверка приложения 7.2 (appendix_7_2)
    EXISTS(
        SELECT 1 
        FROM user_contract_signatures ucs
        JOIN contract_files cf ON ucs.contract_file_id = cf.id
        WHERE ucs.user_id = u.id
        AND cf.contract_type = 'appendix_7_2'
        AND ucs.rental_id IS NOT NULL
    ) as appendix_7_2_signed,
    
    -- Детальная информация о подписанных договорах аренды
    (
        SELECT json_agg(
            json_build_object(
                'rental_id', ucs.rental_id,
                'contract_type', cf.contract_type,
                'signed_at', ucs.signed_at
            )
        )
        FROM user_contract_signatures ucs
        JOIN contract_files cf ON ucs.contract_file_id = cf.id
        WHERE ucs.user_id = u.id
        AND ucs.rental_id IS NOT NULL
        AND cf.contract_type IN ('rental_main_contract', 'appendix_7_1', 'appendix_7_2')
    ) as signed_contracts_details,
    
    -- Активные аренды/осмотры/доставки для механика
    (
        SELECT json_agg(
            json_build_object(
                'rental_id', rh.id,
                'rental_status', rh.rental_status,
                'mechanic_inspection_status', rh.mechanic_inspection_status,
                'car_id', rh.car_id
            )
        )
        FROM rental_history rh
        WHERE (rh.mechanic_inspector_id = u.id OR rh.delivery_mechanic_id = u.id)
        AND (
            rh.mechanic_inspection_status IN ('PENDING', 'IN_USE', 'SERVICE')
            OR rh.rental_status IN ('DELIVERY_RESERVED', 'DELIVERING', 'DELIVERING_IN_PROGRESS')
        )
    ) as active_rentals_for_mechanic

FROM users u
WHERE u.phone_number = '71234567876';

