from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.core.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    pool_size=30,  # одновременно до 30 «живых» соединений
    max_overflow=40,  # ещё до 40 «переполнений» за пределы pool_size (итого до 70 соединений)
    pool_timeout=30,  # ждать соединение не более 30 секунд
    pool_pre_ping=True,  # проверять «живость» соединения перед выдачей
    pool_recycle=1800,  # перезапускать соединение через 30 минут
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
