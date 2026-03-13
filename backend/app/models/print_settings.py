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

    # Размеры и поворот ФБС этикеток
    ozon_width_mm = Column(Integer, nullable=True, default=58)
    ozon_height_mm = Column(Integer, nullable=True, default=40)
    ozon_label_rotate = Column(Integer, nullable=False, default=90)  # 0/90/180/270 — 90 для широких 58×40
    wb_width_mm = Column(Integer, nullable=True, default=58)
    wb_height_mm = Column(Integer, nullable=True, default=40)
    wb_label_rotate = Column(Integer, nullable=False, default=90)   # 0/90/180/270 — 90 для широкой 58×40

    # Поворот штрихкодов товаров (Ozon OZN+SKU и WB EAN)
    barcode_rotate = Column(Integer, nullable=False, default=0)     # 0/90/180/270 — штрихкод уже горизонтальный

    # Размер и поворот этикетки КИЗ
    kiz_width_mm = Column(Integer, nullable=True)    # default 40
    kiz_height_mm = Column(Integer, nullable=True)   # default 35
    kiz_rotate = Column(Integer, nullable=False, default=0)         # 0/90/180/270

    # DPI принтера (203 или 300) — для точной генерации этикеток под физический размер
    printer_dpi = Column(Integer, nullable=True, default=203)

    # Масштаб печати SumatraPDF: fit (рекомендуется) | shrink | noscale
    print_scale = Column(String(20), nullable=True, default="fit")

    # Режим печати этикеток заказов (ФБС):
    # as_is_fit — этикетки от маркетплейсов без обработки, агенту fit
    # standard_58x40_noscale — на листе 58×40 мм, агенту noscale (по умолчанию)
    label_print_mode = Column(String(30), nullable=True, default="standard_58x40_noscale")
