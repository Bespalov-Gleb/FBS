"""
Сервис синхронизации заказов с маркетплейсами
"""
import asyncio
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.security import decrypt_api_key
from app.models.marketplace import Marketplace, MarketplaceType
from app.models.order import OrderStatus
from app.repositories.order_repository import OrderRepository
from app.repositories.warehouse_repository import WarehouseRepository
from app.services.marketplace.base import MarketplaceOrder
from app.services.marketplace.ozon import OzonClient
from app.services.marketplace.wildberries import WildberriesClient
from app.services.warehouse_service import WarehouseService
from app.utils.logger import logger


class OrderSyncService:
    """Синхронизация заказов из Ozon и Wildberries в БД"""

    @staticmethod
    async def sync_marketplace_orders(marketplace: Marketplace, db: Session) -> int:
        """
        Синхронизация заказов для одного маркетплейса.
        
        Ozon: заказы awaiting_deliver
        WB: заказы new + confirm (на сборке)
        
        Returns:
            int: Количество созданных/обновлённых заказов
        """
        # 1. Синхронизируем склады
        await WarehouseService.sync_warehouses(marketplace, db)
        
        api_key = decrypt_api_key(marketplace.api_key)
        order_repo = OrderRepository(db)
        count = 0
        
        if marketplace.type == MarketplaceType.OZON:
            if not marketplace.client_id:
                logger.warning("Ozon without client_id, skipping sync")
                return 0
            async with OzonClient(
                api_key=api_key,
                client_id=marketplace.client_id,
            ) as client:
                orders, _ = await client.get_orders_awaiting_deliver(limit=1000)
                # Получаем фото товаров (POST /v3/product/info/list)
                offer_ids = list({mo.article for mo in orders if mo.article})
                product_ids = []
                sku_to_article = {}
                for mo in orders:
                    prods = (mo.metadata or {}).get("products", [])
                    if prods and (sku := prods[0].get("sku")):
                        try:
                            pid = int(sku)
                            product_ids.append(pid)
                            sku_to_article[pid] = mo.article
                        except (ValueError, TypeError):
                            pass
                product_ids = list(dict.fromkeys(product_ids))
                if offer_ids or product_ids:
                    try:
                        images = await client.get_product_images(
                            offer_ids=offer_ids or None,
                            product_ids=product_ids or None,
                            sku_to_article=sku_to_article or None,
                        )
                        for mo in orders:
                            url = images.get(mo.article)
                            if not url and mo.metadata:
                                prods = mo.metadata.get("products", [])
                                sku = prods[0].get("sku") if prods else None
                                if sku is not None:
                                    url = images.get(str(sku)) or images.get(int(sku))
                            mo.metadata["product_image_url"] = url or ""
                        with_images = sum(1 for mo in orders if mo.metadata.get("product_image_url"))
                        logger.info(f"Product images: {with_images}/{len(orders)} orders got photo")
                    except Exception as e:
                        logger.warning(f"Could not fetch product images: {e}")
                api_external_ids = {mo.external_id for mo in orders}
                for mo in orders:
                    count += OrderSyncService._upsert_order(
                        db, order_repo, marketplace, mo,
                    )
                cancelled = OrderSyncService._mark_cancelled_orders(
                    db, order_repo, marketplace.id, api_external_ids,
                )
                if cancelled:
                    logger.info(f"Marked {cancelled} cancelled orders for Ozon marketplace {marketplace.id}")

        elif marketplace.type == MarketplaceType.WILDBERRIES:
            async with WildberriesClient(api_key=api_key) as client:
                # new + confirm = на сборке (ТЗ)
                orders_new = await client.get_new_orders()
                orders_paged, _ = await client.get_orders_by_status(limit=500)
                seen = {mo.external_id for mo in orders_new}
                for mo in orders_paged:
                    if mo.external_id not in seen and mo.metadata.get("supplierStatus") == "confirm":
                        seen.add(mo.external_id)
                        orders_new.append(mo)
                # URL фото: Content API (официально), fallback — CDN
                unique_nm_ids = list({
                    (mo.metadata or {}).get("nm_id")
                    for mo in orders_new
                    if (mo.metadata or {}).get("nm_id") is not None
                })
                nm_to_url: dict[int | str, str] = {}
                for nm_id in unique_nm_ids:
                    try:
                        url = await client.get_product_image_url_content_api(nm_id)
                        if url:
                            nm_to_url[nm_id] = url
                        else:
                            nm_to_url[nm_id] = WildberriesClient.build_product_image_url(nm_id) or ""
                    except Exception as e:
                        logger.debug(f"WB Content API image for nm_id={nm_id}: {e}")
                        nm_to_url[nm_id] = WildberriesClient.build_product_image_url(nm_id) or ""
                    await asyncio.sleep(0.7)  # ~100 req/min лимит Content API
                for mo in orders_new:
                    nm_id = (mo.metadata or {}).get("nm_id")
                    if nm_id is not None:
                        if mo.metadata is None:
                            mo.metadata = {}
                        mo.metadata["product_image_url"] = nm_to_url.get(nm_id, "") or ""
                with_images = sum(1 for mo in orders_new if (mo.metadata or {}).get("product_image_url"))
                if orders_new:
                    logger.info(f"WB product images: {with_images}/{len(orders_new)} orders got photo")
                api_external_ids = {mo.external_id for mo in orders_new}
                for mo in orders_new:
                    count += OrderSyncService._upsert_order(
                        db, order_repo, marketplace, mo,
                    )
                cancelled = OrderSyncService._mark_cancelled_orders(
                    db, order_repo, marketplace.id, api_external_ids,
                )
                if cancelled:
                    logger.info(f"Marked {cancelled} cancelled orders for WB marketplace {marketplace.id}")
        else:
            logger.warning(f"Unknown marketplace type: {marketplace.type}")
            return 0
        
        marketplace.update_sync_time()
        db.commit()
        logger.info(f"Synced {count} orders for marketplace {marketplace.id}")
        return count

    @staticmethod
    def _upsert_order(
        db: Session,
        order_repo: OrderRepository,
        marketplace: Marketplace,
        mo: MarketplaceOrder,
    ) -> int:
        """Создать или обновить заказ"""
        external_wh_id = None
        if mo.metadata:
            external_wh_id = mo.metadata.get("warehouse_id") or mo.metadata.get("warehouseId")
        if external_wh_id is None and mo.metadata and "delivery_method" in mo.metadata:
            dm = mo.metadata["delivery_method"] or {}
            external_wh_id = dm.get("warehouse_id")
        
        warehouse_id = None
        if external_wh_id is not None:
            wh = WarehouseRepository.get_or_create(
                db,
                marketplace.id,
                str(external_wh_id),
                mo.warehouse_name or f"Склад {external_wh_id}",
            )
            warehouse_id = wh.id
        
        existing = order_repo.get_by_external_id(marketplace.id, mo.external_id)
        if existing:
            order_repo.update_from_marketplace(
                existing,
                warehouse_id=warehouse_id,
                warehouse_name=mo.warehouse_name,
                metadata=mo.metadata,
            )
            return 1
        
        order_repo.create(
            marketplace_id=marketplace.id,
            external_id=mo.external_id,
            posting_number=mo.posting_number,
            article=mo.article,
            product_name=mo.product_name,
            quantity=mo.quantity,
            warehouse_id=warehouse_id,
            warehouse_name=mo.warehouse_name,
            marketplace_status=mo.status,
            marketplace_created_at=mo.created_at,
            metadata=mo.metadata,
        )
        return 1

    @staticmethod
    def _mark_cancelled_orders(
        db: Session,
        order_repo: OrderRepository,
        marketplace_id: int,
        api_external_ids: set[str],
    ) -> int:
        """
        Пометить как отменённые заказы, которых нет в API.
        Только заказы не в статусе completed.
        """
        from app.models.order import Order

        if not api_external_ids:
            return 0
        to_cancel = (
            db.query(Order)
            .filter(
                Order.marketplace_id == marketplace_id,
                Order.status != OrderStatus.COMPLETED,
                Order.status != OrderStatus.CANCELLED,
                ~Order.external_id.in_(api_external_ids),
            )
            .all()
        )
        for order in to_cancel:
            order.cancel()
        if to_cancel:
            db.commit()
        return len(to_cancel)
