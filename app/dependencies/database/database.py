from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.core.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    pool_size=50,  # одновременно до 50 «живых» соединений 
    max_overflow=50,  # ещё до 50 «переполнений» за пределы pool_size 
    pool_timeout=10,  # ждать соединение не более 10 секунд 
    pool_pre_ping=True,  # проверять «живость» соединения перед выдачей
    pool_recycle=1800,  # перезапускать соединение через 30 минут
    connect_args={
        "options": "-c statement_timeout=180000 -c lock_timeout=60000 -c idle_in_transaction_session_timeout=180000"
    }
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
