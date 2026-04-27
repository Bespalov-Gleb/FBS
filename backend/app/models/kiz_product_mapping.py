"""
Привязка товара к группе КИЗ (один товар -> одна группа).
"""
from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class KizProductMapping(BaseModel):
    __tablename__ = "kiz_product_mappings"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "marketplace_id",
            "article",
            "size",
            name="uq_kiz_product_mapping_user_mp_article_size",
        ),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    marketplace_id = Column(Integer, ForeignKey("marketplaces.id", ondelete="CASCADE"), nullable=False, index=True)
    group_id = Column(Integer, ForeignKey("kiz_groups.id", ondelete="CASCADE"), nullable=False, index=True)

    article = Column(String(255), nullable=False, index=True)
    # Пустая строка = без размера (nullable не используем для корректного unique).
    size = Column(String(120), nullable=False, default="", server_default="")

    user = relationship("User")
    marketplace = relationship("Marketplace")
    group = relationship("KizGroup")
