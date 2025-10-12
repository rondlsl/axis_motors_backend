"""
Утилиты для отслеживания активности пользователей
"""
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.user_model import User


def update_user_last_activity(db: Session, user_id: int) -> None:
    """
    Обновляет время последней активности пользователя
    """
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.last_activity_at = datetime.utcnow()
            db.commit()
    except Exception as e:
        print(f"Error updating user last activity: {e}")
