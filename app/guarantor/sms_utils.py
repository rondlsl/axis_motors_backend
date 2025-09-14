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
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        return response.text


async def send_guarantor_invitation_sms(guarantor_phone: str, requestor_first_name: str, requestor_last_name: str = None):
    """Отправка SMS приглашения гаранту"""
    # Формируем имя для SMS
    if requestor_last_name:
        requestor_display_name = f"{requestor_first_name} {requestor_last_name}"
    else:
        requestor_display_name = requestor_first_name
    
    sms_text = f"{requestor_display_name} выбрал(а) вас в качестве Гаранта. Перейдите по ссылке и скачайте приложение"
    
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
