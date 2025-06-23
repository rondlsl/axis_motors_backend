from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.core.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    pool_size=20,  # одновременно до 20 «живых» соединений
    max_overflow=30,  # ещё до 30 «переполнений» за пределы pool_size
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
