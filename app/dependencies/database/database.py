from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.core.config import DATABASE_URL
from app.core.logging_config import get_logger
logger = get_logger(__name__)

# pool_recycle меньше типичного idle timeout на стороне PostgreSQL/прокси,
# чтобы не использовать соединения, уже закрытые сервером («server closed the connection unexpectedly»).
engine = create_engine(
    DATABASE_URL,
    pool_size=50,
    max_overflow=50,
    pool_timeout=10,
    pool_pre_ping=True,
    pool_recycle=600,  # перезапускать соединение через 10 мин (раньше 30 — меньше шанс stale connection)
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
        try:
            db.close()
        except Exception as e:
            logger.error("Ошибка закрытия сессии БД: %s", e)
