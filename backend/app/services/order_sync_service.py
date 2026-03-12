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

                # Шаг 1: фото + «Размер продавца» — параллельно одним gather
                images: dict[str, str] = {}
                sizes: dict[str, str] = {}
                if offer_ids or sku_list:
                    fetch_sizes = (
                        bool(offer_ids)
                        and os.environ.get("FBS_OZON_FETCH_SIZES", "1") != "0"
                    )
                    if fetch_sizes:
                        # Параллельный запрос фото и размеров — экономим 1 последовательный round-trip
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
                        sizes = _res[1] if isinstance(_res[1], dict) else {}
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

                # Шаг 2: применяем фото и «Размер продавца» ко всем заказам
                for mo in orders:
                    prods = (mo.metadata or {}).get("products", [])
                    if mo.metadata is None:
                        mo.metadata = {}
                    mo.metadata["product_image_url"] = ""
                    for p in prods:
                        oid = p.get("offer_id")
                        url = images.get(oid) if oid else ""
                        if not url and p.get("sku") is not None:
                            url = images.get(str(p["sku"])) or images.get(int(p["sku"])) or ""  # type: ignore[call-overload]
                        p["image_url"] = url or ""
                        if url and not mo.metadata.get("product_image_url"):
                            mo.metadata["product_image_url"] = url
                        if oid:
                            seller_size = sizes.get(oid) or ""
                            if seller_size and str(seller_size).strip():
                                p["size"] = str(seller_size).strip()
                                logger.debug(
                                    "Ozon size [get_product_sizes]: posting=%s offer_id=%s size=%r",
                                    getattr(mo, "posting_number", ""), oid, seller_size,
                                )
                            elif not p.get("size"):
                                logger.debug(
                                    "Ozon size [get_product_sizes]: posting=%s offer_id=%s NO_SIZE (sizes keys sample=%s)",
                                    getattr(mo, "posting_number", ""), oid, list(sizes.keys())[:5] if sizes else [],
                                )
                    first_size = next(
                        (p.get("size") for p in (mo.metadata or {}).get("products", []) if p.get("size")),
                        None,
                    )
                    if first_size and mo.metadata:
                        mo.metadata["size"] = first_size
                with_images = sum(1 for mo in orders if (mo.metadata or {}).get("product_image_url"))
                logger.info(f"Product images: {with_images}/{len(orders)} orders got photo")

                # Шаг 3 (fallback): posting/fbs/get только для заказов БЕЗ размера
                # Таких обычно 0 — экономим N отдельных запросов
                if os.environ.get("FBS_OZON_FETCH_POSTING_DETAILS", "1") != "0":
                    orders_without_size = [
                        mo for mo in orders
                        if not any(p.get("size") for p in (mo.metadata or {}).get("products", []))
                    ]
                    if orders_without_size:
                        pns_missing = [
                            mo.posting_number
                            for mo in orders_without_size
                            if getattr(mo, "posting_number", None)
                        ]
                        logger.info(
                            f"Ozon: {len(orders_without_size)} orders without size, "
                            f"fetching posting details as fallback"
                        )
                        try:
                            details_map = await client.get_postings_details_for_sizes(pns_missing)
                            sizes_from_get = 0
                            for mo in orders_without_size:
                                pn = getattr(mo, "posting_number", None)
                                if not pn or pn not in details_map:
                                    continue
                                details_products = (details_map.get(pn) or {}).get("products") or []
                                our_prods = (mo.metadata or {}).get("products") or []
                                for i, dp in enumerate(details_products):
                                    if i >= len(our_prods) or our_prods[i].get("size"):
                                        continue
                                    size_val = None
                                    size_source = None
                                    # Сначала атрибуты — там чаще буквенный размер (M, L, XL)
                                    for attrs_key in ("optional_product_attributes", "required_product_attributes"):
                                        attrs = dp.get(attrs_key) or []
                                        for a in attrs if isinstance(attrs, list) else []:
                                            if not isinstance(a, dict):
                                                continue
                                            name = (a.get("attribute_name") or a.get("name") or "").lower()
                                            if "размер" in name or "size" in name:
                                                v = a.get("attribute_value") or a.get("value")
                                                if v:
                                                    size_val = v
                                                    size_source = f"{attrs_key}.{name}"
                                                    break
                                        if size_val:
                                            break
                                    if not size_val:
                                        dims = dp.get("dimensions") or {}
                                        if isinstance(dims, dict):
                                            size_val = dims.get("size_name") or dims.get("size")
                                            size_source = "dimensions.size_name|size" if size_val else None
                                    if size_val and str(size_val).strip():
                                        raw = str(size_val).strip()
                                        letter = OzonClient._extract_letter_size(raw)
                                        our_prods[i]["size"] = letter if letter else raw
                                        sizes_from_get += 1
                                        logger.debug(
                                            "Ozon size [posting/fbs/get fallback]: posting=%s product_idx=%s source=%s size=%r",
                                            pn, i, size_source or "unknown", size_val,
                                        )
                                    elif not our_prods[i].get("size"):
                                        opt_attrs = dp.get("optional_product_attributes") or []
                                        req_attrs = dp.get("required_product_attributes") or []
                                        dims = dp.get("dimensions")
                                        attr_names = [
                                            (a.get("attribute_name") or a.get("name") or "")
                                            for a in (opt_attrs + req_attrs)
                                            if isinstance(a, dict)
                                        ]
                                        logger.debug(
                                            "Ozon size [posting/fbs/get fallback]: posting=%s product_idx=%s NO_SIZE attr_names=%r dims=%r",
                                            pn, i, attr_names, dims,
                                        )
                                # Обновляем первый размер для карточки
                                first_size = next(
                                    (p.get("size") for p in our_prods if p.get("size")),
                                    None,
                                )
                                if first_size and mo.metadata:
                                    mo.metadata["size"] = first_size
                            if sizes_from_get:
                                logger.info(
                                    "Ozon: %s sizes from posting/fbs/get (fallback, %s orders)",
                                    sizes_from_get, len(orders_without_size),
                                )
                            still_missing = [
                                mo for mo in orders_without_size
                                if not any(p.get("size") for p in (mo.metadata or {}).get("products", []))
                            ]
                            if still_missing:
                                for mo in still_missing[:3]:  # первые 3 для лога
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
                        except Exception as e:
                            logger.warning("Ozon: posting details fallback failed: %s", e)
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
