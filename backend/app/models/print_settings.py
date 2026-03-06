"""
Модель настроек печати (Диспетчер печати)
"""
from sqlalchemy import Column, ForeignKey, Integer, String, Text

from app.models.base import BaseModel


class PrintSettings(BaseModel):
    """
    Настройки печати для пользователя.
    
    ТЗ: принтер по умолчанию, формат этикеток (58/80 мм), шаблоны.
    Размеры этикеток Ozon и WB — для генерации PDF под конкретный принтер.
    """

    __tablename__ = "print_settings"

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    default_printer = Column(String(255), nullable=True)
    label_format = Column(String(20), nullable=True)  # 58mm, 80mm
    label_template = Column(Text, nullable=True)  # HTML шаблон или JSON конфиг
    auto_print_on_click = Column(String(10), nullable=True)  # "true" | "false"
    auto_print_kiz_duplicate = Column(String(10), nullable=True)  # "true" | "false" — дубль КИЗ после скана

    # Размеры этикеток (мм) — для Ozon и WB
    ozon_width_mm = Column(Integer, nullable=True, default=58)
    ozon_height_mm = Column(Integer, nullable=True, default=40)
    wb_width_mm = Column(Integer, nullable=True, default=58)
    wb_height_mm = Column(Integer, nullable=True, default=40)
