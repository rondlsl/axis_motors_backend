import asyncio
import uuid
import httpx
from typing import List
from sqlalchemy.orm import Session
from app.models.user_model import User
from app.translations.notifications import get_notification_text


def get_user_push_tokens(db_session: Session, user_id: uuid.UUID) -> List[str]:
    """
    Возвращает активные FCM-токены пользователя из user_devices.
    Если устройств нет, использует legacy-колонку users.fcm_token.
    """
    from app.models.user_device_model import UserDevice
    from app.models.user_model import User

    device_rows = (
        db_session
        .query(UserDevice.fcm_token)
        .filter(
            UserDevice.user_id == user_id,
            UserDevice.is_active.is_(True),
            UserDevice.fcm_token.isnot(None),
            UserDevice.revoked_at.is_(None),
        )
        .all()
    )
    tokens = [row[0] for row in device_rows if row[0]]

    if not tokens:
        user = (
            db_session
            .query(User)
            .filter(User.id == user_id, User.fcm_token.isnot(None))
            .first()
        )
        if user and user.fcm_token:
            tokens = [user.fcm_token]

    # Убираем дубликаты, сохраняя порядок
    seen = set()
    unique_tokens = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            unique_tokens.append(token)
    return unique_tokens


def user_has_push_tokens(db_session: Session, user_id: uuid.UUID) -> bool:
    """Проверяет наличие хотя бы одного активного FCM-токена пользователя."""
    return bool(get_user_push_tokens(db_session, user_id))


async def send_push_notification_async(token: str, title: str, body: str, max_retries: int = 3):
    """
    Send push notification via Expo Push Notification Service
    Works with Expo Push Tokens (ExponentPushToken[...])
    
    Args:
        token: Expo push token
        title: Notification title
        body: Notification body
        max_retries: Maximum number of retry attempts (default: 3)
    """
    # Log token format for debugging
    print(f'📱 Sending push to token: {token[:50]}...' if len(token) > 50 else f'📱 Sending push to token: {token}')
    
    # Expo Push API endpoints (primary and fallback)
    urls = [
        "https://exp.host/--/api/v2/push/send",
        "https://api.expo.dev/v2/push/send"  # Alternative endpoint
    ]
    
    # Prepare message payload
    message = {
        "to": token,
        "title": title,
        "body": body,
        "sound": "default",
        "priority": "high",
        "channelId": "default"
    }
    
    print(f'📤 Sending to Expo: {message}')
    
    # Retry logic with exponential backoff
    for attempt in range(max_retries):
        for url_idx, url in enumerate(urls):
            try:
                # Увеличенный таймаут и настройки для лучшей работы в сети
                timeout = httpx.Timeout(
                    connect=30.0,  # Таймаут подключения
                    read=30.0,     # Таймаут чтения
                    write=30.0,    # Таймаут записи
                    pool=30.0      # Таймаут пула
                )
                
                # Настройки для обхода DNS и сетевых проблем
                limits = httpx.Limits(
                    max_keepalive_connections=5,
                    max_connections=10,
                    keepalive_expiry=30.0
                )
                
                async with httpx.AsyncClient(
                    timeout=timeout, 
                    limits=limits,
                    follow_redirects=True,
                    http2=False  # Отключаем HTTP/2 для совместимости
                ) as client:
                    if attempt > 0 or url_idx > 0:
                        print(f'🔄 Retry attempt {attempt + 1}/{max_retries}, endpoint {url_idx + 1}/{len(urls)}')
                    
                    response = await client.post(url, json=message)
                    
                print(f'📥 Expo response status: {response.status_code}')
                print(f'📥 Expo response body: {response.text}')
                
                # Check response
                if response.status_code == 200:
                    result = response.json()
                    print(f'📊 Expo response JSON: {result}')
                    
                    # Expo returns different formats:
                    # Single: {"data": {"status": "ok", "id": "..."}}
                    # Batch:  {"data": [{"status": "ok", "id": "..."}, ...]}
                    response_data = result.get('data', {})
                    
                    # Handle both list and dict formats
                    if isinstance(response_data, list):
                        data = response_data[0] if response_data else {}
                    else:
                        data = response_data
                    
                    if data.get('status') == 'ok':
                        print(f'✅ Expo push sent successfully: {data.get("id", "no-id")}')
                        return True
                    elif data.get('status') == 'error':
                        error_msg = data.get('message', 'Unknown error')
                        error_details = data.get('details', {})
                        print(f'❌ Expo push error: {error_msg}')
                        print(f'❌ Error details: {error_details}')
                        return False
                    else:
                        print(f'❌ Expo push unexpected response: {data}')
                        return False
                else:
                    print(f'❌ Expo push HTTP error: {response.status_code} - {response.text}')
                    # Try next URL if available
                    if url_idx < len(urls) - 1:
                        continue
                    return False
                    
            except (httpx.TimeoutException, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
                print(f'⏱️ Push timeout error (attempt {attempt + 1}/{max_retries}, endpoint {url_idx + 1}): {e}')
                # Try next URL if available
                if url_idx < len(urls) - 1:
                    continue
                # Exponential backoff before retry
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 1  # 1, 2, 4 seconds
                    print(f'⏳ Waiting {wait_time}s before retry...')
                    await asyncio.sleep(wait_time)
                    break  # Break inner loop to retry with first URL
                    
            except (httpx.ConnectError, httpx.NetworkError) as e:
                print(f'🌐 Push network error (attempt {attempt + 1}/{max_retries}, endpoint {url_idx + 1}): {type(e).__name__}: {e}')
                # Try next URL if available
                if url_idx < len(urls) - 1:
                    continue
                # Exponential backoff before retry
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 1
                    print(f'⏳ Waiting {wait_time}s before retry...')
                    await asyncio.sleep(wait_time)
                    break  # Break inner loop to retry with first URL
                    
            except Exception as e:
                print(f'❌ Push unexpected error (attempt {attempt + 1}/{max_retries}): {type(e).__name__}: {e}')
                import traceback
                traceback.print_exc()
                # Try next URL if available
                if url_idx < len(urls) - 1:
                    continue
                return False
    
    print(f'❌ Failed to send push after {max_retries} retries')
    return False


async def send_notification_to_all_mechanics_async(
        db_session: Session,
        title: str,
        body: str,
        status: str = None
) -> dict:
    """
    Sends notification to every active mechanic by user_id.
    """
    from app.models.user_model import User, UserRole

    mechanics = (
        db_session.query(User)
        .filter(
            User.role == UserRole.MECHANIC,
            User.is_active.is_(True)
        )
        .all()
    )
    if not mechanics:
        return {"success": 0, "failed": 0, "failed_ids": []}

    # Сохраняем ID механиков перед закрытием сессии
    mechanic_ids = [mech.id for mech in mechanics]
    
    tasks = [
        send_push_to_user_by_id_async(mech_id, title, body, status)
        for mech_id in mechanic_ids
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    success = sum(1 for r in results if r is True)
    failed_ids = [
        mech_id
        for mech_id, r in zip(mechanic_ids, results)
        if r is not True
    ]

    return {"success": success, "failed": len(failed_ids), "failed_ids": failed_ids}


async def broadcast_push_notification_async(db_session, title: str, body: str):
    """
    Sends a push notification to every unique FCM token in the users table.

    Args:
        db_session: SQLAlchemy database session
        title: Notification title
        body: Notification body message

    Returns:
        dict: {
            "success": <int count of successes>,
            "failed": <int count of failures>,
            "failed_tokens": <list of tokens that failed>,
        }
    """
    from app.models.user_model import User

    try:
        from app.models.user_device_model import UserDevice

        # Fetch all distinct, non-null tokens from devices
        device_rows = (
            db_session
            .query(UserDevice.fcm_token)
            .filter(
                UserDevice.fcm_token.isnot(None),
                UserDevice.is_active.is_(True),
                UserDevice.revoked_at.is_(None),
            )
            .distinct()
            .all()
        )
        tokens = [row[0] for row in device_rows if row[0]]

        # Fallback: legacy tokens from users table
        if not tokens:
            token_rows = (
                db_session
                .query(User.fcm_token)
                .filter(User.fcm_token.isnot(None))
                .distinct()
                .all()
            )
            tokens = [row[0] for row in token_rows]

        if not tokens:
            print("No FCM tokens found for broadcast")
            return {"success": 0, "failed": 0, "failed_tokens": []}

        # Отправляем батчами, чтобы не перегрузить сервер
        MAX_CONCURRENT = 50
        BATCH_SIZE = 100
        BATCH_DELAY = 1.0
        
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        results = []
        
        async def send_with_semaphore(token):
            async with semaphore:
                return await send_push_notification_async(token=token, title=title, body=body)
        
        # Разбиваем на батчи
        for i in range(0, len(tokens), BATCH_SIZE):
            batch = tokens[i:i + BATCH_SIZE]
            batch_tasks = [send_with_semaphore(token) for token in batch]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            results.extend(batch_results)
            
            # Задержка между батчами
            if i + BATCH_SIZE < len(tokens):
                await asyncio.sleep(BATCH_DELAY)

        # Tally results
        success_count = sum(1 for r in results if r is True)
        failed_tokens = [
            token for token, result in zip(tokens, results)
            if result is not True
        ]
        failed_count = len(failed_tokens)

        print("Broadcast: {success_count} succeeded, {failed_count} failed")

        return {
            "success": success_count,
            "failed": failed_count,
            "failed_tokens": failed_tokens
        }

    except Exception as e:
        print("Error during broadcast: {e}")
        return {"success": 0, "failed": 0, "error": str(e)}


async def send_push_to_user_by_id(
    db_session: Session,
    user_id: uuid.UUID,
    title: str,
    body: str,
    status: str = None
) -> bool:
    from app.models.notification_model import Notification
    from app.push.enums import NotificationStatus

    notif = Notification(user_id=user_id, title=title, body=body)
    if status:
        try:
            notif.status = NotificationStatus(status)
        except ValueError:
            pass
    db_session.add(notif)
    db_session.commit()

    devices_tokens = get_user_push_tokens(db_session, user_id)
    if not devices_tokens:
        return False
    
    tasks = [
        send_push_notification_async(token=token, title=title, body=body)
        for token in devices_tokens
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    return any(r is True for r in results)


async def send_localized_notification_to_user(
        db_session: Session,
        user_id: uuid.UUID,
        translation_key: str,
        status: str = None,
        **kwargs
) -> bool:
    """
    Отправить локализованное уведомление пользователю
    
    Args:
        db_session: Сессия базы данных
        user_id: ID пользователя
        translation_key: Ключ перевода (например, 'financier_approve')
        status: Статус уведомления
        **kwargs: Параметры для форматирования перевода
        
    Returns:
        bool: Успешность отправки
    """
    
    db_session.expire_all()
    
    user = db_session.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    
    db_session.refresh(user)
    
    title, body = get_notification_text(user.locale or "ru", translation_key, **kwargs)
    
    return await send_push_to_user_by_id(db_session, user_id, title, body, status)


async def send_localized_notification_to_user_async(
        user_id: uuid.UUID,
        translation_key: str,
        status: str = None,
        **kwargs
) -> bool:
    """
    Отправить локализованное уведомление пользователю (создает свою сессию БД)
    Используется для asyncio.create_task, когда сессия может быть закрыта
    
    Args:
        user_id: ID пользователя
        translation_key: Ключ перевода (например, 'financier_approve')
        status: Статус уведомления
        **kwargs: Параметры для форматирования перевода
        
    Returns:
        bool: Успешность отправки
    """
    from app.dependencies.database.database import SessionLocal
    
    db = SessionLocal()
    try:
        return await send_localized_notification_to_user(db, user_id, translation_key, status, **kwargs)
    finally:
        db.close()


async def send_push_to_user_by_id_async(
        user_id: uuid.UUID,
        title: str,
        body: str,
        status: str = None
) -> bool:
    """
    Отправить push-уведомление пользователю (создает свою сессию БД)
    Используется для asyncio.create_task, когда сессия может быть закрыта
    
    Args:
        user_id: ID пользователя
        title: Заголовок уведомления
        body: Текст уведомления
        status: Статус уведомления
        
    Returns:
        bool: Успешность отправки
    """
    from app.dependencies.database.database import SessionLocal
    
    db = SessionLocal()
    try:
        return await send_push_to_user_by_id(db, user_id, title, body, status)
    finally:
        db.close()


async def send_localized_notification_to_all_mechanics(
        db_session: Session,
        translation_key: str,
        status: str = None,
        **kwargs
) -> dict:
    """
    Отправить локализованное уведомление всем механикам
    
    Args:
        db_session: Сессия базы данных
        translation_key: Ключ перевода
        status: Статус уведомления
        **kwargs: Параметры для форматирования перевода
        
    Returns:
        dict: Результат отправки
    """
    from app.models.user_model import User, UserRole
    
    # Получаем всех активных механиков
    mechanics = (
        db_session.query(User)
        .filter(
            User.role == UserRole.MECHANIC,
            User.is_active.is_(True)
        )
        .all()
    )
    
    if not mechanics:
        return {"success": 0, "failed": 0, "failed_ids": []}
    
    mechanic_ids = [mech.id for mech in mechanics]
    
    # Отправляем локализованные уведомления каждому механику (используем async версии)
    tasks = []
    for mech_id in mechanic_ids:
        task = send_localized_notification_to_user_async(
            mech_id, 
            translation_key, 
            status, 
            **kwargs
        )
        tasks.append(task)
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    success = sum(1 for r in results if r is True)
    failed_ids = [
        mech_id for mech_id, r in zip(mechanic_ids, results)
        if r is not True
    ]
    
    return {"success": success, "failed": len(failed_ids), "failed_ids": failed_ids}
