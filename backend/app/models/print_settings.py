"""
Модель настроек печати (Диспетчер печати)
"""
from sqlalchemy import Column, ForeignKey, Integer, String, Text

from app.models.base import BaseModel


class PrintSettings(BaseModel):
    """
    Настройки печати для пользователя.
    
    ТЗ: принтер по умолчанию, формат этикеток (58/80 мм), шаблоны.
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
