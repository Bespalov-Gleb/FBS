"""
Таблица отсканированных КИЗ пользователя.
Отдельная от заказов — для накопления сканов за рабочий день и выгрузки в WB/Ozon.
"""
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class ScannedKiz(BaseModel):
    """
    Отсканированный КИЗ пользователя.
    Накапливаются за рабочий день, выгружаются в таблицу WB/Ozon, очищаются кнопкой.
    """

    __tablename__ = "scanned_kiz"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kiz_code = Column(String(255), nullable=False)

    # Контекст заказа (для формата WB: № задания, Стикер)
    external_id = Column(String(255), nullable=True)  # № задания (WB)
    posting_number = Column(String(255), nullable=True)  # Стикер / Номер отправления
    marketplace_id = Column(Integer, ForeignKey("marketplaces.id", ondelete="SET NULL"), nullable=True, index=True)

    marketplace = relationship("Marketplace", lazy="joined")
