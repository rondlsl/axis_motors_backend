"""
Support System Integration
Система поддержки для AZV Motors
"""

from fastapi import FastAPI
from app.support.router import router as support_router
from app.support.telegram_bot import start_support_bot
from app.support.notification_service import support_notification_service
import asyncio
import logging

logger = logging.getLogger(__name__)

def setup_support_system(app: FastAPI, db_session_factory):
    """Настройка системы поддержки"""
    
    # Запускаем телеграм бота в фоновом режиме
    async def start_support_bot_task():
        # Запускаем бота поддержки в фоновой задаче
        asyncio.create_task(start_support_bot(db_session_factory))
    
    # Возвращаем функцию для запуска
    return start_support_bot_task


# Функция для тестирования уведомлений
async def test_support_notifications():
    """Тестовая функция для проверки уведомлений"""
    
    # Тестовые данные
    test_chat_data = {
        'user_name': 'Иван Иванов',
        'user_phone': '+77001234567',
        'azv_user_id': 'test-user-123',
        'message_text': 'Тестовое сообщение от клиента',
        'chat_id': 'test-chat-456',
        'user_telegram_id': 123456789
    }
    
    # Отправляем тестовые уведомления
    await support_notification_service.send_new_chat_notification(test_chat_data)
    await support_notification_service.send_new_message_notification(test_chat_data, "Новое тестовое сообщение")
    await support_notification_service.send_chat_assigned_notification(test_chat_data, "Тестовый Сотрудник")
    await support_notification_service.send_chat_status_changed_notification(test_chat_data, "new", "in_progress")
    
    # Тестовая статистика
    test_stats = {
        'new_chats': 5,
        'in_progress_chats': 3,
        'resolved_chats': 12,
        'closed_chats': 8,
        'total_chats': 28,
        'avg_response_time': 15.5
    }
    
    await support_notification_service.send_daily_stats(test_stats)
    
    logger.info("Test notifications sent successfully")


if __name__ == "__main__":
    # Запуск тестовых уведомлений
    asyncio.run(test_support_notifications())
