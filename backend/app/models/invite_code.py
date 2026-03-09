"""
Модель инвайт-кода для регистрации упаковщиков
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class InviteCode(BaseModel):
    """
    Инвайт-код, генерируемый администратором для регистрации упаковщика.
    После использования помечается как использованный (used_by_id, used_at).
    Действует 24 часа с момента создания.
    """

    __tablename__ = "invite_codes"

    code = Column(String(32), unique=True, nullable=False, index=True)
    created_by_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    expires_at = Column(DateTime, nullable=False)
    used_by_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    used_at = Column(DateTime, nullable=True)

    created_by = relationship("User", foreign_keys=[created_by_id])
    used_by = relationship("User", foreign_keys=[used_by_id])

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

    @property
    def is_used(self) -> bool:
        return self.used_by_id is not None

    @property
    def is_valid(self) -> bool:
        return not self.is_expired and not self.is_used
