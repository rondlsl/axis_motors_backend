import asyncio
import logging
from typing import Dict, Optional
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from app.core.config import TELEGRAM_BOT_TOKEN_2
from app.services.support_service import SupportService
from app.models.support_chat_model import SupportChatStatus
from app.models.support_message_model import SupportMessageSenderType
from app.schemas.support_schemas import SupportChatCreate, SupportMessageCreate

logger = logging.getLogger(__name__)

# Состояния пользователей в боте
class BotState:
    WAITING_FOR_NAME = "waiting_for_name"
    WAITING_FOR_PHONE = "waiting_for_phone"
    WAITING_FOR_MESSAGE = "waiting_for_message"
    IN_CHAT = "in_chat"

# Хранилище состояний пользователей
user_states: Dict[int, Dict] = {}


class SupportBot:
    def __init__(self, db_session_factory):
        self.db_session_factory = db_session_factory
        
        # Проверяем токен бота
        if not TELEGRAM_BOT_TOKEN_2:
            print("TELEGRAM_BOT_TOKEN_2 не установлен!")
            raise ValueError("TELEGRAM_BOT_TOKEN_2 не установлен")
        
        print(f"Инициализируем бота с токеном: {TELEGRAM_BOT_TOKEN_2[:10]}...")
        self.application = Application.builder().token(TELEGRAM_BOT_TOKEN_2).build()
        self.setup_handlers()

    def setup_handlers(self):
        """Настройка обработчиков команд"""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /start"""
        user = update.effective_user
        
        keyboard = [
            [InlineKeyboardButton("🆘 Обратиться в техподдержку", callback_data="start_support")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_text = (
            f"👋 Привет, {user.first_name}!\n\n"
            "Добро пожаловать в службу поддержки AZV Motors!\n\n"
            "Здесь вы можете получить помощь по любым вопросам, связанным с нашим сервисом."
        )
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /help"""
        help_text = (
            "📋 Доступные команды:\n\n"
            "/start - Начать работу с ботом\n"
            "/help - Показать эту справку\n\n"
            "Для обращения в поддержку нажмите кнопку 'Обратиться в техподдержку'"
        )
        await update.message.reply_text(help_text)

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатий на кнопки"""
        print("Получен callback!")
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        print(f"Callback от пользователя {user_id}, data: {query.data}")
        
        if query.data == "start_support":
            print("Обрабатываем start_support")
            await self.start_support_process(query)

    async def start_support_process(self, query):
        """Начать процесс обращения в поддержку"""
        user_id = query.from_user.id
        
        # Проверяем, есть ли активный чат
        db = self.db_session_factory()
        try:
            support_service = SupportService(db)
            existing_chat = support_service.get_chat_by_telegram_id(user_id)
            
            if existing_chat:
                await query.edit_message_text(
                    f"✅ У вас уже есть активное обращение в поддержку!\n\n"
                    f"Статус: {self.get_status_text(existing_chat.status)}\n"
                    f"Создано: {existing_chat.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
                    "Вы можете продолжить общение, просто отправьте сообщение."
                )
                user_states[user_id] = {"state": BotState.IN_CHAT, "chat_id": existing_chat.id}
                return
            
            # Начинаем процесс создания нового чата
            user_states[user_id] = {"state": BotState.WAITING_FOR_NAME}
            
            await query.edit_message_text(
                "📝 Для создания обращения в поддержку нам нужна некоторая информация.\n\n"
                "Пожалуйста, введите ваше ФИО (Фамилия Имя Отчество):"
            )
            
        finally:
            db.close()

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений"""
        user = update.effective_user
        user_id = user.id
        message_text = update.message.text
        
        if user_id not in user_states:
            await self.start_command(update, context)
            return
        
        state = user_states[user_id]["state"]
        
        if state == BotState.WAITING_FOR_NAME:
            await self.handle_name_input(update, message_text)
        elif state == BotState.WAITING_FOR_PHONE:
            await self.handle_phone_input(update, message_text)
        elif state == BotState.WAITING_FOR_MESSAGE:
            await self.handle_message_input(update, message_text)
        elif state == BotState.IN_CHAT:
            await self.handle_chat_message(update, message_text)

    async def handle_name_input(self, update: Update, name: str):
        """Обработка ввода имени"""
        user_id = update.effective_user.id
        
        if len(name.strip()) < 3:
            await update.message.reply_text("❌ Пожалуйста, введите полное ФИО (минимум 3 символа)")
            return
        
        user_states[user_id]["name"] = name.strip()
        user_states[user_id]["state"] = BotState.WAITING_FOR_PHONE
        
        await update.message.reply_text(
            "📞 Теперь введите ваш номер телефона в формате +7XXXXXXXXXX:"
        )

    async def handle_phone_input(self, update: Update, phone: str):
        """Обработка ввода телефона"""
        user_id = update.effective_user.id
        
        # Простая валидация номера телефона
        phone = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        
        if not phone.startswith("+7") or len(phone) != 12:
            await update.message.reply_text(
                "❌ Пожалуйста, введите номер телефона в формате +7XXXXXXXXXX"
            )
            return
        
        user_states[user_id]["phone"] = phone
        user_states[user_id]["state"] = BotState.WAITING_FOR_MESSAGE
        
        await update.message.reply_text(
            "💬 Отлично! Теперь опишите вашу проблему или вопрос:\n\n"
            "Чем подробнее вы опишете ситуацию, тем быстрее мы сможем вам помочь."
        )

    async def handle_message_input(self, update: Update, message_text: str):
        """Обработка ввода сообщения и создание чата"""
        user = update.effective_user
        user_id = user.id
        
        if len(message_text.strip()) < 10:
            await update.message.reply_text(
                "❌ Пожалуйста, опишите вашу проблему более подробно (минимум 10 символов)"
            )
            return
        
        # Создаем чат поддержки
        db = self.db_session_factory()
        try:
            support_service = SupportService(db)
            
            chat_data = SupportChatCreate(
                user_telegram_id=user_id,
                user_telegram_username=user.username,
                user_name=user_states[user_id]["name"],
                user_phone=user_states[user_id]["phone"],
                message_text=message_text
            )
            
            chat = support_service.create_chat(chat_data)
            
            # Отправляем уведомление в группу поддержки
            await self.send_notification_to_support_group(chat)
            
            user_states[user_id] = {"state": BotState.IN_CHAT, "chat_id": chat.id}
            
            await update.message.reply_text(
                f"✅ Ваше обращение создано!\n\n"
                f"Номер обращения: {chat.sid}\n"
                f"Статус: {self.get_status_text(chat.status)}\n\n"
                "Наш специалист свяжется с вами в ближайшее время. "
                "Вы можете продолжить общение, просто отправляя сообщения."
            )
            
        except Exception as e:
            logger.error(f"Error creating support chat: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка при создании обращения. Попробуйте еще раз."
            )
        finally:
            db.close()

    async def handle_chat_message(self, update: Update, message_text: str):
        """Обработка сообщений в активном чате"""
        user_id = update.effective_user.id
        chat_id = user_states[user_id]["chat_id"]
        
        db = self.db_session_factory()
        try:
            support_service = SupportService(db)
            
            message_data = SupportMessageCreate(
                chat_id=chat_id,
                sender_type=SupportMessageSenderType.CLIENT,
                message_text=message_text
            )
            
            support_service.add_message(message_data)
            
            # Отправляем уведомление в группу поддержки
            chat = support_service.get_chat_by_id(chat_id)
            await self.send_message_notification_to_support_group(chat, message_text)
            
            await update.message.reply_text("✅ Сообщение отправлено!")
            
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            await update.message.reply_text("❌ Ошибка при отправке сообщения")
        finally:
            db.close()

    async def send_notification_to_support_group(self, chat):
        """Отправить уведомление о новом чате в группу поддержки"""
        try:
            notification_text = (
                f"🔔 Новое обращение в поддержку\n\n"
                f"👤 Клиент: {chat.user_name}\n"
                f"📞 Телефон: {chat.user_phone}\n"
                f"🆔 AZV ID: {chat.azv_user.sid if chat.azv_user else 'Не найден'}\n"
                f"📝 Сообщение: {chat.messages[0].message_text[:100]}...\n\n"
                f"ID чата: {chat.sid}"
            )
            
            await self.send_to_support_group(notification_text)
            
        except Exception as e:
            logger.error(f"Error sending notification: {e}")

    async def send_message_notification_to_support_group(self, chat, message_text):
        """Отправить уведомление о новом сообщении в группу поддержки"""
        try:
            notification_text = (
                f"💬 Новое сообщение от клиента\n\n"
                f"👤 Клиент: {chat.user_name}\n"
                f"📞 Телефон: {chat.user_phone}\n"
                f"💬 Сообщение: {message_text[:100]}...\n\n"
                f"ID чата: {chat.sid}"
            )
            
            await self.send_to_support_group(notification_text)
            
        except Exception as e:
            logger.error(f"Error sending message notification: {e}")

    async def send_to_support_group(self, text: str):
        """Отправить сообщение в группу поддержки"""
        # Здесь нужно добавить логику отправки в группу поддержки
        # Пока просто логируем
        logger.info(f"Support group notification: {text}")

    def get_status_text(self, status: str) -> str:
        """Получить текстовое описание статуса"""
        status_map = {
            SupportChatStatus.NEW: "🆕 Новое",
            SupportChatStatus.IN_PROGRESS: "🔄 В работе",
            SupportChatStatus.RESOLVED: "✅ Решено",
            SupportChatStatus.CLOSED: "🔒 Закрыто"
        }
        return status_map.get(status, "❓ Неизвестно")

    async def run(self):
        """Запуск бота"""
        print("Starting support bot...")
        try:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            print("Бот поддержки запущен и работает!")
            
            # Ждем бесконечно (бот работает в фоне)
            await asyncio.Event().wait()
        except Exception as e:
            print(f"Ошибка запуска бота: {e}")
            raise


# Функция для запуска бота
async def start_support_bot(db_session_factory):
    """Запустить бота поддержки"""
    try:
        print("Создаем экземпляр бота поддержки...")
        bot = SupportBot(db_session_factory)
        print("Бот создан, запускаем polling...")
        await bot.run()
    except Exception as e:
        print(f"Ошибка запуска бота поддержки: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
