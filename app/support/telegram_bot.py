import asyncio
import logging
import traceback
import os
import uuid
from typing import Dict, Optional
from pathlib import Path
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

# Хранилище состояний ожидания ответа от поддержки (для работы в группе)
# Ключ: user_id поддержки, Значение: {"chat_id": str, "client_telegram_id": int}
support_reply_states: Dict[int, Dict] = {}


class SupportBot:
    def __init__(self, db_session_factory):
        self.db_session_factory = db_session_factory
        
        # Проверяем токен бота
        if not TELEGRAM_BOT_TOKEN_2:
            raise ValueError("TELEGRAM_BOT_TOKEN_2 не установлен")
        
        self.application = Application.builder().token(TELEGRAM_BOT_TOKEN_2).build()
        self.setup_handlers()

    def setup_handlers(self):
        """Настройка обработчиков команд"""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("cancel", self.cancel_command))
        self.application.add_handler(CallbackQueryHandler(self.button_callback))

        def has_document(update: Update) -> bool:
            return update.message and update.message.document is not None
        
        self.application.add_handler(MessageHandler(filters.PHOTO, self.handle_media))
        self.application.add_handler(MessageHandler(has_document, self.handle_media))
        self.application.add_handler(MessageHandler(filters.VIDEO, self.handle_media))
        self.application.add_handler(MessageHandler(filters.AUDIO, self.handle_media))
        self.application.add_handler(MessageHandler(filters.VOICE, self.handle_media))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /start"""
        # Игнорируем команды в группах и супергруппах
        if update.message.chat.type in ['group', 'supergroup']:
            return
        
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
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /cancel"""
        user_id = update.effective_user.id
        
        # Отмена ответа в группе поддержки
        if update.message.chat.type in ['group', 'supergroup']:
            if user_id in support_reply_states:
                del support_reply_states[user_id]
                await update.message.reply_text("❌ Ответ отменен")
            else:
                await update.message.reply_text("ℹ️ Нет активного ответа для отмены")
            return
        
        # Отмена в личном чате (если есть активное состояние)
        if user_id in user_states:
            del user_states[user_id]
            await update.message.reply_text("❌ Операция отменена")
        else:
            await update.message.reply_text("ℹ️ Нет активной операции для отмены")

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатий на кнопки"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        
        if query.data == "start_support":
            await self.start_support_process(query)
        elif query.data.startswith("reply_"):
            # Обработка кнопки "Ответить" из группы
            chat_id = query.data.replace("reply_", "")
            await self.handle_reply_button(query, chat_id)

    async def start_support_process(self, query):
        """Начать процесс обращения в поддержку"""
        user_id = query.from_user.id
        
        # Проверяем, есть ли активный чат
        db_gen = self.db_session_factory()
        db = next(db_gen)
        try:
            support_service = SupportService(db)
            existing_chat = support_service.get_chat_by_telegram_id(user_id)
            
            if existing_chat:
                await query.edit_message_text(
                    f"У вас уже есть активное обращение в поддержку!\n\n"
                    f"Статус: {self.get_status_text(existing_chat.status)}\n"
                    f"Создано: {existing_chat.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
                    "Вы можете продолжить общение, просто отправьте сообщение."
                )
                user_states[user_id] = {"state": BotState.IN_CHAT, "chat_id": existing_chat.sid}
                return
            
            # Начинаем процесс создания нового чата
            user_states[user_id] = {"state": BotState.WAITING_FOR_NAME}
            
            await query.edit_message_text(
                "📝 Для создания обращения в поддержку нам нужна некоторая информация.\n\n"
                "Пожалуйста, введите ваше ФИО (Фамилия Имя Отчество):"
            )
            
        except Exception as e:
            logger.error(f"Ошибка в start_support_process: {e}")
        finally:
            db.close()

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений"""
        user = update.effective_user
        user_id = user.id
        message_text = update.message.text
        
        # Обработка сообщений в группах (ответы от поддержки)
        if update.message.chat.type in ['group', 'supergroup']:
            if user_id in support_reply_states:
                await self.handle_support_reply(update, message_text)
            return
        
        # Обработка сообщений от клиентов (личные чаты)
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
        db_gen = self.db_session_factory()
        db = next(db_gen)
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
            
            user_states[user_id] = {"state": BotState.IN_CHAT, "chat_id": chat.sid}
            
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
        
        db_gen = self.db_session_factory()
        db = next(db_gen)
        try:
            support_service = SupportService(db)
            
            message_data = SupportMessageCreate(
                chat_id=chat_id,
                sender_type=SupportMessageSenderType.CLIENT,
                message_text=message_text
            )
            
            saved_message = support_service.add_message(message_data)
            
            saved_message.telegram_message_id = update.message.message_id
            saved_message.telegram_chat_id = update.message.chat.id
            db.commit()
            
            # Отправляем уведомление в группу поддержки
            chat = support_service.get_chat_by_sid(chat_id)
            if chat:
                await self.send_message_notification_to_support_group(chat, message_text)
            
            await update.message.reply_text("✅ Сообщение отправлено!")
            
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            await update.message.reply_text("❌ Ошибка при отправке сообщения")
        finally:
            db.close()

    async def handle_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка медиа файлов (фото, документы, видео, аудио)"""
        user = update.effective_user
        user_id = user.id
        
        # Игнорируем медиа в группах
        if update.message.chat.type in ['group', 'supergroup']:
            return
        
        # Проверяем, есть ли активный чат
        if user_id not in user_states:
            await update.message.reply_text(
                "❌ У вас нет активного обращения в поддержку. "
                "Используйте /start для создания нового обращения."
            )
            return
        
        state = user_states[user_id].get("state")
        if state != BotState.IN_CHAT:
            await update.message.reply_text(
                "❌ Пожалуйста, сначала создайте обращение в поддержку через /start"
            )
            return
        
        chat_id = user_states[user_id]["chat_id"]
        message = update.message
        
        # Определяем тип медиа и получаем файл
        media_type = None
        file_obj = None
        file_name = None
        file_size = None
        caption = message.caption or ""
        
        if message.photo:
            # Берем самое большое фото
            file_obj = message.photo[-1]
            media_type = "photo"
            file_name = f"photo_{file_obj.file_id}.jpg"
        elif message.document:
            file_obj = message.document
            media_type = "document"
            file_name = file_obj.file_name or f"document_{file_obj.file_id}"
            file_size = file_obj.file_size
        elif message.video:
            file_obj = message.video
            media_type = "video"
            file_name = file_obj.file_name or f"video_{file_obj.file_id}.mp4"
            file_size = file_obj.file_size
        elif message.audio:
            file_obj = message.audio
            media_type = "audio"
            file_name = file_obj.file_name or f"audio_{file_obj.file_id}.mp3"
            file_size = file_obj.file_size
        elif message.voice:
            file_obj = message.voice
            media_type = "voice"
            file_name = f"voice_{file_obj.file_id}.ogg"
            file_size = file_obj.file_size
        
        if not file_obj:
            await update.message.reply_text("❌ Не удалось обработать медиа файл")
            return
        
        try:
            # Скачиваем файл
            media_url = await self.download_telegram_file(file_obj, media_type)
            
            if not media_url:
                await update.message.reply_text("❌ Ошибка при сохранении файла")
                return
            
            # Сохраняем сообщение в БД
            db_gen = self.db_session_factory()
            db = next(db_gen)
            try:
                support_service = SupportService(db)
                
                message_data = SupportMessageCreate(
                    chat_id=chat_id,
                    sender_type=SupportMessageSenderType.CLIENT,
                    message_text=caption or f"[{media_type.upper()}]",
                    media_type=media_type,
                    media_url=media_url,
                    media_file_name=file_name,
                    media_file_size=file_size
                )
                
                saved_message = support_service.add_message(message_data)
                
                saved_message.telegram_message_id = message.message_id
                saved_message.telegram_chat_id = message.chat.id
                db.commit()
                
                # Отправляем медиа в группу поддержки
                chat = support_service.get_chat_by_sid(chat_id)
                if chat:
                    await self.send_media_to_support_group(chat, file_obj, media_type, file_name, caption)
                
                await update.message.reply_text("✅ Медиа файл отправлен!")
                
            except Exception as e:
                logger.error(f"Error saving media message: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                await update.message.reply_text("❌ Ошибка при отправке медиа файла")
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error handling media: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            await update.message.reply_text("❌ Ошибка при обработке медиа файла")

    async def download_telegram_file(self, file_obj, media_type: str) -> Optional[str]:
        """Скачать файл из Telegram и сохранить локально"""
        try:
            # Получаем информацию о файле
            file_info = await self.application.bot.get_file(file_obj.file_id)
            
            # Создаем директорию для медиа поддержки
            upload_dir = Path("uploads/support")
            upload_dir.mkdir(parents=True, exist_ok=True)
            
            # Генерируем уникальное имя файла
            file_extension = Path(file_info.file_path).suffix if file_info.file_path else ""
            if not file_extension:
                # Определяем расширение по типу медиа
                extensions = {
                    "photo": ".jpg",
                    "document": Path(file_info.file_path).suffix if file_info.file_path else ".bin",
                    "video": ".mp4",
                    "audio": ".mp3",
                    "voice": ".ogg"
                }
                file_extension = extensions.get(media_type, ".bin")
            
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            file_path = upload_dir / unique_filename
            
            # Скачиваем файл
            async with httpx.AsyncClient() as client:
                download_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN_2}/{file_info.file_path}"
                response = await client.get(download_url, timeout=30.0)
                response.raise_for_status()
                
                # Сохраняем файл
                with open(file_path, "wb") as f:
                    f.write(response.content)
            
            # Возвращаем относительный путь
            return str(file_path.relative_to(Path(".")))
            
        except Exception as e:
            logger.error(f"Error downloading Telegram file: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    async def send_notification_to_support_group(self, chat):
        """Отправить уведомление о новом чате в группу поддержки"""
        try:
            # Get first message text safely
            first_message = chat.messages[0].message_text if chat.messages and len(chat.messages) > 0 else "Нет сообщения"
            
            telegram_username = f"@{chat.user_telegram_username}" if chat.user_telegram_username else "Не указан"
            
            notification_text = (
                f"🔔 Новое обращение в поддержку\n\n"
                f"👤 Клиент: {chat.user_name}\n"
                f"📞 Телефон: {chat.user_phone}\n"
                f"📱 Telegram: {telegram_username}\n"
                f"🆔 AZV ID: {chat.azv_user.sid if chat.azv_user else 'Не найден'}\n"
                f"📝 Сообщение: {first_message}\n\n"
                f"ID чата: {chat.sid}"
            )
            
            # Создаем кнопку "Ответить"
            keyboard = [
                [InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{chat.sid}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await self.send_to_support_group(notification_text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error sending notification: {e}")

    async def send_media_to_support_group(self, chat, file_obj, media_type: str, file_name: str, caption: str = ""):
        """Отправить медиа файл в группу поддержки"""
        try:
            from app.core.config import SUPPORT_GROUP_ID
            
            if not SUPPORT_GROUP_ID:
                logger.warning("SUPPORT_GROUP_ID не установлен")
                return
            
            telegram_username = f"@{chat.user_telegram_username}" if chat.user_telegram_username else "Не указан"
            
            # Формируем подпись с информацией о клиенте
            media_caption = (
                f"📎 {media_type.upper()}: {file_name}\n\n"
                f"👤 Клиент: {chat.user_name}\n"
                f"📞 Телефон: {chat.user_phone}\n"
                f"📱 Telegram: {telegram_username}\n"
            )
            if caption:
                media_caption += f"💬 Подпись: {caption}\n"
            media_caption += f"\nID чата: {chat.sid}"
            
            if len(media_caption) > 1024:
                media_caption = media_caption[:1021] + "..."
            
            keyboard = [
                [InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{chat.sid}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                if media_type == "photo":
                    # Для фото используем send_photo
                    await self.application.bot.send_photo(
                        chat_id=SUPPORT_GROUP_ID,
                        photo=file_obj.file_id,
                        caption=media_caption,
                        reply_markup=reply_markup
                    )
                    
                elif media_type == "document":
                    # Для документов используем send_document
                    await self.application.bot.send_document(
                        chat_id=SUPPORT_GROUP_ID,
                        document=file_obj.file_id,
                        caption=media_caption,
                        reply_markup=reply_markup
                    )
                    
                elif media_type == "video":
                    # Для видео используем send_video
                    await self.application.bot.send_video(
                        chat_id=SUPPORT_GROUP_ID,
                        video=file_obj.file_id,
                        caption=media_caption,
                        reply_markup=reply_markup
                    )
                    
                elif media_type == "audio":
                    # Для аудио используем send_audio
                    await self.application.bot.send_audio(
                        chat_id=SUPPORT_GROUP_ID,
                        audio=file_obj.file_id,
                        caption=media_caption,
                        reply_markup=reply_markup
                    )
                    
                elif media_type == "voice":
                    # Для голосовых сообщений используем send_voice
                    await self.application.bot.send_voice(
                        chat_id=SUPPORT_GROUP_ID,
                        voice=file_obj.file_id,
                        caption=media_caption,
                        reply_markup=reply_markup
                    )
                else:
                    logger.warning(f"Неизвестный тип медиа: {media_type}")
                    return
                
                logger.info(f"Медиа {media_type} отправлено в группу поддержки: {SUPPORT_GROUP_ID}")
            except Exception as send_error:
                logger.error(f"Ошибка отправки медиа в группу: {send_error}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                raise
                
        except Exception as e:
            logger.error(f"Error sending media to support group: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            # В случае ошибки отправляем текстовое уведомление
            try:
                media_text = f"📎 {media_type.upper()}: {file_name}"
                if caption:
                    media_text = f"{media_text}\n💬 {caption}"
                await self.send_message_notification_to_support_group(chat, media_text)
            except:
                pass

    async def send_message_notification_to_support_group(self, chat, message_text):
        """Отправить уведомление о новом сообщении в группу поддержки"""
        try:
            telegram_username = f"@{chat.user_telegram_username}" if chat.user_telegram_username else "Не указан"
            
            notification_text = (
                f"💬 Новое сообщение от клиента\n\n"
                f"👤 Клиент: {chat.user_name}\n"
                f"📞 Телефон: {chat.user_phone}\n"
                f"📱 Telegram: {telegram_username}\n"
                f"💬 Сообщение: {message_text}\n\n"
                f"ID чата: {chat.sid}"
            )
            
            keyboard = [
                [InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{chat.sid}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await self.send_to_support_group(notification_text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error sending message notification: {e}")

    async def send_to_support_group(self, text: str, reply_markup=None):
        """Отправить сообщение в группу поддержки (с разбивкой на части, если превышает лимит Telegram)"""
        try:
            from app.core.config import SUPPORT_GROUP_ID
            
            if not SUPPORT_GROUP_ID:
                logger.warning("SUPPORT_GROUP_ID не установлен")
                return
            
            MAX_MESSAGE_LENGTH = 4096
            
            payload = {
                "chat_id": SUPPORT_GROUP_ID,
                "text": text
            }
            
            if reply_markup:
                keyboard_json = reply_markup.to_dict()
                payload["reply_markup"] = keyboard_json
            
            if len(text) <= MAX_MESSAGE_LENGTH:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN_2}/sendMessage",
                        json=payload
                    )
                    response.raise_for_status()
                    logger.info(f"Уведомление отправлено в группу поддержки: {SUPPORT_GROUP_ID}")
            else:
                parts = []
                current_part = ""
                lines = text.split('\n')
                
                for line in lines:
                    if len(line) > MAX_MESSAGE_LENGTH:
                        if current_part:
                            parts.append(current_part.strip())
                            current_part = ""
                        for i in range(0, len(line), MAX_MESSAGE_LENGTH):
                            parts.append(line[i:i + MAX_MESSAGE_LENGTH])
                    elif len(current_part) + len(line) + 1 <= MAX_MESSAGE_LENGTH:
                        current_part += line + '\n' if current_part else line + '\n'
                    else:
                        if current_part:
                            parts.append(current_part.strip())
                        current_part = line + '\n'
                
                if current_part:
                    parts.append(current_part.strip())
                
                async with httpx.AsyncClient() as client:
                    for i, part in enumerate(parts):
                        part_text = part
                        if len(parts) > 1:
                            part_text = f"[Часть {i + 1} из {len(parts)}]\n\n{part}"
                        
                        part_payload = {
                            "chat_id": SUPPORT_GROUP_ID,
                            "text": part_text
                        }
                        
                        # Добавляем клавиатуру только к последней части
                        if reply_markup and i == len(parts) - 1:
                            part_payload["reply_markup"] = reply_markup.to_dict()
                        
                        response = await client.post(
                            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN_2}/sendMessage",
                            json=part_payload
                        )
                        response.raise_for_status()
                        
                        if i < len(parts) - 1:
                            await asyncio.sleep(0.1)
                    
                    logger.info(f"Уведомление отправлено в группу поддержки ({len(parts)} частей): {SUPPORT_GROUP_ID}")
                
        except Exception as e:
            logger.error(f"Ошибка отправки в группу поддержки: {e}")

    async def handle_reply_button(self, query, chat_id: str):
        """Обработка нажатия кнопки 'Ответить' в группе"""
        try:
            user_id = query.from_user.id
            
            db_gen = self.db_session_factory()
            db = next(db_gen)
            try:
                support_service = SupportService(db)
                chat = support_service.get_chat_by_sid(chat_id)
                
                if not chat:
                    await query.answer("❌ Чат не найден", show_alert=True)
                    return
                
                support_reply_states[user_id] = {
                    "chat_id": chat_id,
                    "client_telegram_id": chat.user_telegram_id
                }
                
                await query.answer("✅ Теперь отправьте ваш ответ клиенту в эту группу")
                
                from app.core.config import SUPPORT_GROUP_ID
                instruction_text = (
                    f"👤 {query.from_user.first_name} готов ответить клиенту\n"
                    f"📝 Отправьте ваше сообщение в эту группу, и оно будет доставлено клиенту\n"
                    f"❌ Для отмены отправьте /cancel"
                )
                
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN_2}/sendMessage",
                        json={
                            "chat_id": SUPPORT_GROUP_ID,
                            "text": instruction_text,
                            "reply_to_message_id": query.message.message_id
                        }
                    )
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Ошибка в handle_reply_button: {e}")
            await query.answer("❌ Произошла ошибка", show_alert=True)
    
    async def handle_support_reply(self, update: Update, message_text: str):
        """Обработка ответа от поддержки в группе"""
        user_id = update.effective_user.id
        message_sent_to_client = False
        
        try:
            if user_id not in support_reply_states:
                return
            
            reply_state = support_reply_states[user_id]
            chat_id = reply_state["chat_id"]
            client_telegram_id = reply_state["client_telegram_id"]
            
            # Отправляем сообщение клиенту
            full_text = f"📞 Поддержка:\n\n{message_text}"
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN_2}/sendMessage",
                    json={
                        "chat_id": client_telegram_id,
                        "text": full_text
                    }
                )
                response.raise_for_status()
            
            # Сообщение успешно отправлено клиенту
            message_sent_to_client = True
            
            # Сохраняем сообщение в БД
            db_gen = self.db_session_factory()
            db = next(db_gen)
            try:
                support_service = SupportService(db)
                
                message_data = SupportMessageCreate(
                    chat_id=chat_id,
                    sender_type=SupportMessageSenderType.SUPPORT,
                    message_text=message_text
                )
                
                support_service.add_message(message_data)
                
                # Обновляем статус чата на "В работе", если он был "Новое"
                chat = support_service.get_chat_by_sid(chat_id)
                if chat and chat.status == SupportChatStatus.NEW:
                    support_service.update_chat_status_by_sid(chat_id, SupportChatStatus.IN_PROGRESS)
                
            except Exception as db_error:
                logger.error(f"Ошибка при сохранении в БД: {db_error}")
                logger.error(f"Traceback: {traceback.format_exc()}")
            finally:
                db.close()
            
            # Удаляем состояние ожидания ответа
            if user_id in support_reply_states:
                del support_reply_states[user_id]
            
            # Подтверждение в группе
            await update.message.reply_text("✅ Ответ отправлен клиенту!")
            
            logger.info(f"Ответ от поддержки отправлен клиенту {client_telegram_id}")
            
        except Exception as e:
            logger.error(f"Ошибка в handle_support_reply: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            
            # Удаляем состояние, если сообщение было отправлено
            if message_sent_to_client and user_id in support_reply_states:
                del support_reply_states[user_id]
            
            # Отправляем соответствующее сообщение об ошибке
            try:
                if message_sent_to_client:
                    await update.message.reply_text("⚠️ Сообщение отправлено клиенту, но произошла ошибка при сохранении в БД")
                else:
                    await update.message.reply_text("❌ Ошибка при отправке ответа клиенту")
            except:
                pass
    
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
        try:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            # Ждем бесконечно (бот работает в фоне)
            await asyncio.Event().wait()
        except Exception as e:
            logger.error(f"Ошибка запуска бота: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise


# Функция для запуска бота
async def start_support_bot(db_session_factory):
    """Запустить бота поддержки"""
    try:
        bot = SupportBot(db_session_factory)
        await bot.run()
    except Exception as e:
        logger.error(f"Ошибка запуска бота поддержки: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise
