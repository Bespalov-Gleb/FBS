"""
Доступ упаковщика к конкретным маркетплейсам.
Если у пользователя нет строк в этой таблице — он видит все магазины своего владельца.
"""
from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class UserMarketplaceAccess(BaseModel):
    """Разрешение упаковщику видеть конкретный маркетплейс."""

    __tablename__ = "user_marketplace_access"

    # Переопределяем PK: используем составной (user_id, marketplace_id)
    # BaseModel добавляет автоинкрементный id — оставляем его для совместимости
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    marketplace_id = Column(
        Integer,
        ForeignKey("marketplaces.id", ondelete="CASCADE"),
        nullable=False,
    )

    user = relationship("User", foreign_keys=[user_id])
    marketplace = relationship("Marketplace", foreign_keys=[marketplace_id])
