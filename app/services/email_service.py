"""
Централизованный сервис отправки email через Resend API.
Вся логика отправки изолирована здесь; роутеры только вызывают методы сервиса.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple, TYPE_CHECKING

from app.core.config import RESEND_API_KEY, EMAIL_FROM

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from app.services.email_reputation import validate_email as validate_email_reputation, should_send_to_email

logger = logging.getLogger(__name__)


def _registration_code_html(code: str, title: str, intro_text: str, footer_text: str) -> str:
    """Минималистичный HTML для кода верификации. Inline-стили, без внешнего CSS."""
    import html as html_module
    code_safe = html_module.escape(code)
    title_safe = html_module.escape(title)
    intro_safe = html_module.escape(intro_text)
    footer_safe = html_module.escape(footer_text)
    return f"""
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title_safe}</title>
</head>
<body style="margin:0; padding:0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f5f5f5;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #f5f5f5;">
    <tr>
      <td align="center" style="padding: 40px 20px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width: 420px; background-color: #ffffff; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
          <tr>
            <td style="padding: 40px 32px;">
              <h1 style="margin: 0 0 8px 0; font-size: 22px; font-weight: 600; color: #1a1a1a; text-align: center;">{title_safe}</h1>
              <p style="margin: 0 0 24px 0; font-size: 15px; line-height: 1.5; color: #555555; text-align: center;">{intro_safe}</p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="center" style="padding: 16px 0;">
                    <span style="display: inline-block; font-size: 28px; font-weight: 700; letter-spacing: 8px; color: #1a1a1a; background-color: #e8e8e8; padding: 16px 24px; border-radius: 10px;">{code_safe}</span>
                  </td>
                </tr>
              </table>
              <p style="margin: 24px 0 0 0; font-size: 13px; line-height: 1.5; color: #888888; text-align: center;">{footer_safe}</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


class EmailServiceError(Exception):
    """Ошибка отправки email через Resend."""
    pass


class EmailService:
    """
    Сервис отправки email через Resend.
    Инициализируется из RESEND_API_KEY в ENV.
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or RESEND_API_KEY
        self._from = EMAIL_FROM

    def is_configured(self) -> bool:
        return bool(self._api_key and self._api_key.strip())

    async def send_email(
        self,
        to: str,
        subject: str,
        html: str,
        *,
        text: Optional[str] = None,
        db: Optional["Session"] = None,
        skip_reputation_check: bool = False,
    ) -> Tuple[bool, Optional[str]]:
        """
        Отправить письмо на один адрес.
        :param to: email получателя
        :param subject: тема
        :param html: HTML-тело письма
        :param text: опционально plain-text версия
        :param db: если передан, перед отправкой проверяются validation и suppression (reputation)
        :param skip_reputation_check: не проверять reputation (для системных писем, если нужно)
        :return: (успех, message_id от Resend или None)
        """
        if not self.is_configured():
            logger.warning("Email not sent: RESEND_API_KEY not configured")
            return False, None

        to_normalized = to.strip().lower()
        if db and not skip_reputation_check:
            ok, err = validate_email_reputation(to_normalized)
            if not ok:
                logger.warning("Email not sent (validation): to=%s reason=%s", to, err)
                raise EmailServiceError(err)
            if not should_send_to_email(db, to_normalized):
                logger.warning("Email not sent (suppression/bounce): to=%s", to)
                raise EmailServiceError("Email disabled due to reputation issues (bounce/complaint/suppressed)")

        try:
            import resend
            resend.api_key = self._api_key

            payload = {
                "from": self._from,
                "to": [to_normalized],
                "subject": subject,
                "html": html,
            }
            if text:
                payload["text"] = text

            result = resend.Emails.send(payload)
            message_id = None
            if result is not None:
                if isinstance(result, dict) and result.get("id"):
                    message_id = str(result["id"])
                elif hasattr(result, "get") and result.get("id"):
                    message_id = str(result.get("id"))
                elif hasattr(result, "id"):
                    message_id = str(result.id)
            logger.info("Email sent to %s, subject=%s, message_id=%s", to, subject, message_id)
            return True, message_id
        except Exception as e:
            logger.error("Resend send_email failed to=%s subject=%s: %s", to, subject, e, exc_info=True)
            return False, None

    async def send_registration_code(
        self, to: str, code: str, *, db: Optional["Session"] = None
    ) -> bool:
        """
        Отправить код подтверждения регистрации / верификации email.
        Если передан db, применяется проверка reputation перед отправкой.
        """
        html = _registration_code_html(
            code=code,
            title="Подтверждение регистрации",
            intro_text="Используйте код ниже для завершения регистрации.",
            footer_text="Если вы не регистрировались — проигнорируйте это письмо.",
        )
        success, _ = await self.send_email(
            to=to,
            subject="Подтверждение регистрации — AZV Motors",
            html=html,
            text=f"Ваш код подтверждения: {code}",
            db=db,
        )
        return success

    async def send_email_change_code(
        self, to: str, code: str, *, db: Optional["Session"] = None
    ) -> bool:
        """Отправить код для подтверждения смены email."""
        html = _registration_code_html(
            code=code,
            title="Изменение email",
            intro_text="Используйте код ниже для подтверждения нового email.",
            footer_text="Если вы не запрашивали смену email — проигнорируйте письмо.",
        )
        success, _ = await self.send_email(
            to=to,
            subject="Изменение email — AZV Motors",
            html=html,
            text=f"Ваш код для подтверждения изменения email: {code}",
            db=db,
        )
        return success

    async def send_plain_email(
        self,
        to: str,
        subject: str,
        body: str,
        *,
        db: Optional["Session"] = None,
        skip_reputation_check: bool = False,
    ) -> bool:
        """
        Отправить простое текстовое письмо (для админки/саппорта).
        Если передан db, перед отправкой проверяются validation и suppression.
        """
        import html as html_module
        escaped = html_module.escape(body).replace("\n", "<br>\n")
        html = f"<div style='font-family: sans-serif; font-size: 14px; line-height: 1.5;'>{escaped}</div>"
        success, _ = await self.send_email(
            to=to,
            subject=subject,
            html=html,
            text=body,
            db=db,
            skip_reputation_check=skip_reputation_check,
        )
        return success


# Синглтон для использования в роутерах
_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
