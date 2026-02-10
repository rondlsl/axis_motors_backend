import httpx
from datetime import datetime

from app.core.config import TELEGRAM_BOT_TOKEN_2, SUPPORT_GROUP_ID
from app.core.logging_config import get_logger
from app.partnership.schemas import PartnershipRequest

logger = get_logger(__name__)


async def send_partnership_to_bot(request: PartnershipRequest) -> bool:
    """
    Отправить заявку о сотрудничестве в Telegram бот.
    
    Args:
        request: Данные заявки
        
    Returns:
        True если отправка успешна, иначе False
    """
    try:
        message = format_partnership_message(request)
        success = await send_to_telegram(message, SUPPORT_GROUP_ID)
        
        if success:
            logger.info(f"Partnership request from {request.name} sent to bot")
        else:
            logger.error(f"Failed to send partnership request from {request.name}")
            
        return success
        
    except Exception as e:
        logger.error(f"Error sending partnership request: {e}")
        return False


def format_partnership_message(request: PartnershipRequest) -> str:
    """
    Сформировать сообщение о заявке на сотрудничество.
    
    Args:
        request: Данные заявки
        
    Returns:
        Отформатированное сообщение
    """
    message = f"""
🤝 **НОВАЯ ЗАЯВКА НА СОТРУДНИЧЕСТВО**

👤 **Имя:** {request.name}
📞 **Телефон:** {request.phone}"""
    
    if request.email:
        message += f"\n📧 **Email:** {request.email}"
    
    if request.company_name:
        message += f"\n🏢 **Компания:** {request.company_name}"
    
    if request.message:
        message += f"""

📄 **Сообщение:**
{request.message}"""
    
    message += f"""

⏰ **Время:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    
    return message


async def send_to_telegram(message: str, chat_id: str) -> bool:
    if not TELEGRAM_BOT_TOKEN_2 or not chat_id:
        logger.warning("Telegram bot token or chat ID not configured")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN_2}/sendMessage"
        
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    return True
                else:
                    logger.error(f"Telegram API error: {result.get('description', 'Unknown error')}")
                    return False
            else:
                logger.error(f"Telegram HTTP error: {response.status_code} - {response.text}")
                return False
                
    except httpx.TimeoutException:
        logger.error("Telegram request timeout")
        return False
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")
        return False
