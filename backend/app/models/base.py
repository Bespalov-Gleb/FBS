"""
Базовая модель для всех моделей БД
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer
from sqlalchemy.ext.declarative import declared_attr

from app.core.database import Base


class BaseModel(Base):
    """Абстрактная базовая модель с общими полями"""
    
    __abstract__ = True
    
    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    
    @declared_attr
    def __tablename__(cls) -> str:
        """Автоматическая генерация имени таблицы из имени класса"""
        return cls.__name__.lower() + "s"
    
    def __repr__(self) -> str:
        """Строковое представление модели"""
        return f"<{self.__class__.__name__}(id={self.id})>"
