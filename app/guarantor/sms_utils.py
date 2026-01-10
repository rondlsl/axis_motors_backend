import httpx
from app.core.config import SMS_TOKEN


async def send_sms_mobizon(recipient: str, sms_text: str, api_key: str):
    """Отправка SMS через Mobizon API"""
    url = "https://api.mobizon.kz/service/message/sendsmsmessage"
    params = {
        "recipient": recipient,
        "text": sms_text,
        "apiKey": api_key
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, params=params)
        return response.text


async def send_guarantor_invitation_sms(guarantor_phone: str, requestor_first_name: str, requestor_last_name: str = None, requestor_middle_name: str = None):
    """Отправка SMS приглашения гаранту"""
    # Формируем имя для SMS
    name_parts = [requestor_first_name]
    if requestor_middle_name:
        name_parts.append(requestor_middle_name)
    if requestor_last_name:
        name_parts.append(requestor_last_name)
    requestor_display_name = " ".join(name_parts)
    
    sms_text = f"""Здравствуйте!

{requestor_display_name} указал вас в качестве гаранта при подключении к сервису AZV Motors.
Гарант несет поручительство за клиента и обязуется компенсировать возможный материальный ущерб, причинённый по его вине в процессе пользования автомобилем.

Для подтверждения вашего согласия на данную ответственность, необходимо зарегестрироваться в нашем приложении перейдя по ссылке:
AppStore: https://apps.apple.com/kz/app/azv-motors/id6744049292
Google play:
В случае отказа — клиенту потребуется выбрать другого гаранта.

С уважением,
Команда AZV Motors"""
    
    # Если SMS_TOKEN = "6666" - тестовый режим, SMS не отправляем
    if SMS_TOKEN == "6666":
        print(f"TEST SMS to {guarantor_phone}: {sms_text}")
        return {"message": "TEST SMS sent successfully"}
    
    try:
        result = await send_sms_mobizon(guarantor_phone, sms_text, SMS_TOKEN)
        return {"message": "SMS sent successfully", "result": result}
    except Exception as e:
        print(f"SMS sending error: {e}")
        return {"message": "SMS sending failed", "error": str(e)}


async def send_user_rejection_with_guarantor_sms(user_phone: str, user_name: str, rejection_reason: str):
    """Отправка SMS об отказе с предложением гаранта"""
    sms_text = f"Вам отказано. Причина: {rejection_reason}. Однако вы можете воспользоваться услугой «Гарант». Гарант — это человек, который в случае ДТП или других обязательств несёт материальную ответственность за вас. Для оформления укажите данные человека: Имя, Фамилия, Отчество, Номер телефона."
    
    # Если SMS_TOKEN = "6666" - тестовый режим, SMS не отправляем
    if SMS_TOKEN == "6666":
        print(f"TEST SMS to {user_phone}: {sms_text}")
        return {"message": "TEST SMS sent successfully"}
    
    try:
        result = await send_sms_mobizon(user_phone, sms_text, SMS_TOKEN)
        return {"message": "SMS sent successfully", "result": result}
    except Exception as e:
        print(f"SMS sending error: {e}")
        return {"message": "SMS sending failed", "error": str(e)}


async def send_guarantor_approval_sms(guarantor_phone: str, client_first_name: str, client_last_name: str, client_middle_name: str = None):
    """Отправка SMS гаранту при одобрении заявки администратором"""
    name_parts = [client_first_name]
    if client_middle_name:
        name_parts.append(client_middle_name)
    if client_last_name:
        name_parts.append(client_last_name)
    client_full_name = " ".join(name_parts)
    
    sms_text = f"""Здравствуйте!

{client_full_name} указал вас в качестве гаранта при подключении к сервису AZV Motors.
Гарант несет поручительство за клиента и обязуется компенсировать возможный материальный ущерб, причинённый по его вине в процессе пользования автомобилем.

Для подтверждения вашего согласия на данную ответственность, необходимо зарегестрироваться в нашем приложении перейдя по ссылке:
AppStore: https://apps.apple.com/kz/app/azv-motors/id6744049292
Google Play: Скоро будет доступно
В случае отказа — клиенту потребуется выбрать другого гаранта.

С уважением,
Команда AZV Motors"""
    
    try:
        result = await send_sms_mobizon(guarantor_phone, sms_text, SMS_TOKEN)
        return {"message": "SMS sent successfully", "result": result}
    except Exception as e:
        print(f"SMS sending error: {e}")
        return {"message": "SMS sending failed", "error": str(e)}


async def send_rental_start_sms(
    client_phone: str, 
    rent_id: str, 
    full_name: str, 
    login: str, 
    client_id: str, 
    digital_signature: str, 
    car_id: str, 
    plate_number: str, 
    car_name: str
):
    """Отправка SMS при начале аренды"""
    sms_text = f"""Поездка c {rent_id} успешно начата! 

ФИО Клиента: {full_name}
Логин Клиента: {login}
ID Клиента: {client_id}
Электронная подпись: {digital_signature} 
ID аренды: {rent_id}
ID машины: {car_id}
Госномер машины: {plate_number}
Модель машины: {car_name}"""
    
    if SMS_TOKEN == "6666":
        print(f"TEST SMS to {client_phone}: {sms_text}")
        return {"message": "TEST SMS sent successfully"}
    
    try:
        result = await send_sms_mobizon(client_phone, sms_text, SMS_TOKEN)
        return {"message": "SMS sent successfully", "result": result}
    except Exception as e:
        print(f"SMS sending error: {e}")
        return {"message": "SMS sending failed", "error": str(e)}


async def send_rental_complete_sms(
    client_phone: str, 
    rent_id: str, 
    full_name: str, 
    login: str, 
    client_id: str, 
    digital_signature: str, 
    car_id: str, 
    plate_number: str, 
    car_name: str
):
    """Отправка SMS при завершении аренды"""
    sms_text = f"""Поездка c {rent_id} успешно завершена! 

ФИО Клиента: {full_name}
Логин Клиента: {login}
ID Клиента: {client_id}
Электронная подпись: {digital_signature} 
ID аренды: {rent_id}
ID машины: {car_id}
Госномер машины: {plate_number}
Модель машины: {car_name}"""
    
    if SMS_TOKEN == "6666":
        print(f"TEST SMS to {client_phone}: {sms_text}")
        return {"message": "TEST SMS sent successfully"}
    
    try:
        result = await send_sms_mobizon(client_phone, sms_text, SMS_TOKEN)
        return {"message": "SMS sent successfully", "result": result}
    except Exception as e:
        print(f"SMS sending error: {e}")
        return {"message": "SMS sending failed", "error": str(e)}


async def send_guarantor_contract_signed_sms(
    guarantor_phone: str,
    guarantor_full_name: str,
    guarantor_id: str,
    client_full_name: str,
    client_id: str
):
    """Отправка SMS гаранту после подписания всех договоров"""
    sms_text = f"""Поздравляем! Договоры подписаны. Вы {guarantor_full_name}, {guarantor_id} стали гарантом и несете ответственность за Клиента {client_full_name}, {client_id}.
ТОО «Объединение Азаева» - AZV Motors"""
    
    if SMS_TOKEN == "6666":
        print(f"TEST SMS to {guarantor_phone}: {sms_text}")
        return {"message": "TEST SMS sent successfully"}
    
    try:
        result = await send_sms_mobizon(guarantor_phone, sms_text, SMS_TOKEN)
        return {"message": "SMS sent successfully", "result": result}
    except Exception as e:
        print(f"SMS sending error: {e}")
        return {"message": "SMS sending failed", "error": str(e)}


async def send_client_guarantor_confirmed_sms(
    client_phone: str,
    guarantor_full_name: str,
    guarantor_id: str,
    client_full_name: str,
    client_id: str
):
    """Отправка SMS клиенту после подтверждения гаранта"""
    sms_text = f"""Поздравляем! Гарант {guarantor_full_name} (ID: {guarantor_id}) подтвердил ваш запрос на гаранта и взял ответственность по вашим договорам. Ваш ID: {client_id}, {client_full_name}.

ТОО «Объединение Азаева» - AZV Motors"""
    
    if SMS_TOKEN == "6666":
        print(f"TEST SMS to {client_phone}: {sms_text}")
        return {"message": "TEST SMS sent successfully"}
    
    try:
        result = await send_sms_mobizon(client_phone, sms_text, SMS_TOKEN)
        return {"message": "SMS sent successfully", "result": result}
    except Exception as e:
        print(f"SMS sending error: {e}")
        return {"message": "SMS sending failed", "error": str(e)}