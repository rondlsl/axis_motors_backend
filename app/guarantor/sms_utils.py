import httpx
import logging
from app.core.config import SMS_TOKEN, logger


async def send_sms_mobizon(recipient: str, sms_text: str, api_key: str):
    """Отправка SMS через Mobizon API"""
    url = "https://api.mobizon.kz/service/message/sendsmsmessage"
    params = {
        "recipient": recipient,
        "text": sms_text,
        "apiKey": api_key,
        "from": "AZV Motors"
    }
    
    # Логируем детали запроса
    logger.info(f"[MOBIZON REQUEST] URL: {url}")
    logger.info(f"[MOBIZON REQUEST] Recipient: {recipient}")
    logger.info(f"[MOBIZON REQUEST] Text: {sms_text}")
    logger.info(f"[MOBIZON REQUEST] From: AZV Motors")
    logger.info(f"[MOBIZON REQUEST] API Key: {api_key[:8]}...{api_key[-4:] if len(api_key) > 12 else '***'}")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            logger.info(f"[MOBIZON REQUEST] Sending HTTP GET request...")
            response = await client.get(url, params=params)
            
            logger.info(f"[MOBIZON RESPONSE] Status Code: {response.status_code}")
            logger.info(f"[MOBIZON RESPONSE] Response Headers: {dict(response.headers)}")
            logger.info(f"[MOBIZON RESPONSE] Response Text: {response.text}")
            
            if response.status_code == 200:
                logger.info(f"[MOBIZON SUCCESS] SMS sent successfully to {recipient}")
            else:
                logger.error(f"[MOBIZON ERROR] Failed to send SMS. Status: {response.status_code}")
            
            return response.text
            
    except httpx.TimeoutException as e:
        logger.error(f"[MOBIZON TIMEOUT] Request timeout: {e}")
        raise
    except httpx.RequestError as e:
        logger.error(f"[MOBIZON REQUEST ERROR] Network error: {e}")
        raise
    except Exception as e:
        logger.error(f"[MOBIZON UNEXPECTED ERROR] Unexpected error: {e}")
        raise


async def send_guarantor_invitation_sms(guarantor_phone: str, requestor_first_name: str, requestor_last_name: str = None):
    """Отправка SMS приглашения гаранту"""
    logger.info(f"[GUARANTOR SMS] Starting guarantor invitation SMS to {guarantor_phone}")
    
    # Формируем имя для SMS
    if requestor_last_name:
        requestor_display_name = f"{requestor_first_name} {requestor_last_name}"
    else:
        requestor_display_name = requestor_first_name
    
    sms_text = f"{requestor_display_name} выбрал(а) вас в качестве Гаранта. Перейдите по ссылке и скачайте приложение"
    
    logger.info(f"[GUARANTOR SMS] SMS text: {sms_text}")
    
    # Если SMS_TOKEN = "6666" - тестовый режим, SMS не отправляем
    if SMS_TOKEN == "6666":
        logger.info(f"[GUARANTOR SMS] TEST MODE - SMS not sent to {guarantor_phone}: {sms_text}")
        print(f"TEST SMS to {guarantor_phone}: {sms_text}")
        return {"message": "TEST SMS sent successfully"}
    
    try:
        logger.info(f"[GUARANTOR SMS] Calling send_sms_mobizon for {guarantor_phone}")
        result = await send_sms_mobizon(guarantor_phone, sms_text, SMS_TOKEN)
        logger.info(f"[GUARANTOR SMS] Successfully sent invitation SMS to {guarantor_phone}")
        return {"message": "SMS sent successfully", "result": result}
    except Exception as e:
        logger.error(f"[GUARANTOR SMS ERROR] Failed to send SMS to {guarantor_phone}: {e}")
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


async def send_guarantor_approval_sms(guarantor_phone: str, client_first_name: str, client_last_name: str):
    """Отправка SMS гаранту при одобрении заявки администратором"""
    client_full_name = f"{client_first_name} {client_last_name}"
    
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