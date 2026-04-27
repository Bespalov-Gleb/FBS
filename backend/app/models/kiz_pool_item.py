"""
Пул КИЗ-кодов, загруженных из PDF.
"""
import enum

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class KizCodeStatus(str, enum.Enum):
    FREE = "free"
    USED = "used"


class KizPoolItem(BaseModel):
    __tablename__ = "kiz_pool_items"

    code = Column(String(255), nullable=False, unique=True, index=True)
    group_id = Column(Integer, ForeignKey("kiz_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    source_filename = Column(String(255), nullable=True)
    source_page = Column(Integer, nullable=True)

    status = Column(
        Enum(KizCodeStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=KizCodeStatus.FREE,
        index=True,
    )
    used_at = Column(DateTime, nullable=True)
    used_order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    used_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    group = relationship("KizGroup")
    used_order = relationship("Order")
    used_by_user = relationship("User")
