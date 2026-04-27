"""
Группы КИЗ и связи с магазинами.
"""
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    ForeignKey,
    Integer,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.base import BaseModel

kiz_group_marketplaces = Table(
    "kiz_group_marketplaces",
    Base.metadata,
    Column("group_id", Integer, ForeignKey("kiz_groups.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "marketplace_id",
        Integer,
        ForeignKey("marketplaces.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class KizGroup(BaseModel):
    __tablename__ = "kiz_groups"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_kiz_groups_user_name"),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    color = Column(String(120), nullable=True)
    size = Column(String(120), nullable=True)
    cut_type = Column(String(120), nullable=True)
    # Пользовательские подсказки для парсера/классификации (MVP: только хранение).
    parser_markers = Column(JSON, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    user = relationship("User")
    marketplaces = relationship("Marketplace", secondary=kiz_group_marketplaces, lazy="joined")
