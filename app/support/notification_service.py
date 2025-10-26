import asyncio
import logging
from typing import List, Optional
import httpx
from app.core.config import TELEGRAM_BOT_TOKEN_2, SUPPORT_GROUP_ID

logger = logging.getLogger(__name__)

class SupportNotificationService:
    def __init__(self):
        self.bot_token = TELEGRAM_BOT_TOKEN_2
        self.support_group_id = SUPPORT_GROUP_ID
        
    async def send_new_chat_notification(self, chat_data: dict):
        """Отправить уведомление о новом чате в группу поддержки"""
        try:
            message_text = (
                f"🔔 **Новое обращение в поддержку**\n\n"
                f"👤 **Клиент:** {chat_data['user_name']}\n"
                f"📞 **Телефон:** {chat_data['user_phone']}\n"
                f"🆔 **AZV ID:** {chat_data.get('azv_user_id', 'Не найден')}\n"
                f"📝 **Сообщение:** {chat_data['message_text'][:100]}...\n\n"
                f"**ID чата:** `{chat_data['chat_id']}`\n"
                f"**Telegram ID:** `{chat_data['user_telegram_id']}`"
            )
            
            await self._send_to_group(message_text)
            
        except Exception as e:
            logger.error(f"Error sending new chat notification: {e}")
    
    async def send_new_message_notification(self, chat_data: dict, message_text: str):
        """Отправить уведомление о новом сообщении в группу поддержки"""
        try:
            notification_text = (
                f"💬 **Новое сообщение от клиента**\n\n"
                f"👤 **Клиент:** {chat_data['user_name']}\n"
                f"📞 **Телефон:** {chat_data['user_phone']}\n"
                f"💬 **Сообщение:** {message_text[:100]}...\n\n"
                f"**ID чата:** `{chat_data['chat_id']}`"
            )
            
            await self._send_to_group(notification_text)
            
        except Exception as e:
            logger.error(f"Error sending new message notification: {e}")
    
    async def send_chat_assigned_notification(self, chat_data: dict, support_user_name: str):
        """Отправить уведомление о назначении чата"""
        try:
            notification_text = (
                f"✅ **Чат назначен**\n\n"
                f"👤 **Клиент:** {chat_data['user_name']}\n"
                f"📞 **Телефон:** {chat_data['user_phone']}\n"
                f"👨‍💼 **Назначен:** {support_user_name}\n\n"
                f"**ID чата:** `{chat_data['chat_id']}`"
            )
            
            await self._send_to_group(notification_text)
            
        except Exception as e:
            logger.error(f"Error sending chat assigned notification: {e}")
    
    async def send_chat_status_changed_notification(self, chat_data: dict, old_status: str, new_status: str):
        """Отправить уведомление об изменении статуса чата"""
        try:
            status_emojis = {
                'new': '🆕',
                'in_progress': '🔄',
                'resolved': '✅',
                'closed': '🔒'
            }
            
            status_names = {
                'new': 'Новое',
                'in_progress': 'В работе',
                'resolved': 'Решено',
                'closed': 'Закрыто'
            }
            
            notification_text = (
                f"📊 **Статус чата изменен**\n\n"
                f"👤 **Клиент:** {chat_data['user_name']}\n"
                f"📞 **Телефон:** {chat_data['user_phone']}\n"
                f"🔄 **Статус:** {status_emojis.get(old_status, '❓')} {status_names.get(old_status, old_status)} → "
                f"{status_emojis.get(new_status, '❓')} {status_names.get(new_status, new_status)}\n\n"
                f"**ID чата:** `{chat_data['chat_id']}`"
            )
            
            await self._send_to_group(notification_text)
            
        except Exception as e:
            logger.error(f"Error sending status change notification: {e}")
    
    async def _send_to_group(self, text: str):
        """Отправить сообщение в группу поддержки"""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            
            payload = {
                "chat_id": self.support_group_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                
                logger.info(f"Support notification sent to group: {self.support_group_id}")
                
        except Exception as e:
            logger.error(f"Failed to send support notification: {e}")
    
    async def send_daily_stats(self, stats: dict):
        """Отправить ежедневную статистику в группу поддержки"""
        try:
            stats_text = (
                f"📊 **Ежедневная статистика поддержки**\n\n"
                f"🆕 **Новых чатов:** {stats.get('new_chats', 0)}\n"
                f"🔄 **В работе:** {stats.get('in_progress_chats', 0)}\n"
                f"✅ **Решено:** {stats.get('resolved_chats', 0)}\n"
                f"🔒 **Закрыто:** {stats.get('closed_chats', 0)}\n"
                f"📈 **Всего чатов:** {stats.get('total_chats', 0)}\n\n"
                f"⏱️ **Среднее время ответа:** {stats.get('avg_response_time', 'N/A')} мин"
            )
            
            await self._send_to_group(stats_text)
            
        except Exception as e:
            logger.error(f"Error sending daily stats: {e}")


# Глобальный экземпляр сервиса
support_notification_service = SupportNotificationService()
