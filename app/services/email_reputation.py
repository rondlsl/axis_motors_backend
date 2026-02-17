"""
Email reputation & deliverability: validation, suppression, webhook processing.
Integrates with Resend webhooks (bounce/complaint) and User.email_status.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models.user_model import User
from app.utils.time_utils import get_local_time

logger = logging.getLogger(__name__)

# Status values for User.email_status (must match DB server_default where used)
EMAIL_STATUS_PENDING = "pending"
EMAIL_STATUS_VERIFIED = "verified"
EMAIL_STATUS_BOUNCED = "bounced"
EMAIL_STATUS_COMPLAINT = "complaint"
EMAIL_STATUS_SUPPRESSED = "suppressed"

# Do not send to these statuses
BLOCKED_EMAIL_STATUSES = {EMAIL_STATUS_BOUNCED, EMAIL_STATUS_COMPLAINT, EMAIL_STATUS_SUPPRESSED}

# Soft bounce: retry up to this count before marking bounced
SOFT_BOUNCE_MAX_COUNT = 3

# Basic email syntax (RFC 5322 simplified)
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)

# Disposable / temporary domains (short list; extend as needed)
DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "tempmail.com", "10minutemail.com", "guerrillamail.com",
    "throwaway.email", "yopmail.com", "maildrop.cc", "temp-mail.org",
    "fakeinbox.com", "trashmail.com", "getnada.com", "mailnesia.com",
})


def validate_email_syntax(email: str) -> bool:
    """Check basic email syntax. Returns True if valid."""
    if not email or not isinstance(email, str):
        return False
    e = email.strip().lower()
    return bool(EMAIL_REGEX.match(e))


def is_disposable_domain(email: str) -> bool:
    """True if domain is in disposable blocklist."""
    email = (email or "").strip().lower()
    if "@" not in email:
        return False
    domain = email.split("@")[-1]
    return domain in DISPOSABLE_DOMAINS


def validate_email(email: str) -> tuple[bool, str]:
    """
    Validate email for sending: syntax + disposable check.
    Returns (ok: bool, error_message: str). error_message empty if ok.
    """
    if not email or not isinstance(email, str):
        return False, "Email is empty"
    e = email.strip().lower()
    if not EMAIL_REGEX.match(e):
        return False, "Invalid email format"
    if is_disposable_domain(e):
        return False, "Disposable email not allowed"
    return True, ""


def should_send_to_user(user: Optional[User]) -> bool:
    """
    Whether we are allowed to send email to this user (reputation/suppression).
    Returns False if user is None, has no email, or status is blocked.
    """
    if not user or not (user.email and user.email.strip()):
        return False
    status = (user.email_status or EMAIL_STATUS_PENDING).strip().lower()
    return status not in BLOCKED_EMAIL_STATUSES


def should_send_to_email(db: Session, email: str) -> bool:
    """
    Whether we are allowed to send to this address (checks user by email if exists).
    If no user has this email (например, новая почта при смене) — разрешаем отправку.
    """
    email = (email or "").strip().lower()
    if not email:
        return False
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        return True  # адрес свободен — можно отправлять (смена почты, регистрация)
    return should_send_to_user(user)


def mark_bounced(db: Session, email: str, *, hard_bounce: bool) -> None:
    """
    Update user(s) with this email: increment bounce_count, set last_bounce_at.
    If hard_bounce or bounce_count > SOFT_BOUNCE_MAX_COUNT, set email_status = bounced.
    """
    email = (email or "").strip().lower()
    if not email:
        return
    users = db.query(User).filter(User.email == email).all()
    for user in users:
        user.bounce_count = (user.bounce_count or 0) + 1
        user.last_bounce_at = get_local_time()
        if hard_bounce or (user.bounce_count or 0) > SOFT_BOUNCE_MAX_COUNT:
            user.email_status = EMAIL_STATUS_BOUNCED
            logger.info("User %s email_status set to bounced (hard=%s, count=%s)", user.id, hard_bounce, user.bounce_count)
    db.commit()


def mark_complaint(db: Session, email: str) -> None:
    """Set email_status = complaint for all users with this email. Never send again."""
    email = (email or "").strip().lower()
    if not email:
        return
    users = db.query(User).filter(User.email == email).all()
    for user in users:
        user.email_status = EMAIL_STATUS_COMPLAINT
        logger.info("User %s email_status set to complaint (spam report)", user.id)
    db.commit()


def process_webhook(db: Session, payload: dict) -> None:
    """
    Process Resend webhook payload. Handles email.bounced, email.complained.
    Payload: { "type": "email.bounced"|"email.complained", "data": { "to": [...], "bounce": { "type": "Permanent"|"Temporary" } } }
    """
    event_type = (payload.get("type") or "").strip()
    data = payload.get("data") or {}
    to_list = data.get("to")
    if not to_list or not isinstance(to_list, list):
        return

    if event_type == "email.bounced":
        bounce = data.get("bounce") or {}
        bounce_type = (bounce.get("type") or "").strip()
        hard_bounce = bounce_type.lower() == "permanent"
        for addr in to_list:
            if isinstance(addr, str):
                mark_bounced(db, addr, hard_bounce=hard_bounce)
    elif event_type == "email.complained":
        for addr in to_list:
            if isinstance(addr, str):
                mark_complaint(db, addr)
