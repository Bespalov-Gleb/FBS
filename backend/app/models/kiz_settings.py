"""
Настройки КИЗ для пользователя (маркеры цвета в артикуле и т.п.).
"""
from sqlalchemy import Column, ForeignKey, Integer, JSON
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class KizSettings(BaseModel):
    __tablename__ = "kiz_settings"

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    # Подстроки цвета для поиска в артикуле (Ozon/WB fallback), например ["white", "black", "manblack"].
    color_markers = Column(JSON, nullable=False, default=list)

    user = relationship("User")
