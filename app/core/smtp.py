"""
Отправка email через SMTP с перебором аккаунтов при ошибке (лимиты и т.д.).
"""
import logging
import smtplib

from app.core.config import SMTP_HOST, SMTP_PORT, SMTP_ACCOUNTS, SMTP_FROM

logger = logging.getLogger(__name__)


def send_email_with_fallback(msg, to_address, from_override: str | None = None) -> bool:
    """
    Отправить письмо (MIMEText/MIMEMultipart). Пробует по очереди SMTP_ACCOUNTS;
    при ошибке (лимит, отказ и т.д.) переходит к следующему аккаунту.

    :param msg: готовое сообщение (Subject, From, To уже заданы у msg)
    :param to_address: email получателя или список адресов
    :param from_override: если задан, используется как From для всех попыток
    :return: True если отправка прошла хотя бы одним аккаунтом, иначе False
    """
    if not SMTP_HOST or not SMTP_ACCOUNTS:
        logger.warning("SMTP not configured: no SMTP_HOST or no SMTP accounts")
        return False

    to_list = [to_address] if isinstance(to_address, str) else list(to_address)
    last_error = None

    for smtp_user, smtp_pass in SMTP_ACCOUNTS:
        from_addr = from_override or SMTP_FROM or smtp_user
        try:
            msg["From"] = from_addr
            if msg.get("To") is None and len(to_list) == 1:
                msg["To"] = to_list[0]
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(from_addr, to_list, msg.as_string())
            logger.debug("Email sent via SMTP account %s", smtp_user)
            return True
        except Exception as e:
            last_error = e
            logger.warning("SMTP send failed for %s: %s", smtp_user, e)

    if last_error:
        logger.error("All SMTP accounts failed; last error: %s", last_error)
    return False
