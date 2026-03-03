"""
Подключение к базе данных и сессии
"""
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings

# Параметры для SQLite (тесты) vs PostgreSQL
_engine_kwargs: dict = {
    "pool_pre_ping": not settings.database_url_sync.startswith("sqlite"),
    "echo": settings.DEBUG,
}
if settings.database_url_sync.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
    _engine_kwargs["poolclass"] = StaticPool  # один connection — одна БД для всех сессий
else:
    _engine_kwargs["pool_size"] = 20
    _engine_kwargs["max_overflow"] = 10
    _engine_kwargs["pool_recycle"] = 3600

engine = create_engine(settings.database_url_sync, **_engine_kwargs)

# Session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# Базовый класс для моделей
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    Dependency для получения сессии БД
    
    Yields:
        Session: SQLAlchemy сессия
        
    Example:
        ```python
        @router.get("/users")
        def get_users(db: Session = Depends(get_db)):
            return db.query(User).all()
        ```
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    Инициализация базы данных
    Создание всех таблиц
    """
    # Импорт всех моделей для создания таблиц
    from app.models import user, marketplace, order, warehouse, print_settings, audit_log  # noqa: F401
    
    Base.metadata.create_all(bind=engine)
