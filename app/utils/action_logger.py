from sqlalchemy.orm import Session
from app.models.action_log_model import ActionLog
import json

def log_action(
    db: Session,
    actor_id,
    action: str,
    entity_type: str = None,
    entity_id = None,
    details: dict = None
):
    """
    Creates an ActionLog entry.
    Does NOT commit the session.
    """
    log_entry = ActionLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details
    )
    db.add(log_entry)
    return log_entry
