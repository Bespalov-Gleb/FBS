"""
Модель подключения к маркетплейсу
"""
import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class MarketplaceType(str, enum.Enum):
    """Типы маркетплейсов"""
    OZON = "ozon"
    WILDBERRIES = "wildberries"


class Marketplace(BaseModel):
    """Модель подключения к маркетплейсу"""
    
    __tablename__ = "marketplaces"
    
    # Связь с пользователем (владельцем)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Основная информация
    type = Column(
        Enum(MarketplaceType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)  # Пользовательское название
    
    # API credentials (зашифрованы)
    api_key = Column(Text, nullable=False)
    client_id = Column(String(255), nullable=True)  # Для Ozon
    
    # Настройки
    is_kiz_enabled = Column(Boolean, default=False, nullable=False)  # КИЗ: WB + Ozon (Ozon — только сохранять в БД)
    save_kiz_to_file = Column(Boolean, default=False, nullable=False)  # Сохранять КИЗ в файл после упаковки
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Синхронизация
    last_sync_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="marketplaces")
    warehouses = relationship(
        "Warehouse",
        back_populates="marketplace",
        cascade="all, delete-orphan",
    )
    orders = relationship(
        "Order",
        back_populates="marketplace",
        cascade="all, delete-orphan",
    )
    
    def __repr__(self) -> str:
        return f"<Marketplace(id={self.id}, type={self.type}, name={self.name})>"
    
    @property
    def is_ozon(self) -> bool:
        """Проверка, является ли маркетплейс Ozon"""
        return self.type == MarketplaceType.OZON
    
    @property
    def is_wildberries(self) -> bool:
        """Проверка, является ли маркетплейс Wildberries"""
        return self.type == MarketplaceType.WILDBERRIES
    
    def update_sync_time(self) -> None:
        """Обновление времени последней синхронизации"""
        self.last_sync_at = datetime.utcnow()
