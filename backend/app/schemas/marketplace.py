"""
Схемы для маркетплейсов
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class MarketplaceCreate(BaseModel):
    """Создание маркетплейса"""
    type: str  # ozon | wildberries
    name: str
    api_key: str
    client_id: Optional[str] = None  # для Ozon
    is_kiz_enabled: bool = False
    save_kiz_to_file: bool = False


class MarketplaceUpdate(BaseModel):
    """Обновление маркетплейса"""
    name: Optional[str] = None
    is_kiz_enabled: Optional[bool] = None
    save_kiz_to_file: Optional[bool] = None
    is_active: Optional[bool] = None


class MarketplaceResponse(BaseModel):
    """Ответ с данными маркетплейса"""
    id: int
    type: str
    name: str
    is_kiz_enabled: bool
    save_kiz_to_file: bool
    is_active: bool
    last_sync_at: Optional[datetime] = None
