"""
Схемы для заказов
"""
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel


class OrderCompleteRequest(BaseModel):
    """Запрос на отметку «Собрано». КИЗ — один или массив (по одному на каждый товар)."""
    kiz_code: Optional[str] = None  # один КИЗ (для quantity=1)
    kiz_codes: Optional[List[str]] = None  # массив КИЗ (для quantity>=2)


class OrderProductItem(BaseModel):
    """Товар в заказе (Ozon: несколько товаров в одном posting)"""
    offer_id: str = ""
    name: str = ""
    quantity: int = 1
    image_url: str = ""
    size: Optional[str] = None  # Размер (если есть в API)


class OrdersListResponse(BaseModel):
    """Пагинированный список заказов"""
    items: list["OrderResponse"]
    total: int


class OrderResponse(BaseModel):
    """Ответ со списком заказов"""
    id: int
    external_id: str
    posting_number: str
    article: str
    product_name: str
    quantity: int
    status: str
    marketplace_id: int
    marketplace_type: Optional[str] = None
    warehouse_id: Optional[int] = None
    warehouse_name: Optional[str] = None
    warehouse_color: Optional[str] = None
    product_image_url: Optional[str] = None  # Фото товара (Ozon: primary_image)
    size: Optional[str] = None  # Размер (WB/Ozon — из extra_data или API)
    marketplace_created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    # Блокировка (захват упаковщиком)
    assigned_to_id: Optional[int] = None
    assigned_at: Optional[datetime] = None
    assigned_to_name: Optional[str] = None
    is_locked_by_me: bool = False
    is_locked_by_other: bool = False
    is_kiz_enabled: bool = False  # Маркетплейс требует КИЗ (WB + Ozon)
    products: list[OrderProductItem] = []  # Ozon: несколько товаров в одном заказе


# Разрешение forward reference для OrdersListResponse
OrdersListResponse.model_rebuild()