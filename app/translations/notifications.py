NOTIFICATIONS_TRANSLATIONS = {
    "ru": {
        # Отклонение финансистом - документы
        "financier_reject_documents_title": "Заявка отклонена",
        "financier_reject_documents_body": "Ваши документы нечитабельны, пожалуйста, прикрепите их снова.",
        
        # Отклонение финансистом - отсутствуют сертификаты для граждан Казахстана
        "financier_reject_certificates_title": "Заявка отклонена",
        "financier_reject_certificates_body": "Как гражданин Республики Казахстан, вы обязаны предоставить справки: из психоневрологического диспансера, наркологического диспансера, справку о пенсионных отчислениях.\nПожалуйста, прикрепите недостающие документы.",
        
        # Отклонение финансистом - финансовые причины
        "financier_reject_financial_title": "Заявка отклонена",
        "financier_reject_financial_body": "К сожалению, в ходе проверки ваших данных мы не смогли одобрить вашу заявку. Но вы можете воспользоваться услугой «Гарант», пригласив человека, который, в случае необходимости, сможет понести за вас материальную ответственность.",
        
        # Одобрение финансистом
        "financier_approve_title": "Заявка одобрена",
        "financier_approve_body": "Ваши заявка на регистрацию уже одобрена, осталось немного подождать, и вам будут доступны автомобили. Класс допуска: {auto_class}",
        
        # Отклонение МВД
        "mvd_reject_title": "Заявка отклонена",
        "mvd_reject_body": "Вынуждены отказать в регистрации. По результатам проверки ваших данных были выявлены несоответствия требованиям доступа к сервису. Обращаем внимание, что на основании п. 6.3.4 Договора, Арендодатель вправе по своему усмотрению отказаться от заключения Договора с Клиентом. С уважением, Команда «AZV Motors».",
        
        # Одобрение МВД
        "mvd_approve_title": "Заявка одобрена",
        "mvd_approve_body": "Поздравляем! Автомобили доступны к аренде. Какое из авто вы выберите первым?",
        
        # Уведомления о доставке
        "mechanic_assigned_title": "Механик назначен",
        "mechanic_assigned_body": "Механик принял ваш заказ доставки и готов начать.",
        
        "delivery_started_title": "Доставка начата",
        "delivery_started_body": "Механик начал доставку вашего автомобиля.",
        
        "delivery_completed_title": "Машина доставлена",
        "delivery_completed_body": "Ваш автомобиль успешно доставлен. Можете начинать аренду.",
        
        "delivery_cancelled_title": "Доставка отменена",
        "delivery_cancelled_body": "Доставка автомобиля {car_name} ({plate_number}) по заказу #{rental_id} была отменена.",
        
        # Уведомление для механиков о новом заказе
        "delivery_new_order_title": "Доставка: новый заказ",
        "delivery_new_order_body": "Нужно доставить клиенту {car_name} ({plate_number}).",
        
        # Уведомления о балансе
        "low_balance_title": "Низкий баланс",
        "low_balance_body": "На балансе {balance}₸ — осталось менее 1000₸.",
        
        "balance_exhausted_title": "Баланс исчерпан",
        "balance_exhausted_body": "Ваш баланс 0₸ — завершите аренду, чтобы избежать штрафов.",
        
        "engine_locked_due_to_balance_title": "Двигатель заблокирован",
        "engine_locked_due_to_balance_body": "Двигатель вашего автомобиля {car_name} заблокирован из-за задолженности.",
        
        # Уведомление о загрузке документов
        "documents_uploaded_title": "Ваши документы загружены",
        "documents_uploaded_body": "Ваши документы успешно загружены. Проверка займет до 24 часов.",
        
        # Уведомления о штрафах
        "delivery_delay_penalty_title": "Штраф за задержку доставки",
        "delivery_delay_penalty_body": "Списан штраф {penalty_fee}₸ за задержку доставки на {penalty_minutes} мин.",
        
        # Уведомления о тарифах и ожидании
        "pre_waiting_alert_title": "Скоро начнётся платное ожидание",
        "pre_waiting_alert_body": "Через {mins_left} мин бесплатного ожидания начнётся списание {price}₸/мин.",
        
        "waiting_started_title": "Началось платное ожидание",
        "waiting_started_body": "Списано за ожидание: {charge}₸ за {extra} мин.",
        
        "pre_overtime_alert_title": "Скоро закончится базовый тариф",
        "pre_overtime_alert_body": "Через {remaining} мин.",
        
        "overtime_charges_title": "Списания вне тарифта",
        "overtime_charges_body": "Списано сверхлимита: {charge}₸ за {extra} мин.",
        
        # Новая машина для осмотра
        "new_car_for_inspection_title": "Новая машина для осмотра",
        "new_car_for_inspection_body": "Аренда автомобиля {car_name} ({plate_number}) завершена. Требуется осмотр.",
        
        "inspection_assigned_by_admin_title": "Вам назначен осмотр",
        "inspection_assigned_by_admin_body": "Администратор назначил вас для осмотра автомобиля {car_name} ({plate_number}). Пожалуйста, проведите осмотр.",
        
        "inspection_unassigned_by_admin_title": "Назначение отменено",
        "inspection_unassigned_by_admin_body": "Администратор снял назначение на осмотр автомобиля {car_name} ({plate_number}).",

        # Повторная проверка документов по запросу финансиста
        "financier_request_recheck_title": "Требуется повторная проверка документов",
        "financier_request_recheck_body": "Пожалуйста, загрузите документы повторно для повторной проверки.",
        
        "fuel_empty_title": "Закончился бензин",
        "fuel_empty_body": "Топливо на нуле. Пожалуйста, заправьте авто, чтобы продолжить поездку.",
        
        "account_balance_low_title": "Заканчиваются деньги на аккаунте",
        "account_balance_low_body": "Баланс на исходе. Пополните счёт, чтобы избежать остановки аренды.",
        
        "zone_exit_title": "Выезд за зону",
        "zone_exit_body": "Вы вне зоны аренды. Вернитесь в разрешённую область, чтобы продолжить поездку.",
        
        "rpm_spikes_title": "Много резких скачков оборотов",
        "rpm_spikes_body": "Аккуратнее за рулём. Система фиксирует резкие скачки оборотов.",
        
        "verification_passed_title": "Проверка пройдена",
        "verification_passed_body": "Уважаемый клиент! Поздравляем Вас с успешным прохождением проверки. Ваша заявка одобрена.",
        
        "verification_failed_title": "Не прошли проверку",
        "verification_failed_body": "Уважаемый клиент! К сожалению, Ваша заявка не прошла проверку.",
        
        "promo_code_available_title": "Вам доступен промокод",
        "promo_code_available_body": "Вам начислен промокод! Используйте его и арендуйте авто выгоднее.",
        
        "guarantor_connected_title": "Гарант подключён",
        "guarantor_connected_body": "Гарант подключён. Теперь автомобили доступны к аренде!",
        
        "guarantor_accepted_title": "Гарант принял заявку",
        "guarantor_accepted_body": "Вы успешно приняли и подписали все условия. Теперь вы гарант для {client_name}",
        
        "fuel_refill_detected_title": "Обнаружена заправка",
        "fuel_refill_detected_body": "Заправка только 95/98 АИ. Использование другого топлива запрещено. После заправки оставьте чек в подлокотнике автомобиля.",
        
        "courier_found_title": "Нашёлся курьер",
        "courier_found_body": "Курьер найден. Ваш автомобиль уже в пути.",
        
        "courier_delivered_title": "Курьер доставил авто",
        "courier_delivered_body": "Доставлено! Курьер передал автомобиль на точку.",
        
        "fine_issued_title": "Вам начислен штраф",
        "fine_issued_body": "Санкция начислена. Проверьте детали в приложении.",
        
        "balance_top_up_title": "Ваш баланс пополнен",
        "balance_top_up_body": "Баланс успешно пополнен. Приятных поездок!",
        
        "basic_tariff_ending_title": "Основной тариф заканчивается",
        "basic_tariff_ending_body": "Тариф подходит к концу. После списание за поездку начнется в поминутном тарифе.",
        
        "locks_open_title": "Замки открыты",
        "locks_open_body": "Замки открыты. Закройте авто в приложении, чтобы защитить поездку.",
        
        "impact_weak_title": "Удар слабый",
        "impact_weak_body": "Фиксируем удар. На авто зарегистрировано столкновение. Проверьте состояние.",
        
        "impact_medium_title": "Удар средний",
        "impact_medium_body": "Фиксируем удар. На авто зарегистрировано столкновение. Проверьте состояние.",
        
        "impact_strong_title": "Удар сильный",
        "impact_strong_body": "Фиксируем удар. На авто зарегистрировано столкновение. Проверьте состояние.",
        
        "birthday_title": "День рождения",
        "birthday_body": "С днём рождения! AZV Motors желает вам безопасных дорог и дарит бонус 🎉",
        
        "friday_evening_title": "Пятница вечер",
        "friday_evening_body": "Начните выходные красиво — выберите свой автомобиль.",
        
        "monday_morning_title": "Понедельник утро",
        "monday_morning_body": "Удобный старт недели — авто доступны поблизости.",
        
        "new_car_available_title": "Новое авто",
        "new_car_available_body": "Новое авто в парке! Загляните — возможно, это ваш следующий выбор.",
        
        "car_nearby_title": "Машина рядом",
        "car_nearby_body": "Авто рядом с вами. Можно забронировать в один клик.",
        
        "holiday_greeting_title": "Поздравления с праздником",
        "holiday_greeting_body": "Празднуем вместе! AZV Motors поздравляет вас с праздником.",
        
        # Индивидуальные праздники Казахстана
        "new_year_title": "С Новым годом!",
        "new_year_body": "Поздравляем с Новым годом! AZV Motors желает вам счастья, здоровья и удачных поездок в новом году! 🎉",
        
        "christmas_title": "С Рождеством Христовым!",
        "christmas_body": "Поздравляем с Рождеством! Пусть этот светлый праздник принесёт вам радость и тепло. AZV Motors! ✨",
        
        "womens_day_title": "С Международным женским днём!",
        "womens_day_body": "Поздравляем с 8 Марта! Пусть каждый день будет наполнен красотой и счастьем. AZV Motors поздравляет всех женщин! 🌷",
        
        "nauryz_title": "С праздником Наурыз!",
        "nauryz_body": "Поздравляем с Наурызом! Пусть весна принесёт в ваш дом благополучие и радость. AZV Motors! 🌸",
        
        "unity_day_title": "С Днём единства народа Казахстана!",
        "unity_day_body": "Поздравляем с Днём единства народа Казахстана! Вместе мы сильнее! AZV Motors! 🇰🇿",
        
        "defender_day_title": "С Днём защитника Отечества!",
        "defender_day_body": "Поздравляем с Днём защитника Отечества! Благодарим за мужество и преданность. AZV Motors! 🎖️",
        
        "victory_day_title": "С Днём Победы!",
        "victory_day_body": "Поздравляем с Днём Победы! Помним и чтим подвиг героев. Спасибо за мир! AZV Motors! 🕊️",
        
        "capital_day_title": "С Днём столицы!",
        "capital_day_body": "Поздравляем с Днём столицы! Желаем процветания и благополучия! AZV Motors! 🏙️",
        
        "constitution_day_title": "С Днём Конституции!",
        "constitution_day_body": "Поздравляем с Днём Конституции Республики Казахстан! Пусть закон и справедливость всегда будут с нами. AZV Motors! ⚖️",
        
        "republic_day_title": "С Днём Республики!",
        "republic_day_body": "Поздравляем с Днём Республики! Гордимся нашей страной и её достижениями. AZV Motors! 🇰🇿",
        
        "independence_day_title": "С Днём Независимости!",
        "independence_day_body": "Поздравляем с Днём Независимости Республики Казахстан! Пусть наша страна процветает! AZV Motors! 🎆",
        
        "airport_location_title": "Локация аэропорта",
        "airport_location_body": "Добро пожаловать! На локации аэропорта доступны свободные авто.",
        
        "car_viewed_exit_title": "Авто всё ещё доступно",
        "car_viewed_exit_body": "Авто всё ещё доступно. Забронируйте в один клик, пока не увели.",
        
        "rental_extended_title": "Аренда продлена",
        "rental_extended_body": "Аренда успешно продлена на {days} {days_text}. Общая продолжительность: {new_duration} {days_text2}. Стоимость продления: {cost}₸."
    },
    
    "en": {
        # Отклонение финансистом - документы
        "financier_reject_documents_title": "Application Rejected",
        "financier_reject_documents_body": "Your documents are unreadable, please attach them again.",
        
        # Отклонение финансистом - отсутствуют сертификаты для граждан Казахстана
        "financier_reject_certificates_title": "Application Rejected",
        "financier_reject_certificates_body": "As a citizen of the Republic of Kazakhstan, you are required to provide certificates: from a psychoneurological dispensary, narcological dispensary, and pension contributions certificate.\nPlease attach the missing documents.",
        
        # Отклонение финансистом - финансовые причины
        "financier_reject_financial_title": "Application Rejected",
        "financier_reject_financial_body": "Unfortunately, during the verification of your data, we could not approve your application. However, you can use the «Guarantor» service by inviting a person who, if necessary, can bear material responsibility for you.",
        
        # Одобрение финансистом
        "financier_approve_title": "Application Approved",
        "financier_approve_body": "Your registration application has been approved, just wait a little more, and cars will be available to you. Access class: {auto_class}",
        
        # Отклонение МВД
        "mvd_reject_title": "Application Rejected",
        "mvd_reject_body": "We are forced to refuse registration. Based on the verification of your data, discrepancies with the service access requirements were identified. Please note that under clause 6.3.4 of the Agreement, the Lessor has the right to refuse to enter into an Agreement with the Client at its discretion. Best regards, «AZV Motors» Team.",
        
        # Одобрение МВД
        "mvd_approve_title": "Application Approved",
        "mvd_approve_body": "Congratulations! Cars are available for rent. Which car will you choose first?",
        
        # Уведомления о доставке
        "mechanic_assigned_title": "Mechanic Assigned",
        "mechanic_assigned_body": "A mechanic has accepted your delivery order and is ready to start.",
        
        "delivery_started_title": "Delivery Started",
        "delivery_started_body": "The mechanic has started delivering your car.",
        
        "delivery_completed_title": "Car Delivered",
        "delivery_completed_body": "Your car has been successfully delivered. You can start renting now.",
        
        "delivery_cancelled_title": "Delivery Cancelled",
        "delivery_cancelled_body": "Delivery of car {car_name} ({plate_number}) for order #{rental_id} has been cancelled.",
        
        # Уведомление для механиков о новом заказе
        "delivery_new_order_title": "Delivery: New Order",
        "delivery_new_order_body": "Need to deliver {car_name} ({plate_number}) to client.",
        
        # Уведомления о балансе
        "low_balance_title": "Low Balance",
        "low_balance_body": "Balance {balance}₸ — less than 1000₸ remaining.",
        
        "balance_exhausted_title": "Balance Exhausted",
        "balance_exhausted_body": "Your balance is 0₸ — complete rental to avoid penalties.",
        
        "engine_locked_due_to_balance_title": "Engine Locked",
        "engine_locked_due_to_balance_body": "The engine of your car {car_name} has been locked due to outstanding balance.",
        
        # Documents uploaded notification
        "documents_uploaded_title": "Your documents uploaded",
        "documents_uploaded_body": "Your documents have been successfully uploaded. Verification will take up to 24 hours.",
        
        # Уведомления о штрафах
        "delivery_delay_penalty_title": "Delivery Delay Penalty",
        "delivery_delay_penalty_body": "Penalty {penalty_fee}₸ charged for {penalty_minutes} min delivery delay.",
        
        # Уведомления о тарифах и ожидании
        "pre_waiting_alert_title": "Paid Waiting Starting Soon",
        "pre_waiting_alert_body": "In {mins_left} min, free waiting will end and {price}₸/min will be charged.",
        
        "waiting_started_title": "Paid Waiting Started",
        "waiting_started_body": "Charged for waiting: {charge}₸ for {extra} min.",
        
        "pre_overtime_alert_title": "Basic Tariff Ending Soon",
        "pre_overtime_alert_body": "In {remaining} min.",
        
        "overtime_charges_title": "Overtime Charges",
        "overtime_charges_body": "Overtime charged: {charge}₸ for {extra} min.",
        
        # New car for inspection
        "new_car_for_inspection_title": "New Car for Inspection",
        "new_car_for_inspection_body": "Rental of car {car_name} ({plate_number}) completed. Inspection required.",
        
        "inspection_assigned_by_admin_title": "Inspection Assigned",
        "inspection_assigned_by_admin_body": "Administrator assigned you to inspect vehicle {car_name} ({plate_number}). Please perform the inspection.",
        
        "inspection_unassigned_by_admin_title": "Assignment Cancelled",
        "inspection_unassigned_by_admin_body": "Administrator cancelled your assignment to inspect vehicle {car_name} ({plate_number}).",

        # Recheck requested by financier
        "financier_request_recheck_title": "Documents Recheck Required",
        "financier_request_recheck_body": "Please re-upload your documents for re-verification.",
        
        "fuel_empty_title": "Fuel Empty",
        "fuel_empty_body": "Fuel is at zero. Please refuel the car to continue your trip.",
        
        "account_balance_low_title": "Account Balance Running Low",
        "account_balance_low_body": "Balance is running out. Top up your account to avoid rental suspension.",
        
        "zone_exit_title": "Out of Zone",
        "zone_exit_body": "You are outside the rental zone. Return to the permitted area to continue your trip.",
        
        "rpm_spikes_title": "Multiple RPM Spikes",
        "rpm_spikes_body": "Drive carefully. The system is detecting sharp RPM spikes.",
        
        "verification_passed_title": "Verification Passed",
        "verification_passed_body": "Dear client! Congratulations on successfully passing the verification. Your application has been approved.",
        
        "verification_failed_title": "Verification Failed",
        "verification_failed_body": "Dear client! Unfortunately, your application did not pass verification.",
        
        "promo_code_available_title": "Promo Code Available",
        "promo_code_available_body": "You have received a promo code! Use it to rent a car at a better price.",
        
        "guarantor_connected_title": "Guarantor Connected",
        "guarantor_connected_body": "Guarantor connected. Cars are now available for rent!",
        
        "guarantor_accepted_title": "Guarantor Request Accepted",
        "guarantor_accepted_body": "You have successfully accepted and signed all terms. You are now a guarantor for {client_name}",
        
        "fuel_refill_detected_title": "Fuel Refill Detected",
        "fuel_refill_detected_body": "Only 95/98 AI fuel allowed. Use of other fuel is prohibited. After refueling, leave the receipt in the car's armrest.",
        
        "courier_found_title": "Courier Found",
        "courier_found_body": "Courier found. Your car is on the way.",
        
        "courier_delivered_title": "Courier Delivered",
        "courier_delivered_body": "Delivered! The courier has handed over the car at the location.",
        
        "fine_issued_title": "Fine Issued",
        "fine_issued_body": "A fine has been issued. Check the details in the app.",
        
        "balance_top_up_title": "Balance Topped Up",
        "balance_top_up_body": "Balance successfully topped up. Have a pleasant trip!",
        
        "basic_tariff_ending_title": "Basic Tariff Ending",
        "basic_tariff_ending_body": "The tariff is coming to an end. After that, charges for the trip will start at the per-minute rate.",
        
        "locks_open_title": "Locks Open",
        "locks_open_body": "Locks are open. Close the car in the app to protect your trip.",
        
        "impact_weak_title": "Weak Impact",
        "impact_weak_body": "Impact detected. A collision has been registered on the car. Check the condition.",
        
        "impact_medium_title": "Medium Impact",
        "impact_medium_body": "Impact detected. A collision has been registered on the car. Check the condition.",
        
        "impact_strong_title": "Strong Impact",
        "impact_strong_body": "Impact detected. A collision has been registered on the car. Check the condition.",
        
        "birthday_title": "Birthday",
        "birthday_body": "Happy Birthday! AZV Motors wishes you safe roads and gives you a bonus 🎉",
        
        "friday_evening_title": "Friday Evening",
        "friday_evening_body": "Start your weekend beautifully — choose your car.",
        
        "monday_morning_title": "Monday Morning",
        "monday_morning_body": "Convenient start to the week — cars available nearby.",
        
        "new_car_available_title": "New Car",
        "new_car_available_body": "New car in the fleet! Take a look — it might be your next choice.",
        
        "car_nearby_title": "Car Nearby",
        "car_nearby_body": "Car nearby. You can book it in one click.",
        
        "holiday_greeting_title": "Holiday Greetings",
        "holiday_greeting_body": "Let's celebrate together! AZV Motors congratulates you on the holiday.",
        
        "new_year_title": "Happy New Year!",
        "new_year_body": "Wishing you a Happy New Year! AZV Motors wishes you happiness, health, and safe travels in the new year! 🎉",
        
        "christmas_title": "Merry Christmas!",
        "christmas_body": "Wishing you a Merry Christmas! May this bright holiday bring you joy and warmth. AZV Motors! ✨",
        
        "womens_day_title": "Happy International Women's Day!",
        "womens_day_body": "Happy International Women's Day! May every day be filled with beauty and happiness. AZV Motors congratulates all women! 🌷",
        
        "nauryz_title": "Happy Nauryz!",
        "nauryz_body": "Happy Nauryz! May spring bring prosperity and joy to your home. AZV Motors! 🌸",
        
        "unity_day_title": "Happy Unity Day!",
        "unity_day_body": "Happy Unity Day of the People of Kazakhstan! Together we are stronger! AZV Motors! 🇰🇿",
        
        "defender_day_title": "Happy Defender's Day!",
        "defender_day_body": "Happy Defender of the Fatherland Day! Thank you for your courage and dedication. AZV Motors! 🎖️",
        
        "victory_day_title": "Happy Victory Day!",
        "victory_day_body": "Happy Victory Day! We remember and honor the heroes. Thank you for peace! AZV Motors! 🕊️",
        
        "capital_day_title": "Happy Capital City Day!",
        "capital_day_body": "Happy Capital City Day! Wishing you prosperity and success! AZV Motors! 🏙️",
        
        "constitution_day_title": "Happy Constitution Day!",
        "constitution_day_body": "Happy Constitution Day of the Republic of Kazakhstan! May law and justice always be with us. AZV Motors! ⚖️",
        
        "republic_day_title": "Happy Republic Day!",
        "republic_day_body": "Happy Republic Day! We are proud of our country and its achievements. AZV Motors! 🇰🇿",
        
        "independence_day_title": "Happy Independence Day!",
        "independence_day_body": "Happy Independence Day of the Republic of Kazakhstan! May our country prosper! AZV Motors! 🎆",
        
        "airport_location_title": "Airport Location",
        "airport_location_body": "Welcome! Free cars are available at the airport location.",
        
        "car_viewed_exit_title": "Car Still Available",
        "car_viewed_exit_body": "Car is still available. Book it in one click before it's taken.",
        
        "rental_extended_title": "Rental Extended",
        "rental_extended_body": "Rental successfully extended for {days} {days_text}. Total duration: {new_duration} {days_text2}. Extension cost: {cost}₸."
    },
    
    "kz": {
        # Отклонение финансистом - документы
        "financier_reject_documents_title": "Өтініш бас тартылды",
        "financier_reject_documents_body": "Сіздің құжаттарыңыз оқылмайды, қайта тіркеңіз.",
        
        # Отклонение финансистом - отсутствуют сертификаты для граждан Казахстана
        "financier_reject_certificates_title": "Өтініш бас тартылды",
        "financier_reject_certificates_body": "Қазақстан Республикасының азаматы ретінде сіз справкаларды ұсынуға міндеттісіз: психоневрологиялық диспансерден, наркологиялық диспансерден, зейнетақы жарналары туралы справка.\nЖетіспейтін құжаттарды тіркеңіз.",
        
        # Отклонение финансистом - финансовые причины
        "financier_reject_financial_title": "Өтініш бас тартылды",
        "financier_reject_financial_body": "Өкінішке орай, сіздің деректеріңізді тексеру барысында өтінішіңізді мақұлдай алмадық. Дегенмен, сіз «Кепіл» қызметін пайдалана аласыз, қажет болса, сіз үшін материалдық жауапкершілікті алатын адамды шақыру арқылы.",
        
        # Одобрение финансистом
        "financier_approve_title": "Өтініш мақұлданды",
        "financier_approve_body": "Сіздің тіркеу өтінішіңіз мақұлданды, сәл күтіңіз, және автомобильдер сізге қолжетімді болады. Қол жетімділік класы: {auto_class}",
        
        # Отклонение МВД
        "mvd_reject_title": "Өтініш бас тартылды",
        "mvd_reject_body": "Тіркеуден бас тартуға мәжбүрміз. Сіздің деректеріңізді тексеру нәтижесінде қызметке қол жетімділік талаптарына сәйкес келмейтін жерлер анықталды. Келісімшарттың 6.3.4-тармағына сәйкес, Жалдаушының Клиентпен Келісімшарт жасаудан бас тарту құқығы бар екенін ескертеміз. Құрметпен, «AZV Motors» командасы.",
        
        # Одобрение МВД
        "mvd_approve_title": "Өтініш мақұлданды",
        "mvd_approve_body": "Құттықтаймыз! Автомобильдер жалға беруге қолжетімді. Бірінші қай автомобильді таңдайсыз?",
        
        # Уведомления о доставке
        "mechanic_assigned_title": "Механик тағайындалды",
        "mechanic_assigned_body": "Механик сіздің жеткізу тапсырысыңызды қабылдап, бастауға дайын.",
        
        "delivery_started_title": "Жеткізу басталды",
        "delivery_started_body": "Механик сіздің автомобиліңізді жеткізуді бастады.",
        
        "delivery_completed_title": "Машина жеткізілді",
        "delivery_completed_body": "Сіздің автомобиліңіз сәтті жеткізілді. Енді жалға алуды бастай аласыз.",
        
        "delivery_cancelled_title": "Жеткізу бас тартылды",
        "delivery_cancelled_body": "{car_name} ({plate_number}) автомобилінің #{rental_id} тапсырысы бойынша жеткізуі бас тартылды.",
        
        # Уведомление для механиков о новом заказе
        "delivery_new_order_title": "Жеткізу: жаңа тапсырыс",
        "delivery_new_order_body": "Клиентке {car_name} ({plate_number}) жеткізу керек.",
        
        # Уведомления о балансе
        "low_balance_title": "Төмен баланс",
        "low_balance_body": "Баланс {balance}₸ — 1000₸-нан аз қалды.",
        
        "balance_exhausted_title": "Баланс таусылды",
        "balance_exhausted_body": "Сіздің балансыңыз 0₸ — айыппұлдардан аулақ болу үшін жалға алуды аяқтаңыз.",
        
        "engine_locked_due_to_balance_title": "Қозғалтқыш бұғатталды",
        "engine_locked_due_to_balance_body": "{car_name} көлігінің қозғалтқышы қарызға байланысты бұғатталды.",
        
        # Құжаттар жүктелген хабарлама
        "documents_uploaded_title": "Сіздің құжаттарыңыз жүктелді",
        "documents_uploaded_body": "Сіздің құжаттарыңыз сәтті жүктелді. Тексеру 24 сағатқа дейін созылады.",
        
        # Уведомления о штрафах
        "delivery_delay_penalty_title": "Жеткізу кешіктіру айыппұлы",
        "delivery_delay_penalty_body": "{penalty_minutes} мин жеткізу кешіктіру үшін {penalty_fee}₸ айыппұл алынды.",
        
        # Уведомления о тарифах и ожидании
        "pre_waiting_alert_title": "Ақылы күту жақында басталады",
        "pre_waiting_alert_body": "{mins_left} мин ішінде тегін күту аяқталады және {price}₸/мин алынады.",
        
        "waiting_started_title": "Ақылы күту басталды",
        "waiting_started_body": "Күту үшін алынды: {extra} мин үшін {charge}₸.",
        
        "pre_overtime_alert_title": "Негізгі тариф жақында аяқталады",
        "pre_overtime_alert_body": "{remaining} мин ішінде.",
        
        "overtime_charges_title": "Шектен тыс алымдар",
        "overtime_charges_body": "Шектен тыс алынды: {extra} мин үшін {charge}₸.",
        
        # Жаңа автомобильді тексеру
        "new_car_for_inspection_title": "Жаңа автомобильді тексеру",
        "new_car_for_inspection_body": "{car_name} ({plate_number}) автомобилінің жалға алуы аяқталды. Тексеру қажет.",
        
        # Механик осмотрға тағайындалды
        "inspection_assigned_by_admin_title": "Сізге тексеру тағайындалды",
        "inspection_assigned_by_admin_body": "Әкімші сізді {car_name} ({plate_number}) автомобилін тексеруге тағайындады. Тексеруді өткізіңіз.",
        
        # Механиктің тағайындауы алынды
        "inspection_unassigned_by_admin_title": "Тағайындау алынды",
        "inspection_unassigned_by_admin_body": "Әкімші {car_name} ({plate_number}) автомобилін тексеруге тағайындауды алды.",

        # Қаржы менеджерінің сұрауы бойынша құжаттарды қайта тексеру
        "financier_request_recheck_title": "Құжаттарды қайта тексеру қажет",
        "financier_request_recheck_body": "Қайта тексеру үшін құжаттарды қайта жүктеңіз.",
        
        "fuel_empty_title": "Жанармай бітті",
        "fuel_empty_body": "Жанармай нөлге жетті. Саяхатты жалғастыру үшін автомобильді жанармаймен толтырыңыз.",
        
        "account_balance_low_title": "Есептік жазбадағы ақша азайып жатыр",
        "account_balance_low_body": "Баланс таусылып жатыр. Жалға алуды тоқтатудан аулақ болу үшін есептік жазбаңызды толтырыңыз.",
        
        "zone_exit_title": "Ауданнан шығу",
        "zone_exit_body": "Сіз жалға алу аймағынан тыссыз. Саяхатты жалғастыру үшін рұқсат етілген аймаққа оралыңыз.",
        
        "rpm_spikes_title": "Көптеген айналым санының кенеттен өсуі",
        "rpm_spikes_body": "Колесте сақ болыңыз. Жүйе айналым санының кенеттен өсуін анықтап жатыр.",
        
        "verification_passed_title": "Тексеру өтті",
        "verification_passed_body": "Құрметті клиент! Тексеруді сәтті өткеніңізбен құттықтаймыз. Сіздің өтінішіңіз мақұлданды.",
        
        "verification_failed_title": "Тексеруден өте алмады",
        "verification_failed_body": "Құрметті клиент! Өкінішке орай, сіздің өтінішіңіз тексеруден өте алмады.",
        
        "promo_code_available_title": "Сізге промокод қолжетімді",
        "promo_code_available_body": "Сізге промокод берілді! Оны пайдаланып, автомобильді тиімдірек жалға алыңыз.",
        
        "guarantor_connected_title": "Кепіл қосылды",
        "guarantor_connected_body": "Кепіл қосылды. Енді автомобильдер жалға беруге қолжетімді!",
        
        "guarantor_accepted_title": "Кепіл өтінішті қабылдады",
        "guarantor_accepted_body": "Сіз барлық шарттарды сәтті қабылдап, қол қойдыңыз. Енді сіз {client_name} үшін кепілсіз",
        
        "fuel_refill_detected_title": "Жанармай толтыру анықталды",
        "fuel_refill_detected_body": "Тек 95/98 АИ жанармайына рұқсат етіледі. Басқа жанармайды пайдалану тыйым салынады. Жанармай толтырғаннан кейін чекті автомобильдің қолтықшасына қалдырыңыз.",
        
        "courier_found_title": "Курьер табылды",
        "courier_found_body": "Курьер табылды. Сіздің автомобиліңіз жолда.",
        
        "courier_delivered_title": "Курьер автомобильді жеткізді",
        "courier_delivered_body": "Жеткізілді! Курьер автомобильді нүктеге тапсырды.",
        
        "fine_issued_title": "Сізге айыппұл салынды",
        "fine_issued_body": "Санкция салынды. Детальдарды қосымшада тексеріңіз.",
        
        "balance_top_up_title": "Сіздің балансыңыз толтырылды",
        "balance_top_up_body": "Баланс сәтті толтырылды. Жақсы саяхаттар!",
        
        "basic_tariff_ending_title": "Негізгі тариф аяқталуда",
        "basic_tariff_ending_body": "Тариф аяқталуда. Осыдан кейін саяхат үшін алымдар минуттық тариф бойынша басталады.",
        
        "locks_open_title": "Құлыптар ашық",
        "locks_open_body": "Құлыптар ашық. Саяхатты қорғау үшін қосымшада автомобильді жабыңыз.",
        
        "impact_weak_title": "Әлсіз соққы",
        "impact_weak_body": "Соққы анықталды. Автомобильде соқтығысу тіркелді. Күйін тексеріңіз.",
        
        "impact_medium_title": "Орташа соққы",
        "impact_medium_body": "Соққы анықталды. Автомобильде соқтығысу тіркелді. Күйін тексеріңіз.",
        
        "impact_strong_title": "Күшті соққы",
        "impact_strong_body": "Соққы анықталды. Автомобильде соқтығысу тіркелді. Күйін тексеріңіз.",
        
        "birthday_title": "Туған күн",
        "birthday_body": "Туған күніңізбен! AZV Motors сізге қауіпсіз жолдар тілейді және сізге бонус сыйлайды 🎉",
        
        "friday_evening_title": "Жұма кеші",
        "friday_evening_body": "Демалысты әдемі бастаңыз — өз автомобиліңізді таңдаңыз.",
        
        "monday_morning_title": "Дүйсенбі таңы",
        "monday_morning_body": "Аптаны ыңғайлы бастаңыз — автомобильдер маңда қолжетімді.",
        
        "new_car_available_title": "Жаңа автомобиль",
        "new_car_available_body": "Паркте жаңа автомобиль! Қараңыз — бұл сіздің келесі таңдауыңыз болуы мүмкін.",
        
        "car_nearby_title": "Автомобиль маңда",
        "car_nearby_body": "Автомобиль маңда. Оны бір басып брондауға болады.",
        
        "holiday_greeting_title": "Мерекеге құттықтау",
        "holiday_greeting_body": "Бірге мерекелейік! AZV Motors сізді мерекемен құттықтайды.",
        # Қазақстанның мемлекеттік мерекелері
        "new_year_title": "Жаңа жылыңызбен!",
        "new_year_body": "Жаңа жылыңызбен құттықтаймыз! AZV Motors сізге бақыт, денсаулық және қауіпсіз сапарлар тілейді! 🎉",
        
        "christmas_title": "Рождество мерекесімен!",
        "christmas_body": "Рождество мерекесімен құттықтаймыз! Бұл жарқын мереке сізге қуаныш пен жылулық әкелсін. AZV Motors! ✨",
        
        "womens_day_title": "Халықаралық әйелдер күнімен!",
        "womens_day_body": "8 Наурыз - Халықаралық әйелдер күнімен құттықтаймыз! Әр күн сұлулық пен бақытқа толы болсын. AZV Motors барлық әйелдерді құттықтайды! 🌷",
        
        "nauryz_title": "Наурыз мейрамымен!",
        "nauryz_body": "Наурыз мейрамымен құттықтаймыз! Көктем үйіңізге береке мен қуаныш әкелсін. AZV Motors! 🌸",
        
        "unity_day_title": "Халықтар бірлігі күні құтты болсын!",
        "unity_day_body": "Бірлік күні құтты болсын! Бірлік пен татулық мәңгі болсын! AZV Motors! 🇰🇿",
        
        "defender_day_title": "Отан қорғаушылар күнімен!",
        "defender_day_body": "Отан қорғаушылар күнімен құттықтаймыз! Ерлік пен адалдық үшін рахмет! AZV Motors! 🎖️",
        
        "victory_day_title": "Жеңіс күнімен!",
        "victory_day_body": "Жеңіс күнімен құттықтаймыз! Батырлардың ерлігін есте сақтаймыз. Бейбітшілік үшін рахмет! AZV Motors! 🕊️",
        
        "capital_day_title": "Астана күнімен!",
        "capital_day_body": "Астана күнімен құттықтаймыз! Гүлдену мен табыс тілейміз! AZV Motors! 🏙️",
        
        "constitution_day_title": "Конституция күнімен!",
        "constitution_day_body": "Қазақстан Республикасы Конституциясы күнімен құттықтаймыз! Заң мен әділдік әрқашан бізбен болсын. AZV Motors! ⚖️",
        
        "republic_day_title": "Республика күнімен!",
        "republic_day_body": "Республика күнімен құттықтаймыз! Біз өз еліміз бен оның жетістіктерімен мақтанамыз. AZV Motors! 🇰🇿",
        
        "independence_day_title": "Тәуелсіздік күнімен!",
        "independence_day_body": "Қазақстан Республикасының Тәуелсіздік күнімен құттықтаймыз! Еліміз гүлденсін! AZV Motors! 🎆",
        
        "airport_location_title": "Әуежай орналасуы",
        "airport_location_body": "Қош келдіңіз! Әуежай орналасуында бос автомобильдер қолжетімді.",
        
        "car_viewed_exit_title": "Автомобиль әлі қолжетімді",
        "car_viewed_exit_body": "Автомобиль әлі қолжетімді. Ол алынбай тұрып, бір басып брондаңыз.",
        
        "rental_extended_title": "Жалға алу ұзартылды",
        "rental_extended_body": "Жалға алу {days} {days_text} үшін сәтті ұзартылды. Жаңа ұзақтығы: {new_duration} {days_text2}. Ұзарту құны: {cost}₸."
    },
    
    "zh": {
        # 财务拒绝 - 文件
        "financier_reject_documents_title": "申请被拒绝",
        "financier_reject_documents_body": "您的文件无法读取，请重新上传。",
        
        # 财务拒绝 - 哈萨克斯坦公民缺少证书
        "financier_reject_certificates_title": "申请被拒绝",
        "financier_reject_certificates_body": "作为哈萨克斯坦共和国公民，您必须提供以下证明：精神神经病学诊所证明、麻醉学诊所证明、养老金缴费证明。\n请上传缺失的文件。",
        
        # 财务拒绝 - 财务原因
        "financier_reject_financial_title": "申请被拒绝",
        "financier_reject_financial_body": "很抱歉，在审核您的数据时，我们无法批准您的申请。但您可以使用「担保人」服务，邀请一个在必要时可以为您承担物质责任的人。",
        
        # 财务批准
        "financier_approve_title": "申请已批准",
        "financier_approve_body": "您的注册申请已获批准，请稍等片刻，车辆将可供您使用。准入等级：{auto_class}",
        
        # 内务部拒绝
        "mvd_reject_title": "申请被拒绝",
        "mvd_reject_body": "我们不得不拒绝注册。根据对您数据的审核，发现了不符合服务访问要求的情况。请注意，根据合同第6.3.4条，出租方有权自行决定拒绝与客户签订合同。此致敬礼，«AZV Motors»团队。",
        
        # 内务部批准
        "mvd_approve_title": "申请已批准",
        "mvd_approve_body": "恭喜！车辆可供租赁。您会选择哪辆车作为第一辆？",
        
        # 交付通知
        "mechanic_assigned_title": "已分配技师",
        "mechanic_assigned_body": "技师已接受您的交付订单并准备开始。",
        
        "delivery_started_title": "交付已开始",
        "delivery_started_body": "技师已开始交付您的车辆。",
        
        "delivery_completed_title": "车辆已送达",
        "delivery_completed_body": "您的车辆已成功送达。现在可以开始租赁了。",
        
        "delivery_cancelled_title": "交付已取消",
        "delivery_cancelled_body": "订单 #{rental_id} 的车辆 {car_name} ({plate_number}) 的交付已取消。",
        
        # 技师新订单通知
        "delivery_new_order_title": "交付：新订单",
        "delivery_new_order_body": "需要向客户交付 {car_name} ({plate_number})。",
        
        # 余额通知
        "low_balance_title": "余额不足",
        "low_balance_body": "余额 {balance}₸ — 剩余不足 1000₸。",
        
        "balance_exhausted_title": "余额已用完",
        "balance_exhausted_body": "您的余额为 0₸ — 请完成租赁以避免罚款。",
        
        "engine_locked_due_to_balance_title": "发动机已锁定",
        "engine_locked_due_to_balance_body": "由于欠款，您的车辆 {car_name} 的发动机已被锁定。",
        
        # 文件已上传通知
        "documents_uploaded_title": "您的文件已上传",
        "documents_uploaded_body": "您的文件已成功上传。验证最多需要24小时。",
        
        # 罚款通知
        "delivery_delay_penalty_title": "交付延迟罚款",
        "delivery_delay_penalty_body": "因交付延迟 {penalty_minutes} 分钟，已扣除罚款 {penalty_fee}₸。",
        
        # 费率与等待通知
        "pre_waiting_alert_title": "付费等待即将开始",
        "pre_waiting_alert_body": "{mins_left} 分钟后，免费等待将结束，将按 {price}₸/分钟收费。",
        
        "waiting_started_title": "付费等待已开始",
        "waiting_started_body": "等待费用：{extra} 分钟 {charge}₸。",
        
        "pre_overtime_alert_title": "基本费率即将结束",
        "pre_overtime_alert_body": "{remaining} 分钟后。",
        
        "overtime_charges_title": "超时费用",
        "overtime_charges_body": "超时收费：{extra} 分钟 {charge}₸。",
        
        # 需要检查的新车
        "new_car_for_inspection_title": "需要检查的新车",
        "new_car_for_inspection_body": "车辆 {car_name} ({plate_number}) 的租赁已完成。需要检查。",
        
        "inspection_assigned_by_admin_title": "已分配检查任务",
        "inspection_assigned_by_admin_body": "管理员已指派您检查车辆 {car_name} ({plate_number})。请进行检查。",
        
        "inspection_unassigned_by_admin_title": "已取消分配",
        "inspection_unassigned_by_admin_body": "管理员已取消您对车辆 {car_name} ({plate_number}) 的检查任务。",

        # 财务要求重新检查文件
        "financier_request_recheck_title": "需要重新检查文件",
        "financier_request_recheck_body": "请重新上传文件以供重新审核。",
        
        "fuel_empty_title": "燃油已用完",
        "fuel_empty_body": "燃油为零。请加油以继续您的行程。",
        
        "account_balance_low_title": "账户余额不足",
        "account_balance_low_body": "余额即将用完。请充值以避免租赁暂停。",
        
        "zone_exit_title": "超出区域",
        "zone_exit_body": "您已超出租赁区域。请返回允许区域以继续您的行程。",
        
        "rpm_spikes_title": "多次转速突增",
        "rpm_spikes_body": "请小心驾驶。系统检测到转速突增。",
        
        "verification_passed_title": "验证通过",
        "verification_passed_body": "尊敬的客户！恭喜您成功通过验证。您的申请已获批准。",
        
        "verification_failed_title": "验证失败",
        "verification_failed_body": "尊敬的客户！很抱歉，您的申请未通过验证。",
        
        "promo_code_available_title": "您有可用的促销码",
        "promo_code_available_body": "您已收到促销码！使用它以更优惠的价格租车。",
        
        "guarantor_connected_title": "担保人已连接",
        "guarantor_connected_body": "担保人已连接。现在可以租车了！",
        
        "guarantor_accepted_title": "担保人请求已接受",
        "guarantor_accepted_body": "您已成功接受并签署所有条款。您现在是为 {client_name} 的担保人",
        
        "fuel_refill_detected_title": "检测到加油",
        "fuel_refill_detected_body": "仅允许使用95/98号汽油。禁止使用其他燃料。加油后，请将收据留在汽车的扶手箱中。",
        
        "courier_found_title": "找到快递员",
        "courier_found_body": "找到快递员。您的车辆正在路上。",
        
        "courier_delivered_title": "快递员已送达",
        "courier_delivered_body": "已送达！快递员已在指定地点交付车辆。",
        
        "fine_issued_title": "已开出罚单",
        "fine_issued_body": "已开出罚单。请在应用中查看详情。",
        
        "balance_top_up_title": "余额已充值",
        "balance_top_up_body": "余额已成功充值。祝您旅途愉快！",
        
        "basic_tariff_ending_title": "基本费率即将结束",
        "basic_tariff_ending_body": "费率即将结束。之后，行程费用将按每分钟费率开始计费。",
        
        "locks_open_title": "锁已打开",
        "locks_open_body": "锁已打开。请在应用中关闭车辆以保护您的行程。",
        
        "impact_weak_title": "轻微碰撞",
        "impact_weak_body": "检测到碰撞。车辆已记录碰撞。请检查状况。",
        
        "impact_medium_title": "中等碰撞",
        "impact_medium_body": "检测到碰撞。车辆已记录碰撞。请检查状况。",
        
        "impact_strong_title": "严重碰撞",
        "impact_strong_body": "检测到碰撞。车辆已记录碰撞。请检查状况。",
        
        "birthday_title": "生日",
        "birthday_body": "生日快乐！AZV Motors祝您道路安全并赠送您奖金 🎉",
        
        "friday_evening_title": "周五晚上",
        "friday_evening_body": "美好地开始您的周末 — 选择您的车辆。",
        
        "monday_morning_title": "周一早上",
        "monday_morning_body": "方便地开始新的一周 — 附近有可用车辆。",
        
        "new_car available_title": "新车",
        "new_car_available_body": "车队中有新车！看看 — 这可能是您的下一个选择。",
        
        "car_nearby_title": "附近有车",
        "car_nearby_body": "附近有车。您可以一键预订。",
        
        "holiday_greeting_title": "节日问候",
        "holiday_greeting_body": "让我们一起庆祝！AZV Motors祝贺您节日快乐。",
        # 哈萨克斯坦国家节日
        "new_year_title": "新年快乐！",
        "new_year_body": "祝您新年快乐！AZV Motors祝您新年幸福、健康、旅途平安！🎉",
        
        "christmas_title": "圣诞快乐！",
        "christmas_body": "祝您圣诞快乐！愿这个节日给您带来欢乐和温暖。AZV Motors！✨",
        
        "womens_day_title": "国际妇女节快乐！",
        "womens_day_body": "祝所有女性国际妇女节快乐！愿每一天都充满美丽和幸福。AZV Motors！🌷",
        
        "nauryz_title": "纳吾热孜节快乐！",
        "nauryz_body": "祝您纳吾热孜节快乐！愿春天为您的家庭带来繁荣和欢乐。AZV Motors！🌸",
        
        "unity_day_title": "人民团结日快乐！",
        "unity_day_body": "祝您哈萨克斯坦人民团结日快乐！团结就是力量！AZV Motors！🇰🇿",
        
        "defender_day_title": "祖国保卫者日快乐！",
        "defender_day_body": "祝您祖国保卫者日快乐！感谢您的勇气和奉献。AZV Motors！🎖️",
        
        "victory_day_title": "胜利日快乐！",
        "victory_day_body": "祝您胜利日快乐！我们铭记并尊敬英雄的功绩。感谢和平！AZV Motors！🕊️",
        
        "capital_day_title": "首都日快乐！",
        "capital_day_body": "祝您首都日快乐！祝愿繁荣和成功！AZV Motors！🏙️",
        
        "constitution_day_title": "宪法日快乐！",
        "constitution_day_body": "祝您哈萨克斯坦共和国宪法日快乐！愿法律和正义永远与我们同在。AZV Motors！⚖️",
        
        "republic_day_title": "共和国日快乐！",
        "republic_day_body": "祝您共和国日快乐！我们为我们的国家及其成就感到自豪。AZV Motors！🇰🇿",
        
        "independence_day_title": "独立日快乐！",
        "independence_day_body": "祝您哈萨克斯坦共和国独立日快乐！愿我们的国家繁荣昌盛！AZV Motors！🎆",
        
        "airport_location_title": "机场位置",
        "airport_location_body": "欢迎！机场位置有可用车辆。",
        
        "car_viewed_exit_title": "车辆仍然可用",
        "car_viewed_exit_body": "车辆仍然可用。在被预订之前一键预订。",
        
        "rental_extended_title": "租赁已延长",
        "rental_extended_body": "租赁已成功延长 {days} {days_text}。新时长：{new_duration} {days_text2}。延长费用：{cost}₸。"
    }
}


def get_notification_text(locale: str, key: str, **kwargs) -> tuple[str, str]:
    """
    Получить локализованный текст уведомления
    
    Args:
        locale: Язык пользователя (ru/en/kz/zh)
        key: Ключ перевода
        **kwargs: Параметры для форматирования строки
        
    Returns:
        tuple: (title, body) - заголовок и текст уведомления
    """
    if locale not in NOTIFICATIONS_TRANSLATIONS:
        locale = "ru"
    
    translations = NOTIFICATIONS_TRANSLATIONS[locale]
    
    title_key = f"{key}_title"
    body_key = f"{key}_body"
    
    title = translations.get(title_key, NOTIFICATIONS_TRANSLATIONS["ru"][title_key])
    body = translations.get(body_key, NOTIFICATIONS_TRANSLATIONS["ru"][body_key])
    
    if kwargs:
        title = title.format(**kwargs)
        body = body.format(**kwargs)
    
    return title, body
