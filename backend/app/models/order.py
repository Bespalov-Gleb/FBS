"""
Модель заказа
"""
import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class OrderStatus(str, enum.Enum):
    """Статусы заказов"""
    AWAITING_PACKAGING = "awaiting_packaging"  # Ожидает упаковки
    PACKAGING = "packaging"  # В процессе упаковки
    COMPLETED = "completed"  # Собран (и отправлен — в доставке)
    DELIVERED = "delivered"  # Доставлен покупателю — не показывать в списке
    CANCELLED = "cancelled"  # Отменен


class Order(BaseModel):
    """Модель заказа"""
    
    __tablename__ = "orders"
    
    # Связь с маркетплейсом
    marketplace_id = Column(
        Integer,
        ForeignKey("marketplaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Идентификаторы из маркетплейса
    external_id = Column(String(255), nullable=False, index=True)  # ID в маркетплейсе
    posting_number = Column(String(255), nullable=False, index=True)  # Номер отправления
    
    # Информация о товаре
    article = Column(String(255), nullable=False, index=True)  # Артикул
    product_name = Column(String(500), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    
    # Информация о складе
    warehouse_id = Column(
        Integer,
        ForeignKey("warehouses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    warehouse_name = Column(String(255), nullable=True)  # Денормализация для отображения
    
    # Статусы
    status = Column(
        Enum(OrderStatus, values_callable=lambda x: [e.value for e in x]),
        default=OrderStatus.AWAITING_PACKAGING,
        nullable=False,
        index=True,
    )
    marketplace_status = Column(String(100), nullable=True)  # Оригинальный статус из API
    
    # Временные метки
    marketplace_created_at = Column(DateTime, nullable=True)  # Дата создания в маркетплейсе
    assigned_at = Column(DateTime, nullable=True)  # Когда взят в работу
    completed_at = Column(DateTime, nullable=True)  # Когда собран
    
    # Связь с пользователями
    assigned_to_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    completed_by_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Отмечен «Собрано» в нашем приложении (не статус от Ozon/WB)
    collected_in_app = Column(Boolean, default=False, nullable=False, index=True)

    # КИЗ (для Wildberries)
    kiz_code = Column(String(255), nullable=True)
    
    # Дополнительные данные
    extra_data = Column(JSON, nullable=True)  # Любые дополнительные данные из маркетплейса
    
    # Relationships
    marketplace = relationship("Marketplace", back_populates="orders")
    warehouse = relationship(
        "Warehouse",
        back_populates="orders",
        foreign_keys=[warehouse_id],
    )
    assigned_to_user = relationship(
        "User",
        foreign_keys=[assigned_to_id],
        back_populates="assigned_orders",
    )
    completed_by_user = relationship(
        "User",
        foreign_keys=[completed_by_id],
        back_populates="completed_orders",
    )
    
    def __repr__(self) -> str:
        return (
            f"<Order(id={self.id}, article={self.article}, "
            f"status={self.status}, posting_number={self.posting_number})>"
        )
    
    @property
    def is_awaiting_packaging(self) -> bool:
        """Проверка, ожидает ли заказ упаковки"""
        return self.status == OrderStatus.AWAITING_PACKAGING
    
    @property
    def is_packaging(self) -> bool:
        """Проверка, в процессе ли упаковки заказ"""
        return self.status == OrderStatus.PACKAGING
    
    @property
    def is_completed(self) -> bool:
        """Проверка, собран ли заказ"""
        return self.status == OrderStatus.COMPLETED
    
    @property
    def is_cancelled(self) -> bool:
        """Проверка, отменен ли заказ"""
        return self.status == OrderStatus.CANCELLED

    @property
    def is_delivered(self) -> bool:
        """Проверка, доставлен ли заказ (скрыт из списка)"""
        return self.status == OrderStatus.DELIVERED

    @property
    def has_multiple_items(self) -> bool:
        """Проверка, содержит ли заказ 2 или более единиц товара"""
        return self.quantity >= 2

    @property
    def warehouse_color(self) -> str | None:
        """Цвет склада для выделения в интерфейсе"""
        return self.warehouse.color if self.warehouse else None
    
    def assign_to(self, user_id: int) -> None:
        """
        Назначить заказ на пользователя (захват для работы).
        
        Args:
            user_id: ID пользователя
        """
        self.assigned_to_id = user_id
        self.assigned_at = datetime.utcnow()
        self.status = OrderStatus.PACKAGING

    def release(self) -> None:
        """Освободить заказ (закрытие окна без «Собрано»)"""
        self.assigned_to_id = None
        self.assigned_at = None
        self.status = OrderStatus.AWAITING_PACKAGING

    def is_locked_by(self, user_id: int) -> bool:
        """Проверка, захвачен ли заказ данным пользователем"""
        return self.assigned_to_id == user_id

    def is_locked_by_other(self, user_id: int) -> bool:
        """Проверка, захвачен ли заказ другим пользователем"""
        return self.assigned_to_id is not None and self.assigned_to_id != user_id

    def complete(self, user_id: int, kiz_code: str | None = None) -> None:
        """
        Отметить заказ как собранный в нашем приложении.
        
        Args:
            user_id: ID пользователя, который собрал
            kiz_code: КИЗ код (опционально)
        """
        self.completed_by_id = user_id
        self.completed_at = datetime.utcnow()
        self.status = OrderStatus.COMPLETED
        self.collected_in_app = True

        if kiz_code:
            self.kiz_code = kiz_code
    
    def cancel(self) -> None:
        """Отменить заказ"""
        self.status = OrderStatus.CANCELLED
