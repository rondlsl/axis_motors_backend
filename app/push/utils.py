import asyncio
import uuid
import httpx
from app.models.user_model import User
from app.translations.notifications import get_notification_text
from sqlalchemy.orm import Session


async def send_push_notification_async(token: str, title: str, body: str):
    """
    Send push notification via Expo Push Notification Service
    Works with Expo Push Tokens (ExponentPushToken[...])
    """
    try:
        # Expo Push API endpoint
        url = "https://exp.host/--/api/v2/push/send"
        
        # Prepare message payload
        message = {
            "to": token,
            "title": title,
            "body": body,
            "sound": "default",
            "priority": "high",
            "channelId": "default"
        }
        
        # Send push notification
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=message)
            
        # Check response
        if response.status_code == 200:
            result = response.json()
            data = result.get('data', [{}])[0] if isinstance(result.get('data'), list) else result
            
            if data.get('status') == 'ok':
                print(f'✅ Expo push sent successfully: {data.get("id", "no-id")}')
                return True
            else:
                error_msg = data.get('message', 'Unknown error')
                print(f'❌ Expo push failed: {error_msg}')
                return False
        else:
            print(f'❌ Expo push HTTP error: {response.status_code} - {response.text}')
            return False
            
    except httpx.TimeoutException:
        print('❌ Push error: Timeout while connecting to Expo Push Service')
        return False
    except Exception as e:
        print(f'❌ Push error: {e}')
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
            User.is_active == True,
            User.fcm_token.isnot(None)
        )
        .all()
    )
    if not mechanics:
        return {"success": 0, "failed": 0, "failed_ids": []}

    tasks = [
        send_push_to_user_by_id(db_session, mech.id, title, body, status)
        for mech in mechanics
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    success = sum(1 for r in results if r is True)
    failed_ids = [
        mech.id
        for mech, r in zip(mechanics, results)
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
        # Fetch all distinct, non-null tokens
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

        # Fire off one task per unique token
        tasks = [
            send_push_notification_async(token=token, title=title, body=body)
            for token in tokens
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

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
    # 1) Сохраняем уведомление в БД
    from app.models.notification_model import Notification
    from app.push.enums import NotificationStatus
    
    notif = Notification(user_id=user_id, title=title, body=body)
    if status:
        try:
            notif.status = NotificationStatus(status)
        except ValueError:
            # Если статус не найден в enum, оставляем None
            pass
    db_session.add(notif)
    db_session.commit()

    # 2) Достаём токен и шлём пуш
    from app.models.user_model import User
    user = (
        db_session
        .query(User)
        .filter(User.id == user_id, User.fcm_token.isnot(None))
        .first()
    )
    if not user:
        return False

    return await send_push_notification_async(
        token=user.fcm_token,
        title=title,
        body=body
    )


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
    
    user = db_session.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    
    title, body = get_notification_text(user.locale or "ru", translation_key, **kwargs)
    
    return await send_push_to_user_by_id(db_session, user_id, title, body, status)


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
            User.is_active == True,
            User.fcm_token.isnot(None)
        )
        .all()
    )
    
    if not mechanics:
        return {"success": 0, "failed": 0, "failed_ids": []}
    
    # Отправляем локализованные уведомления каждому механику
    tasks = []
    for mech in mechanics:
        task = send_localized_notification_to_user(
            db_session, 
            mech.id, 
            translation_key, 
            status, 
            **kwargs
        )
        tasks.append(task)
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    success = sum(1 for r in results if r is True)
    failed_ids = [
        mech.id for mech, r in zip(mechanics, results)
        if r is not True
    ]
    
    return {"success": success, "failed": len(failed_ids), "failed_ids": failed_ids}