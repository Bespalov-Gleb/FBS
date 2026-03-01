"""
Модель логов аудита
"""
from sqlalchemy import Column, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class AuditLog(BaseModel):
    """Модель логов операций (аудит)"""
    
    __tablename__ = "audit_logs"
    
    # Связь с пользователем
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    
    # Информация о действии
    action = Column(String(100), nullable=False, index=True)  # login, logout, order_completed и т.д.
    entity_type = Column(String(50), nullable=True)  # order, user, marketplace и т.д.
    entity_id = Column(Integer, nullable=True)
    
    # Изменения (что именно изменилось)
    changes = Column(JSON, nullable=True)
    
    # Информация о запросе
    ip_address = Column(String(45), nullable=True)  # IPv4 или IPv6
    user_agent = Column(String(500), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="audit_logs")
    
    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id}, action={self.action}, "
            f"user_id={self.user_id}, entity_type={self.entity_type})>"
        )
