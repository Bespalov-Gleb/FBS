"""
Доступ упаковщика к конкретным маркетплейсам.
Если у пользователя нет строк в этой таблице — он видит все магазины своего владельца.

Используем Base напрямую (без BaseModel), т.к. это простая join-таблица
без нужды в автоинкрементном id и временны́х метках.
"""
from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.core.database import Base


class UserMarketplaceAccess(Base):
    """Разрешение упаковщику видеть конкретный маркетплейс."""

    __tablename__ = "user_marketplace_access"

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    marketplace_id = Column(
        Integer,
        ForeignKey("marketplaces.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )

    user = relationship("User", foreign_keys=[user_id])
    marketplace = relationship("Marketplace", foreign_keys=[marketplace_id])
