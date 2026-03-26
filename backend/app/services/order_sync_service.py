"""
Сервис синхронизации заказов с маркетплейсами
"""
import asyncio
import os
import random
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
        
        Ozon: заказы awaiting_deliver (с пагинацией, период 90 дней)
        WB: заказы confirm (На сборке) — через status API
        
        Returns:
            int: Количество созданных/обновлённых заказов
        """
        # 1. Синхронизируем склады
        await WarehouseService.sync_warehouses(marketplace, db)

        # Ozon: отдельный HTTP-клиент на заказы — без паузы два запроса подряд бьют в per-second
        if marketplace.type == MarketplaceType.OZON:
            try:
                _oz_gap = float(os.environ.get("OZON_MIN_REQUEST_INTERVAL_SEC", "0.55") or 0.55)
            except ValueError:
                _oz_gap = 0.55
            if _oz_gap > 0:
                await asyncio.sleep(_oz_gap)
        
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
                orders = []
                offset = 0
                while True:
                    batch, has_next = await client.get_orders_awaiting_deliver(
                        limit=1000, offset=offset
                    )
                    orders.extend(batch)
                    if not has_next or len(batch) < 1000:
                        break
                    offset += 1000
                # Собираем уникальные offer_id и sku для батч-запросов
                offer_ids = []
                sku_list = []
                sku_to_article: dict[int, str] = {}
                for mo in orders:
                    prods = (mo.metadata or {}).get("products", [])
                    for p in prods:
                        oid = p.get("offer_id")
                        if oid:
                            offer_ids.append(oid)
                        sku = p.get("sku")
                        if sku is not None and oid:
                            try:
                                sku_int = int(sku)
                                sku_list.append(sku_int)
                                sku_to_article[sku_int] = oid
                            except (ValueError, TypeError):
                                pass
                offer_ids = list(dict.fromkeys(offer_ids))
                sku_list = list(dict.fromkeys(sku_list))

                # Шаг 1: фото + posting/fbs/get (размер — приоритет фактический заказанный)
                images: dict[str, str] = {}
                details_map: dict[str, dict] = {}
                sizes_from_attrs: dict[str, str] = {}
                fetch_sizes = False
                if offer_ids or sku_list:
                    fetch_sizes = (
                        bool(offer_ids)
                        and os.environ.get("FBS_OZON_FETCH_SIZES", "1") != "0"
                    )
                    fetch_posting = (
                        fetch_sizes
                        and os.environ.get("FBS_OZON_FETCH_POSTING_DETAILS", "1") != "0"
                    )
                    posting_numbers = [
                        getattr(mo, "posting_number", None) or getattr(mo, "external_id", None)
                        for mo in orders
                        if getattr(mo, "posting_number", None) or getattr(mo, "external_id", None)
                    ]
                    posting_numbers = [pn for pn in posting_numbers if pn]
                    if fetch_sizes and fetch_posting and posting_numbers:
                        # Параллельно: фото + posting details (фактический размер заказа — приоритет)
                        _res = await asyncio.gather(
                            client.get_product_images(
                                offer_ids=offer_ids or None,
                                sku_list=sku_list or None,
                                sku_to_article=sku_to_article or None,
                            ),
                            client.get_postings_details_for_sizes(posting_numbers),
                            return_exceptions=True,
                        )
                        images = _res[0] if isinstance(_res[0], dict) else {}
                        details_map = _res[1] if isinstance(_res[1], dict) else {}
                        if isinstance(_res[0], Exception):
                            logger.warning(f"Ozon: images fetch failed: {_res[0]}")
                        if isinstance(_res[1], Exception):
                            logger.warning(f"Ozon: posting details fetch failed: {_res[1]}")
                    elif fetch_sizes:
                        # Без posting: только фото + attributes
                        _res = await asyncio.gather(
                            client.get_product_images(
                                offer_ids=offer_ids or None,
                                sku_list=sku_list or None,
                                sku_to_article=sku_to_article or None,
                            ),
                            client.get_product_sizes(offer_ids=offer_ids),
                            return_exceptions=True,
                        )
                        images = _res[0] if isinstance(_res[0], dict) else {}
                        sizes_from_attrs = _res[1] if isinstance(_res[1], dict) else {}
                        if isinstance(_res[0], Exception):
                            logger.warning(f"Ozon: images fetch failed: {_res[0]}")
                        if isinstance(_res[1], Exception):
                            logger.warning(f"Ozon: sizes fetch failed: {_res[1]}")
                    else:
                        try:
                            images = await client.get_product_images(
                                offer_ids=offer_ids or None,
                                sku_list=sku_list or None,
                                sku_to_article=sku_to_article or None,
                            )
                        except Exception as e:
                            logger.warning(f"Ozon: could not fetch images: {e}")

                def _extract_size_from_posting_product(dp: dict) -> str | None:
                    """
                    Извлечь размер из продукта posting/fbs/get.
                    Приоритет: attrs (размер продавца) → dimensions.size_name.
                    Все значения валидируются (отсекаем описание варианта, извлекаем букву).
                    """
                    for attrs_key in ("optional_product_attributes", "required_product_attributes"):
                        attrs = dp.get(attrs_key) or []
                        for a in attrs if isinstance(attrs, list) else []:
                            if not isinstance(a, dict):
                                continue
                            name = (a.get("attribute_name") or a.get("name") or "").lower()
                            if "размер" in name or "size" in name:
                                v = a.get("attribute_value") or a.get("value")
                                if v:
                                    validated = OzonClient._validate_and_extract_seller_size(str(v).strip())
                                    if validated:
                                        return validated
                    dims = dp.get("dimensions") or {}
                    if isinstance(dims, dict):
                        size_val = dims.get("size_name") or dims.get("size")
                        if size_val:
                            validated = OzonClient._validate_and_extract_seller_size(str(size_val).strip())
                            if validated:
                                return validated
                            letter = OzonClient._extract_letter_size(str(size_val).strip())
                            if letter:
                                return letter
                            if len(str(size_val).strip()) <= 15:
                                return str(size_val).strip()
                    return None

                # Шаг 2: применяем фото; размер — posting (основа) → attributes (с валидацией) → offer_id
                for mo in orders:
                    prods = (mo.metadata or {}).get("products", [])
                    if mo.metadata is None:
                        mo.metadata = {}
                    mo.metadata["product_image_url"] = ""
                    pn = getattr(mo, "posting_number", None) or getattr(mo, "external_id", None)
                    details_products = (details_map.get(pn) or {}).get("products") or [] if pn else []
                    for i, p in enumerate(prods):
                        oid = p.get("offer_id")
                        url = images.get(oid) if oid else ""
                        if not url and p.get("sku") is not None:
                            url = images.get(str(p["sku"])) or images.get(int(p["sku"])) or ""  # type: ignore[call-overload]
                        p["image_url"] = url or ""
                        if url and not mo.metadata.get("product_image_url"):
                            mo.metadata["product_image_url"] = url
                        # Размер продавца: posting (основа) → attributes (с валидацией) → offer_id
                        size_val = None
                        if i < len(details_products):
                            size_val = _extract_size_from_posting_product(details_products[i])
                        if not size_val and oid:
                            size_val = sizes_from_attrs.get(oid) or ""
                        if not size_val and oid:
                            size_val = OzonClient._extract_size_from_offer_id(oid)
                        if size_val and str(size_val).strip():
                            p["size"] = str(size_val).strip()
                    first_size = next(
                        (pr.get("size") for pr in (mo.metadata or {}).get("products", []) if pr.get("size")),
                        None,
                    )
                    if first_size and mo.metadata:
                        mo.metadata["size"] = first_size
                with_images = sum(1 for mo in orders if (mo.metadata or {}).get("product_image_url"))
                logger.info(f"Product images: {with_images}/{len(orders)} orders got photo")
                if details_map:
                    logger.info("Ozon: sizes from posting/fbs/get (primary, actual ordered size)")
                elif sizes_from_attrs:
                    logger.info("Ozon: sizes from get_product_sizes (attributes, posting disabled)")

                # Шаг 3 (fallback): get_product_sizes — только для заказов БЕЗ размера (когда posting уже запрашивали)
                if fetch_sizes and details_map:
                    orders_without_size = [
                        mo for mo in orders
                        if not any(p.get("size") for p in (mo.metadata or {}).get("products", []))
                    ]
                    if orders_without_size and offer_ids:
                        fallback_offer_ids = list(dict.fromkeys(
                            oid for mo in orders_without_size
                            for p in (mo.metadata or {}).get("products", [])
                            if (oid := p.get("offer_id"))
                        ))
                        if fallback_offer_ids:
                            try:
                                sizes_fallback = await client.get_product_sizes(fallback_offer_ids)
                                sizes_fallback_count = 0
                                for mo in orders_without_size:
                                    prods = (mo.metadata or {}).get("products", [])
                                    for p in prods:
                                        oid = p.get("offer_id")
                                        if oid and not p.get("size"):
                                            sv = sizes_fallback.get(oid) or ""
                                            if sv and str(sv).strip():
                                                p["size"] = str(sv).strip()
                                                sizes_fallback_count += 1
                                            elif not p.get("size"):
                                                from_offer = OzonClient._extract_size_from_offer_id(oid)
                                                if from_offer:
                                                    p["size"] = from_offer
                                                    sizes_fallback_count += 1
                                    first_size = next(
                                        (pr.get("size") for pr in prods if pr.get("size")),
                                        None,
                                    )
                                    if first_size and mo.metadata:
                                        mo.metadata["size"] = first_size
                                if sizes_fallback_count:
                                    logger.info(
                                        "Ozon: %s sizes from get_product_sizes (fallback, %s orders)",
                                        sizes_fallback_count, len(orders_without_size),
                                    )
                            except Exception as e:
                                logger.warning("Ozon: get_product_sizes fallback failed: %s", e)
                    still_missing = [
                        mo for mo in orders
                        if not any(p.get("size") for p in (mo.metadata or {}).get("products", []))
                    ]
                    if still_missing:
                        for mo in still_missing[:3]:
                            prods = (mo.metadata or {}).get("products", [])
                            p0 = prods[0] if prods else {}
                            logger.info(
                                "Ozon size MISSING: posting=%s offer_ids=%s first_product: size=%r dims=%r keys=%s",
                                getattr(mo, "posting_number", ""),
                                [p.get("offer_id") for p in prods],
                                p0.get("size"),
                                p0.get("dimensions"),
                                list(p0.keys()) if p0 else [],
                            )
                        if len(still_missing) > 3:
                            logger.info("Ozon size MISSING: ... and %s more orders", len(still_missing) - 3)
                api_external_ids = {mo.external_id for mo in orders}
                for mo in orders:
                    count += OrderSyncService._upsert_order(
                        db, order_repo, marketplace, mo,
                    )
                # delivering (в доставке) и delivered (доставлен) → DELIVERED (скрыть)
                # filter: since, to — по irenicaa/ozon-seller (GetPostingFBSListFilter)
                delivered_ids: set[str] = set()
                try:
                    off = 0
                    marked_delivered = 0
                    while True:
                        batch, has_next = await client.get_orders_delivered_or_delivering(
                            limit=1000, offset=off, days_back=30
                        )
                        for mo in batch:
                            delivered_ids.add(mo.external_id)
                            raw_status = (mo.metadata or {}).get("status", "")
                            if raw_status in ("delivering", "delivered"):
                                pn = getattr(mo, "posting_number", None) or (mo.metadata or {}).get("posting_number")
                                if order_repo.mark_delivered_by_marketplace(
                                    marketplace.id, mo.external_id, posting_number=pn
                                ):
                                    marked_delivered += 1
                                    count += 1
                        if not has_next or len(batch) < 1000:
                            break
                        off += 1000
                    if delivered_ids:
                        logger.info(
                            f"Ozon marketplace {marketplace.id}: {marked_delivered} delivering/delivered→hidden"
                        )
                except Exception as e:
                    logger.warning(f"Could not sync delivered Ozon orders: {e}")
                all_known_ids = api_external_ids | delivered_ids
                cancelled = OrderSyncService._mark_cancelled_orders(
                    db, order_repo, marketplace.id, all_known_ids,
                )
                if cancelled:
                    logger.info(f"Marked {cancelled} cancelled orders for Ozon marketplace {marketplace.id}")

        elif marketplace.type == MarketplaceType.WILDBERRIES:
            async with WildberriesClient(api_key=api_key) as client:
                # ТЗ: только заказы «На сборке» (confirm), но обновляем complete/cancel
                orders_new, status_updates, all_external_ids = await client.get_orders_in_assembly(
                    days_back=30, limit_per_request=500
                )
                logger.info(
                    f"WB marketplace {marketplace.id}: confirm={len(orders_new)}, "
                    f"all_external_ids={len(all_external_ids)}, status_updates={len(status_updates)}"
                )
                # Обновить статусы: complete (в доставке) → DELIVERED (скрыть), cancel/new → cancelled
                # Не трогаем заказы, собранные в приложении (collected_in_app=True):
                # WB отдаёт complete, но мы больше не вызываем supply API при сборке —
                # статус меняется только локально, синк не должен его сбрасывать.
                for ext_id, wb_status in status_updates.items():
                    if wb_status == "complete":
                        existing_order = order_repo.get_by_external_id(marketplace.id, ext_id)
                        if existing_order and existing_order.collected_in_app:
                            continue
                        if order_repo.mark_delivered_by_marketplace(marketplace.id, ext_id):
                            count += 1
                    elif wb_status in ("cancel", "new"):
                        if order_repo.mark_cancelled_by_marketplace(marketplace.id, ext_id):
                            count += 1
                # URL фото и размер: Content API (официально), fallback — CDN.
                # WB Content API имеет жёсткий лимит. Запросы последовательные с паузой
                # _WB_CONTENT_SLEEP между ними. Случайный начальный сдвиг (jitter) не даёт
                # двум Celery-воркерам синхронно бомбить один endpoint одним API-ключом.
                unique_nm_ids = list({
                    (mo.metadata or {}).get("nm_id")
                    for mo in orders_new
                    if (mo.metadata or {}).get("nm_id") is not None
                })
                _WB_CONTENT_SLEEP = 2.0  # 1 req / 2s = 30 req/min на воркер

                nm_to_card: dict[int | str, dict | None] = {}
                if unique_nm_ids:
                    # Случайный сдвиг 0–4s, чтобы воркеры не шли в ногу
                    await asyncio.sleep(random.uniform(0, 4))
                    for idx, nm_id in enumerate(unique_nm_ids):
                        _res = await client.get_product_card_content_api(nm_id)
                        nm_to_card[nm_id] = _res
                        if idx < len(unique_nm_ids) - 1:
                            await asyncio.sleep(_WB_CONTENT_SLEEP)
                for mo in orders_new:
                    nm_id = (mo.metadata or {}).get("nm_id")
                    chrt_id = (mo.metadata or {}).get("chrt_id")
                    if mo.metadata is None:
                        mo.metadata = {}
                    if nm_id is not None:
                        card = nm_to_card.get(nm_id)
                        if card:
                            photos = card.get("photos") or card.get("mediaFiles") or []
                            if photos:
                                first = photos[0]
                                url = ""
                                if isinstance(first, str) and first.startswith("http"):
                                    url = first
                                elif isinstance(first, dict):
                                    url = first.get("big") or first.get("square") or first.get("c516x688") or first.get("url") or ""
                                if url:
                                    mo.metadata["product_image_url"] = url
                            size = client._extract_size_from_card(card, chrt_id)
                            if size:
                                mo.metadata["size"] = size
                        if not mo.metadata.get("product_image_url"):
                            mo.metadata["product_image_url"] = WildberriesClient.build_product_image_url(nm_id) or ""
                with_images = sum(1 for mo in orders_new if (mo.metadata or {}).get("product_image_url"))
                if orders_new:
                    logger.info(f"WB product images: {with_images}/{len(orders_new)} orders got photo")
                for mo in orders_new:
                    count += OrderSyncService._upsert_order(
                        db, order_repo, marketplace, mo,
                    )
                cancelled = OrderSyncService._mark_cancelled_orders(
                    db, order_repo, marketplace.id, all_external_ids,
                )
                if cancelled:
                    logger.info(
                        f"WB marketplace {marketplace.id}: marked {cancelled} cancelled "
                        f"(not in API response for last 30 days)"
                    )
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
        
        order_status = None
        if mo.status:
            try:
                order_status = OrderStatus(mo.status)
            except ValueError:
                pass

        existing = order_repo.get_by_external_id(marketplace.id, mo.external_id)
        if existing:
            # Не перезаписывать статус, если заказ уже собран локально.
            # Ozon: остаётся в awaiting_deliver до приёмки на складе Ozon — синк не сбрасывает.
            # WB: supply API не вызывается, заказ остаётся confirm на WB — синк не сбрасывает
            # COMPLETED обратно в awaiting_packaging.
            status_to_set = order_status if existing.status != OrderStatus.COMPLETED else None
            order_repo.update_from_marketplace(
                existing,
                status=status_to_set,
                marketplace_status=mo.status,
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
            status=order_status,
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
        Не трогаем completed, delivered, cancelled.
        """
        from app.models.order import Order

        if not api_external_ids:
            return 0
        to_cancel = (
            db.query(Order)
            .filter(
                Order.marketplace_id == marketplace_id,
                Order.status != OrderStatus.COMPLETED,
                Order.status != OrderStatus.DELIVERED,
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
