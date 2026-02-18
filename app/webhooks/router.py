"""
Resend email webhooks: bounce & complaint.
POST /webhooks/email
В Resend: Settings → Webhooks → https://api.azvmotors.kz/webhooks/email
События: email.sent, email.delivered, email.bounced, email.complained
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request, Response, status, Depends

from app.dependencies.database.database import get_db
from app.services.email_reputation import process_webhook
from app.core.config import RESEND_WEBHOOK_SECRET
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_resend_webhook(body: bytes, headers: dict) -> Optional[dict]:
    """
    Проверка подписи Resend (Svix). Заголовки: svix-id, svix-timestamp, svix-signature.
    """
    secret = RESEND_WEBHOOK_SECRET
    if not secret or not secret.strip():
        logger.warning("RESEND_WEBHOOK_SECRET не задан; подпись не проверяется")
        try:
            import json
            return json.loads(body.decode("utf-8"))
        except Exception as e:
            logger.error("Webhook body JSON: %s", e)
            return None
    try:
        from svix.webhooks import Webhook, WebhookVerificationError
        wh = Webhook(secret.strip())
        payload_str = body.decode("utf-8") if isinstance(body, bytes) else body
        msg = wh.verify(payload_str, headers)
        return msg if isinstance(msg, dict) else None
    except WebhookVerificationError as e:
        logger.warning("Resend webhook verification failed: %s", e)
        return None
    except Exception as e:
        logger.exception("Resend webhook verify: %s", e)
        return None


@router.post("/email", status_code=status.HTTP_200_OK)
async def resend_email_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Resend присылает сюда события. Обрабатываем email.bounced и email.complained —
    обновляем User.email_status / bounce_count.
    """
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    payload = _verify_resend_webhook(body, headers)
    if not payload:
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content=b"Invalid or unverified payload")

    event_type = (payload.get("type") or "").strip()
    if event_type in ("email.bounced", "email.complained"):
        try:
            process_webhook(db, payload)
        except Exception as e:
            logger.exception("process_webhook failed: %s", e)

    return {"received": True, "type": event_type}
