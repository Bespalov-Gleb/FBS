"""
Схемы для заказов
"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


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
    marketplace_created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    # Блокировка (захват упаковщиком)
    assigned_to_id: Optional[int] = None
    assigned_at: Optional[datetime] = None
    assigned_to_name: Optional[str] = None
    is_locked_by_me: bool = False
    is_locked_by_other: bool = False
    is_kiz_enabled: bool = False  # Маркетплейс требует КИЗ (WB + Ozon)


# Разрешение forward reference для OrdersListResponse
OrdersListResponse.model_rebuild()