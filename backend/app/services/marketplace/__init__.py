"""
Интеграции с маркетплейсами

Модуль содержит клиенты для работы с API маркетплейсов:
- Ozon Seller API
- Wildberries Marketplace API

Все реализации основаны на официальной документации.
См. API_DOCUMENTATION.md для деталей.
"""
from app.services.marketplace.base import (
    BaseMarketplaceClient,
    MarketplaceOrder,
    OrderStatus,
    Product,
)
from app.services.marketplace.ozon import OzonClient
from app.services.marketplace.wildberries import WildberriesClient

__all__ = [
    "BaseMarketplaceClient",
    "MarketplaceOrder",
    "OrderStatus",
    "Product",
    "OzonClient",
    "WildberriesClient",
]
