"""
Подключение к базе данных и сессии
"""
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# Создание engine с connection pooling
engine = create_engine(
    settings.database_url_sync,
    pool_pre_ping=True,  # Проверка соединения перед использованием
    pool_size=20,  # Размер пула соединений
    max_overflow=10,  # Дополнительные соединения сверх pool_size
    pool_recycle=3600,  # Переиспользование соединений (1 час)
    echo=settings.DEBUG,  # Логирование SQL запросов в dev режиме
)

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
