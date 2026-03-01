"""
Модель склада маркетплейса

Один аккаунт (Marketplace) может иметь несколько складов.
Цвет настраивается для каждого склада отдельно (вкладка Маркетплейсы).
"""
from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class Warehouse(BaseModel):
    """
    Склад маркетплейса.
    
    Связь: Marketplace (1) ──< Warehouse (N)
    external_warehouse_id — ID склада в API Ozon/WB
    """
    
    __tablename__ = "warehouses"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_id",
            "external_warehouse_id",
            name="uq_warehouse_marketplace_external",
        ),
    )
    
    # Связь с подключением к маркетплейсу
    marketplace_id = Column(
        Integer,
        ForeignKey("marketplaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # ID склада в API маркетплейса (Ozon: warehouse_id, WB: warehouseId)
    external_warehouse_id = Column(String(255), nullable=False, index=True)
    
    # Название склада (из API или заданное пользователем)
    name = Column(String(255), nullable=False)
    
    # Цвет выделения в интерфейсе (HEX, например #FF5733)
    color = Column(String(7), nullable=True)
    
    # Relationships
    marketplace = relationship("Marketplace", back_populates="warehouses")
    orders = relationship(
        "Order",
        back_populates="warehouse",
        foreign_keys="Order.warehouse_id",
    )
    
    def __repr__(self) -> str:
        return f"<Warehouse(id={self.id}, name={self.name}, marketplace_id={self.marketplace_id})>"
