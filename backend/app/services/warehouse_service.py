"""
Сервис синхронизации складов маркетплейсов
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import RateLimitException
from app.core.security import decrypt_api_key
from app.models.marketplace import Marketplace, MarketplaceType
from app.repositories.warehouse_repository import WarehouseRepository
from app.services.marketplace.ozon import OzonClient
from app.services.marketplace.wildberries import WildberriesClient
from app.services.ozon_distributed_pace import (
    mark_ozon_warehouse_list_synced,
    should_skip_ozon_warehouse_list,
)
from app.utils.logger import logger


class WarehouseService:
    """Синхронизация складов и управление цветами"""

    @staticmethod
    async def sync_warehouses(marketplace: Marketplace, db: Session) -> int:
        """
        Синхронизация складов из API маркетплейса.
        
        Создаёт/обновляет записи Warehouse для всех складов аккаунта.
        
        Returns:
            int: Количество синхронизированных складов
        """
        api_key = decrypt_api_key(marketplace.api_key)
        
        if marketplace.type == MarketplaceType.OZON:
            if not marketplace.client_id:
                logger.warning("Ozon marketplace without client_id, skipping warehouse sync")
                return 0
            if should_skip_ozon_warehouse_list(marketplace.id):
                logger.info(
                    "Ozon: пропуск /v1/warehouse/list (кэш TTL), склады не менялись недавно",
                    extra={"marketplace_id": marketplace.id},
                )
                return 0
            async with OzonClient(
                api_key=api_key,
                client_id=marketplace.client_id,
            ) as client:
                try:
                    warehouses_data = await client.get_warehouses()
                except RateLimitException:
                    logger.warning(
                        "Ozon: лимит запросов при получении складов — пропускаем обновление складов "
                        "(заказы синхронизируются; склады в БД остаются от прошлого успешного синка)",
                        extra={"marketplace_id": marketplace.id},
                    )
                    return 0
        elif marketplace.type == MarketplaceType.WILDBERRIES:
            async with WildberriesClient(api_key=api_key) as client:
                warehouses_data = await client.get_warehouses()
        else:
            logger.warning(f"Unknown marketplace type: {marketplace.type}")
            return 0
        
        count = 0
        for wh_data in warehouses_data:
            wh_id = wh_data.get("warehouse_id") or wh_data.get("warehouseId")
            name = wh_data.get("name") or wh_data.get("warehouse_name") or f"Склад {wh_id}"
            if wh_id is None:
                continue
            WarehouseRepository.get_or_create(
                db=db,
                marketplace_id=marketplace.id,
                external_warehouse_id=str(wh_id),
                name=str(name),
            )
            count += 1

        if marketplace.type == MarketplaceType.OZON:
            mark_ozon_warehouse_list_synced(marketplace.id)

        logger.info(
            f"Synced {count} warehouses for marketplace {marketplace.id} ({marketplace.type})"
        )
        return count

    @staticmethod
    def get_warehouses_for_marketplace(marketplace_id: int, db: Session) -> list:
        """Получить все склады маркетплейса"""
        return WarehouseRepository.get_by_marketplace(db, marketplace_id)

    @staticmethod
    def update_warehouse_color(
        warehouse_id: int,
        color: str,
        db: Session,
    ) -> Optional[dict]:
        """
        Обновить цвет склада.
        
        Returns:
            dict с данными склада или None
        """
        warehouse = WarehouseRepository.update_color(db, warehouse_id, color)
        if not warehouse:
            return None
        return {
            "id": warehouse.id,
            "external_warehouse_id": warehouse.external_warehouse_id,
            "name": warehouse.name,
            "color": warehouse.color,
        }
