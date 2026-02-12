"""
Предагрегация регистраций пользователей по дням.
Используется для аналитики без full scan таблицы users.
"""
from sqlalchemy import Column, Date, Integer

from app.dependencies.database.database import Base


class DailyUserStats(Base):
    """
    Счётчик зарегистрированных пользователей по дням (по created_at в локальной дате).
    Обновляется атомарно при каждой регистрации через INSERT ... ON CONFLICT DO UPDATE.
    """
    __tablename__ = "daily_user_stats"

    date = Column(Date, primary_key=True, nullable=False)
    registered_count = Column(Integer, nullable=False, server_default="0")
