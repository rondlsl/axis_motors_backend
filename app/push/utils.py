import firebase_admin
from firebase_admin import messaging, credentials
import asyncio

cred = credentials.Certificate("app/push/firebase-service-account.json")
firebase_admin.initialize_app(cred)


async def send_push_notification_async(token: str, title: str, body: str):
    """
    Asynchronous version of send_push_notification
    Runs the Firebase messaging operations in a thread pool
    """
    try:
        # Android: sound and vibration (via channel)
        android_config = messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                title=title,
                body=body,
                sound="default",  # Sound playback
                channel_id="high_importance_channel",  # Channel should be configured for vibration
            )
        )
        # iOS: sound
        apns_config = messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    alert=messaging.ApsAlert(
                        title=title,
                        body=body
                    ),
                    sound="default"  # Sound playback on iOS
                )
            )
        )
        message = messaging.Message(
            android=android_config,
            apns=apns_config,
            token=token
        )

        # Run Firebase messaging in a thread pool since it's blocking
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: messaging.send(message)
        )

        print('Successfully sent message:', response)
        return True
    except Exception as e:
        print('Push error:', e)
        return False


async def send_notification_to_all_mechanics_async(db_session, title: str, body: str):
    """
    Sends push notifications to all users with the 'mechanic' role.

    Args:
        db_session: SQLAlchemy database session
        title: Notification title
        body: Notification body message

    Returns:
        dict: Contains success count and list of failed tokens
    """
    from app.models.user_model import User, UserRole

    try:
        # Query all active mechanics with FCM tokens
        mechanics = db_session.query(User).filter(
            User.role == UserRole.MECHANIC,
            User.is_active == True,
            User.fcm_token.isnot(None)
        ).all()

        if not mechanics:
            print("No active mechanics with FCM tokens found")
            return {"success": 0, "failed": 0, "failed_tokens": []}

        # Send notifications in parallel
        tasks = []
        for mechanic in mechanics:
            if mechanic.fcm_token:
                tasks.append(send_push_notification_async(
                    token=mechanic.fcm_token,
                    title=title,
                    body=body
                ))

        # Wait for all notification tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Count successful and failed notifications
        success_count = sum(1 for r in results if r is True)
        failed_count = len(results) - success_count

        # Collect failed tokens for debugging
        failed_tokens = [
            mechanic.fcm_token
            for mechanic, result in zip(mechanics, results)
            if result is not True
        ]

        print(f"Sent {success_count} notifications to mechanics, {failed_count} failed")

        return {
            "success": success_count,
            "failed": failed_count,
            "failed_tokens": failed_tokens
        }

    except Exception as e:
        print(f"Error sending notifications to mechanics: {e}")
        return {"success": 0, "failed": 0, "error": str(e)}


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

        print(f"Broadcast: {success_count} succeeded, {failed_count} failed")

        return {
            "success": success_count,
            "failed": failed_count,
            "failed_tokens": failed_tokens
        }

    except Exception as e:
        print(f"Error during broadcast: {e}")
        return {"success": 0, "failed": 0, "error": str(e)}


