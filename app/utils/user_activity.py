"""
Утилиты для отслеживания активности пользователей
"""
import uuid
from sqlalchemy.orm import Session
from app.models.user_model import User
from app.utils.time_utils import get_local_time


def update_user_last_activity(db: Session, user_id: uuid.UUID) -> None:
    """
    Обновляет время последней активности пользователя
    """
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.last_activity_at = get_local_time()
            db.commit()
    except Exception as e:
        print(f"Error updating user last activity: {e}")
