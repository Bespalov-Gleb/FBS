"""
Модель пользователя
"""
import enum

from sqlalchemy import Boolean, Column, Enum, String
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class UserRole(str, enum.Enum):
    """Роли пользователей"""
    ADMIN = "admin"
    PACKER = "packer"


class User(BaseModel):
    """Модель пользователя"""
    
    __tablename__ = "users"
    
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(
        Enum(UserRole, values_callable=lambda x: [e.value for e in x]),
        default=UserRole.PACKER,
        nullable=False,
        index=True,
    )
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relationships
    marketplaces = relationship(
        "Marketplace",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    completed_orders = relationship(
        "Order",
        foreign_keys="Order.completed_by_id",
        back_populates="completed_by_user",
    )
    assigned_orders = relationship(
        "Order",
        foreign_keys="Order.assigned_to_id",
        back_populates="assigned_to_user",
    )
    audit_logs = relationship(
        "AuditLog",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"
    
    @property
    def is_admin(self) -> bool:
        """Проверка, является ли пользователь администратором"""
        return self.role == UserRole.ADMIN
    
    @property
    def is_packer(self) -> bool:
        """Проверка, является ли пользователь упаковщиком"""
        return self.role == UserRole.PACKER
