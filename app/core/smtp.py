"""
Отправка email через SMTP с перебором аккаунтов при ошибке (лимиты и т.д.).
Таймаут и перехват всех исключений — чтобы недоступность SMTP не роняла сервер.
"""
import smtplib

from app.core.config import SMTP_HOST, SMTP_PORT, SMTP_ACCOUNTS, SMTP_FROM
from app.core.logging_config import get_logger

logger = get_logger(__name__)

# Таймаут в секундах: без него при "Network is unreachable" соединение может висеть минуты и блокировать воркеры
SMTP_TIMEOUT = 10


def send_email_with_fallback(msg, to_address, from_override: str | None = None) -> bool:
    """
    Отправить письмо (MIMEText/MIMEMultipart). Пробует по очереди SMTP_ACCOUNTS;
    при ошибке (лимит, отказ, сеть недоступна) переходит к следующему аккаунту.
    Исключения не пробрасываются — возвращается False, сервер не падает.

    :param msg: готовое сообщение (Subject, From, To уже заданы у msg)
    :param to_address: email получателя или список адресов
    :param from_override: если задан, используется как From для всех попыток
    :return: True если отправка прошла хотя бы одним аккаунтом, иначе False
    """
    try:
        if not SMTP_HOST or not SMTP_ACCOUNTS:
            logger.warning("SMTP not configured: no SMTP_HOST or no SMTP accounts")
            return False

        to_list = [to_address] if isinstance(to_address, str) else list(to_address)
        to_display = to_list[0] if len(to_list) == 1 else ",".join(to_list[:3])
        logger.info("SMTP: отправка email на to=%s", to_display)

        last_error = None
        for smtp_user, smtp_pass in SMTP_ACCOUNTS:
            from_addr = from_override or SMTP_FROM or smtp_user
            try:
                msg["From"] = from_addr
                if msg.get("To") is None and len(to_list) == 1:
                    msg["To"] = to_list[0]
                # timeout — чтобы при "Network is unreachable" не висеть минутами и не ронять воркеры
                with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.sendmail(from_addr, to_list, msg.as_string())
                logger.info("SMTP: email отправлен на to=%s через %s", to_display, smtp_user)
                return True
            except Exception as e:
                last_error = e
                logger.warning("SMTP send failed for %s (to=%s): %s", smtp_user, to_display, e)

        if last_error:
            logger.error("SMTP: все аккаунты недоступны; last error (to=%s): %s", to_display, last_error)
        return False
    except Exception as e:
        try:
            to_fallback = to_address if isinstance(to_address, str) else (list(to_address)[0] if to_address else "?")
        except Exception:
            to_fallback = "?"
        logger.error("SMTP: неожиданная ошибка при отправке (to=%s): %s", to_fallback, e, exc_info=True)
        return False
