"""
Сервис синхронизации заказов с маркетплейсами
"""
import asyncio
import os
import random
import time
from datetime import datetime
from typing import Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import decrypt_api_key
from app.models.marketplace import Marketplace, MarketplaceType
from app.models.order import OrderStatus
from app.repositories.order_repository import OrderRepository
from app.repositories.warehouse_repository import WarehouseRepository
from app.services.marketplace.base import MarketplaceOrder
from app.models.order import Order
from app.services.marketplace.ozon import OzonClient
from app.services.marketplace.wildberries import WildberriesClient
from app.services.marketplace.yandex import YandexMarketClient, action_for_left_order
from app.services.product_barcode import choose_product_barcode
from app.services.order_sync_guard import (
    AutoSyncCancelled,
    ManualSyncLockTimeout,
    OrderSyncGuard,
    SyncCooldownError,
)
from app.services.warehouse_service import WarehouseService
from app.utils.cache import cache_get, cache_set
from app.utils.logger import logger


def agent_dbg_bc5cf5(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    # #region agent log
    try:
        import json
        import time
        import urllib.request

        payload = {
            "sessionId": "bc5cf5",
            "runId": "pre-fix",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        for path in (
            r"c:\Users\ArdorPC\PycharmProjects\FBS\debug-bc5cf5.log",
            "/app/app/debug-bc5cf5.log",
            "/app/logs/debug-bc5cf5.log",
        ):
            try:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(line)
            except Exception:
                pass
        body = json.dumps(payload).encode()
        for url in (
            "http://127.0.0.1:7463/ingest/e2404570-1ea5-4d9f-ab98-10b1a5a56c41",
            "http://host.docker.internal:7463/ingest/e2404570-1ea5-4d9f-ab98-10b1a5a56c41",
        ):
            try:
                req = urllib.request.Request(
                    url,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Debug-Session-Id": "bc5cf5",
                    },
                )
                urllib.request.urlopen(req, timeout=0.25)
                break
            except Exception:
                pass
    except Exception:
        pass
    # #endregion


class OrderSyncService:
    """Синхронизация заказов из Ozon и Wildberries в БД"""

    _OZON_ENRICH_CACHE_TTL = 12 * 3600
    _WB_CARD_CACHE_TTL = 24 * 3600
    _MIN_INTERVAL_SEC = int(os.environ.get("ORDER_SYNC_MIN_INTERVAL_SEC", "3600") or 3600)

    @staticmethod
    def _assert_sync_interval(marketplace: Marketplace, *, source: str) -> None:
        """Ограничение частоты только для авто-синка. Ручной sync — всегда по нажатию."""
        if source == "manual":
            return
        if not marketplace.last_sync_at:
            return
        elapsed = (datetime.utcnow() - marketplace.last_sync_at).total_seconds()
        seconds_left = int(OrderSyncService._MIN_INTERVAL_SEC - elapsed)
        if seconds_left <= 0:
            return
        raise AutoSyncCancelled(
            f"Auto sync skipped due cooldown marketplace={marketplace.id}, wait={seconds_left}s"
        )

    @staticmethod
    def _check_auto_cancel(sync_source: str, marketplace_id: int) -> None:
        """Кооперативная отмена автосинка, если запрошен ручной."""
        if sync_source == "auto":
            OrderSyncGuard.ensure_auto_not_cancelled(marketplace_id)

    @staticmethod
    async def sync_marketplace_orders(
        marketplace: Marketplace,
        db: Session,
        *,
        sync_source: Literal["auto", "manual"] = "manual",
    ) -> int:
        if sync_source == "auto" and OrderSyncGuard.should_skip_auto(marketplace.id):
            logger.info(
                "Skip auto sync for marketplace %s: manual sync has priority",
                marketplace.id,
            )
            return 0

        manual_priority = sync_source == "manual"
        lock_token: str | None = None
        if manual_priority:
            OrderSyncGuard.request_manual_priority(marketplace.id)

        outcome = "unknown"
        err_name = ""
        synced_count: int | None = None
        started = time.perf_counter()
        try:
            try:
                lock_token = OrderSyncGuard.acquire_lock(marketplace.id, sync_source)
            except ManualSyncLockTimeout as e:
                outcome = "lock_timeout"
                err_name = type(e).__name__
                logger.warning("Manual sync lock timeout marketplace=%s: %s", marketplace.id, e)
                raise
            if lock_token is None:
                outcome = "lock_busy"
                logger.info("Skip auto sync for marketplace %s: lock is busy", marketplace.id)
                return 0

            db.refresh(marketplace)
            OrderSyncService._assert_sync_interval(marketplace, source=sync_source)
            synced_count = await OrderSyncService._sync_marketplace_orders_unlocked(
                marketplace,
                db,
                sync_source=sync_source,
            )
            outcome = "ok"
            return synced_count
        except AutoSyncCancelled as e:
            outcome = "cancelled"
            err_name = str(e)[:180]
            db.rollback()
            logger.info(
                "Sync cancelled for marketplace %s (source=%s): %s",
                marketplace.id,
                sync_source,
                e,
            )
            return 0
        except Exception as e:
            if outcome == "unknown":
                outcome = "error"
                err_name = f"{type(e).__name__}: {e}"[:180]
            raise
        finally:
            # #region agent log
            agent_dbg_bc5cf5(
                "ABD",
                "order_sync_service.py:sync_marketplace_orders",
                "marketplace sync finished",
                {
                    "mp": marketplace.id,
                    "mp_type": getattr(getattr(marketplace, "type", None), "value", str(marketplace.type)),
                    "source": sync_source,
                    "outcome": outcome,
                    "synced": synced_count,
                    "err": err_name,
                    "ms": int((time.perf_counter() - started) * 1000),
                    "got_lock": bool(lock_token),
                },
            )
            # #endregion
            OrderSyncGuard.release_lock(marketplace.id, lock_token)
            if manual_priority:
                OrderSyncGuard.clear_manual_priority(marketplace.id)

    @staticmethod
    async def _sync_marketplace_orders_unlocked(
        marketplace: Marketplace,
        db: Session,
        *,
        sync_source: Literal["auto", "manual"] = "manual",
    ) -> int:
        """
        Синхронизация заказов для одного маркетплейса.
        
        Ozon: заказы «ожидают отгрузки» (по умолчанию awaiting_deliver в filter.status unfulfilled/list;
        переопределение: OZON_SYNC_UNFULFILLED_STATUS).
        WB: заказы confirm (На сборке) — через status API
        
        Returns:
            int: Количество созданных/обновлённых заказов
        """
        OrderSyncService._check_auto_cancel(sync_source, marketplace.id)
        # Ozon: разнести старт синка между Celery-воркерами (один Client-Id — общий per-second лимит)
        if marketplace.type == MarketplaceType.OZON:
            try:
                _jit = float(os.environ.get("OZON_SYNC_START_JITTER_SEC", "2.5") or 0)
            except ValueError:
                _jit = 2.5
            if _jit > 0:
                await asyncio.sleep(random.uniform(0, _jit))

        OrderSyncService._check_auto_cancel(sync_source, marketplace.id)
        # 1. Синхронизируем склады
        await WarehouseService.sync_warehouses(marketplace, db)

        # Ozon: отдельный HTTP-клиент на заказы — без паузы два запроса подряд бьют в per-second
        if marketplace.type == MarketplaceType.OZON:
            try:
                _oz_gap = float(os.environ.get("OZON_MIN_REQUEST_INTERVAL_SEC", "0.22") or 0.22)
            except ValueError:
                _oz_gap = 0.22
            if _oz_gap > 0:
                await asyncio.sleep(_oz_gap)
        OrderSyncService._check_auto_cancel(sync_source, marketplace.id)

        api_key = decrypt_api_key(marketplace.api_key)
        order_repo = OrderRepository(db)
        count = 0
        
        if marketplace.type == MarketplaceType.OZON:
            if not marketplace.client_id:
                logger.warning("Ozon without client_id, skipping sync")
                return 0
            ozon_sync_status = (
                os.environ.get("OZON_SYNC_UNFULFILLED_STATUS", "awaiting_deliver")
                .strip()
                .lower()
            )
            if not ozon_sync_status:
                ozon_sync_status = "awaiting_deliver"
            async with OzonClient(
                api_key=api_key,
                client_id=marketplace.client_id,
            ) as client:
                orders = []
                cursor = None
                seen_cursors: set[str] = set()
                while True:
                    OrderSyncService._check_auto_cancel(sync_source, marketplace.id)
                    batch, has_next, cursor = await client.get_orders_unfulfilled_by_status(
                        status=ozon_sync_status,
                        limit=100,
                        cursor=cursor,
                    )
                    orders.extend(batch)
                    if not has_next or not cursor or cursor in seen_cursors:
                        break
                    seen_cursors.add(cursor)
                logger.info(
                    "Ozon sync unfulfilled status=%s, fetched=%s",
                    ozon_sync_status,
                    len(orders),
                )
                existing_external_ids: set[str] = set()
                for mo in orders:
                    if order_repo.get_by_external_id(marketplace.id, mo.external_id):
                        existing_external_ids.add(mo.external_id)
                new_orders = [mo for mo in orders if mo.external_id not in existing_external_ids]
                logger.info(
                    "Ozon sync split: new=%s existing=%s",
                    len(new_orders),
                    len(existing_external_ids),
                )
                # Собираем уникальные offer_id и sku для батч-запросов
                offer_ids = []
                sku_list = []
                sku_to_article: dict[int, str] = {}
                for mo in new_orders:
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
                ozon_cached_images: dict[str, str] = {}
                ozon_cached_sizes: dict[str, str] = {}
                uncached_offer_ids: list[str] = []
                for oid in offer_ids:
                    cimg = cache_get(f"ozon:enrich:image:{oid}")
                    csize = cache_get(f"ozon:enrich:size:{oid}")
                    if isinstance(cimg, str) and cimg:
                        ozon_cached_images[oid] = cimg
                    if isinstance(csize, str) and csize:
                        ozon_cached_sizes[oid] = csize
                    if oid not in ozon_cached_images or oid not in ozon_cached_sizes:
                        uncached_offer_ids.append(oid)
                if offer_ids:
                    logger.info(
                        "Ozon enrich cache hit: images=%s/%s sizes=%s/%s",
                        len(ozon_cached_images), len(offer_ids),
                        len(ozon_cached_sizes), len(offer_ids),
                    )

                # Шаг 1: фото + posting/fbs/get (размер — приоритет фактический заказанный)
                images: dict[str, str] = {}
                details_map: dict[str, dict] = {}
                sizes_from_attrs: dict[str, str] = {}
                fetch_sizes = False
                if uncached_offer_ids or sku_list:
                    fetch_sizes = (
                        bool(uncached_offer_ids)
                        and os.environ.get("FBS_OZON_FETCH_SIZES", "1") != "0"
                    )
                    fetch_posting = (
                        fetch_sizes
                        and os.environ.get("FBS_OZON_FETCH_POSTING_DETAILS", "1") != "0"
                    )
                    posting_numbers = [
                        getattr(mo, "posting_number", None) or getattr(mo, "external_id", None)
                        for mo in new_orders
                        if getattr(mo, "posting_number", None) or getattr(mo, "external_id", None)
                    ]
                    posting_numbers = [pn for pn in posting_numbers if pn]
                    if fetch_sizes and fetch_posting and posting_numbers:
                        # Параллельно: фото + posting details (фактический размер заказа — приоритет)
                        _res = await asyncio.gather(
                            client.get_product_images(
                                offer_ids=uncached_offer_ids or None,
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
                                offer_ids=uncached_offer_ids or None,
                                sku_list=sku_list or None,
                                sku_to_article=sku_to_article or None,
                            ),
                            client.get_product_sizes(offer_ids=uncached_offer_ids),
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
                                offer_ids=uncached_offer_ids or None,
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
                for mo in new_orders:
                    prods = (mo.metadata or {}).get("products", [])
                    if mo.metadata is None:
                        mo.metadata = {}
                    mo.metadata["product_image_url"] = ""
                    pn = getattr(mo, "posting_number", None) or getattr(mo, "external_id", None)
                    details_products = (details_map.get(pn) or {}).get("products") or [] if pn else []
                    for i, p in enumerate(prods):
                        oid = p.get("offer_id")
                        url = images.get(oid) if oid else ""
                        if not url and oid:
                            url = ozon_cached_images.get(oid, "")
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
                            size_val = ozon_cached_sizes.get(oid) or ""
                        if not size_val and oid:
                            size_val = OzonClient._extract_size_from_offer_id(oid)
                        if size_val and str(size_val).strip():
                            p["size"] = str(size_val).strip()
                        if oid and url:
                            cache_set(f"ozon:enrich:image:{oid}", url, OrderSyncService._OZON_ENRICH_CACHE_TTL)
                        if oid and p.get("size"):
                            cache_set(
                                f"ozon:enrich:size:{oid}",
                                str(p.get("size")).strip(),
                                OrderSyncService._OZON_ENRICH_CACHE_TTL,
                            )
                    first_size = next(
                        (pr.get("size") for pr in (mo.metadata or {}).get("products", []) if pr.get("size")),
                        None,
                    )
                    if first_size and mo.metadata:
                        mo.metadata["size"] = first_size
                with_images = sum(1 for mo in new_orders if (mo.metadata or {}).get("product_image_url"))
                if new_orders:
                    logger.info(f"Product images: {with_images}/{len(new_orders)} new orders got photo")
                if details_map:
                    logger.info("Ozon: sizes from posting/fbs/get (primary, actual ordered size)")
                elif sizes_from_attrs:
                    logger.info("Ozon: sizes from get_product_sizes (attributes, posting disabled)")

                # Шаг 3 (fallback): get_product_sizes — только для заказов БЕЗ размера (когда posting уже запрашивали)
                if fetch_sizes and details_map:
                    orders_without_size = [
                        mo for mo in new_orders
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
                        mo for mo in new_orders
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
                await OrderSyncService._attach_ozon_product_barcodes(client, orders)
                api_external_ids = {mo.external_id for mo in orders}
                for mo in orders:
                    OrderSyncService._check_auto_cancel(sync_source, marketplace.id)
                    count += OrderSyncService._upsert_order(
                        db, order_repo, marketplace, mo,
                        skip_metadata_if_exists=True,
                    )
                # delivering (в доставке) и delivered (доставлен) → DELIVERED (скрыть)
                # filter: since, to — по irenicaa/ozon-seller (GetPostingFBSListFilter)
                delivered_ids: set[str] = set()
                try:
                    delivered_cursor = None
                    seen_delivered_cursors: set[str] = set()
                    marked_delivered = 0
                    while True:
                        OrderSyncService._check_auto_cancel(sync_source, marketplace.id)
                        batch, has_next, delivered_cursor = await client.get_orders_delivered_or_delivering(
                            limit=100, days_back=30, cursor=delivered_cursor
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
                        if (
                            not has_next
                            or not delivered_cursor
                            or delivered_cursor in seen_delivered_cursors
                        ):
                            break
                        seen_delivered_cursors.add(delivered_cursor)
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
                # Обновить статусы: complete (в доставке) → DELIVERED (скрыть), cancel → cancelled
                # Не трогаем заказы, собранные в приложении (collected_in_app=True):
                # WB отдаёт complete, но мы больше не вызываем supply API при сборке —
                # статус меняется только локально, синк не должен его сбрасывать.
                for ext_id, wb_status in status_updates.items():
                    OrderSyncService._check_auto_cancel(sync_source, marketplace.id)
                    if wb_status == "complete":
                        existing_order = order_repo.get_by_external_id(marketplace.id, ext_id)
                        if existing_order and existing_order.collected_in_app:
                            continue
                        if order_repo.mark_delivered_by_marketplace(marketplace.id, ext_id):
                            count += 1
                    elif wb_status == "cancel":
                        if order_repo.mark_cancelled_by_marketplace(marketplace.id, ext_id):
                            count += 1
                # Тяжёлое enrichment WB (Content API) опционально:
                # по умолчанию выключено, чтобы синхронизация заказов оставалась быстрой.
                wb_enrich_content = os.environ.get("FBS_WB_ENRICH_CONTENT", "1") != "0"
                unique_nm_ids = list({
                    (mo.metadata or {}).get("nm_id")
                    for mo in orders_new
                    if (mo.metadata or {}).get("nm_id") is not None
                })
                nm_to_card: dict[int | str, dict | None] = {}
                nm_ids_to_fetch: list[int | str] = []
                for nm_id in unique_nm_ids:
                    cached_card = cache_get(f"wb:card:{nm_id}")
                    if isinstance(cached_card, dict) and cached_card:
                        nm_to_card[nm_id] = cached_card
                    else:
                        nm_ids_to_fetch.append(nm_id)
                # #region agent log
                agent_dbg_bc5cf5(
                    "D",
                    "order_sync_service.py:wb_enrich",
                    "wb content enrich plan",
                    {
                        "mp": marketplace.id,
                        "confirm": len(orders_new),
                        "nm_total": len(unique_nm_ids),
                        "nm_fetch": len(nm_ids_to_fetch),
                        "enrich": wb_enrich_content,
                    },
                )
                # #endregion
                # Без карточки WB ручной синк пишет нерабочий basket-18 и стирает размер.
                # Кэш выше подставляется сразу; в API ходим только за отсутствующими nm_id.
                if wb_enrich_content and nm_ids_to_fetch:
                    _WB_CONTENT_SLEEP = 2.0  # 1 req / 2s = 30 req/min на воркер
                    # Случайный сдвиг 0–4s, чтобы воркеры не шли в ногу
                    await asyncio.sleep(random.uniform(0, 4))
                    for idx, nm_id in enumerate(nm_ids_to_fetch):
                        OrderSyncService._check_auto_cancel(sync_source, marketplace.id)
                        _res = await client.get_product_card_content_api(nm_id)
                        nm_to_card[nm_id] = _res
                        if isinstance(_res, dict) and _res:
                            cache_set(f"wb:card:{nm_id}", _res, OrderSyncService._WB_CARD_CACHE_TTL)
                        if idx < len(nm_ids_to_fetch) - 1:
                            await asyncio.sleep(_WB_CONTENT_SLEEP)
                for mo in orders_new:
                    nm_id = (mo.metadata or {}).get("nm_id")
                    chrt_id = (mo.metadata or {}).get("chrt_id")
                    if mo.metadata is None:
                        mo.metadata = {}
                    prev: dict = {}
                    existing = order_repo.get_by_external_id(marketplace.id, mo.external_id)
                    if existing and isinstance(existing.extra_data, dict):
                        prev = existing.extra_data
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
                            prev_url = prev.get("product_image_url") if isinstance(prev.get("product_image_url"), str) else ""
                            # Угаданный CDN (basket-18 для больших nm_id) отдаёт 404.
                            # Уже сохранённое фото с Content API не подменяем.
                            if prev_url.startswith("http") and "basket-18.wbbasket.ru" not in prev_url:
                                mo.metadata["product_image_url"] = prev_url
                            else:
                                mo.metadata["product_image_url"] = WildberriesClient.build_product_image_url(nm_id) or ""
                        if not mo.metadata.get("size"):
                            prev_size = prev.get("size") if isinstance(prev.get("size"), str) else ""
                            if prev_size.strip():
                                mo.metadata["size"] = prev_size.strip()
                with_images = sum(1 for mo in orders_new if (mo.metadata or {}).get("product_image_url"))
                with_sizes = sum(1 for mo in orders_new if (mo.metadata or {}).get("size"))
                if orders_new:
                    logger.info(
                        f"WB product images: {with_images}/{len(orders_new)} orders got photo, "
                        f"sizes={with_sizes}"
                    )
                for mo in orders_new:
                    OrderSyncService._check_auto_cancel(sync_source, marketplace.id)
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
        elif marketplace.type == MarketplaceType.YANDEX:
            count += await OrderSyncService._sync_yandex_orders(
                marketplace, db, order_repo, api_key, sync_source,
            )
        else:
            logger.warning(f"Unknown marketplace type: {marketplace.type}")
            return 0

        OrderSyncService._check_auto_cancel(sync_source, marketplace.id)
        marketplace.update_sync_time()
        # #region agent log
        agent_dbg_bc5cf5(
            "A",
            "order_sync_service.py:commit",
            "commit sync",
            {"mp": marketplace.id, "count": count, "source": sync_source},
        )
        # #endregion
        db.commit()
        logger.info(
            "Synced %s orders for marketplace %s (source=%s)",
            count,
            marketplace.id,
            sync_source,
        )
        return count

    @staticmethod
    async def _attach_ozon_product_barcodes(client: OzonClient, orders: list) -> None:
        """Кладём выбранный ШК (с нуля, иначе OZN+SKU) в товары новых заказов Ozon."""
        offer_ids: list[str] = []
        for mo in orders:
            for product in (mo.metadata or {}).get("products") or []:
                offer_id = product.get("offer_id")
                if offer_id:
                    offer_ids.append(str(offer_id))
        if not offer_ids:
            return
        try:
            barcode_map = await client.get_product_barcodes(offer_ids)
        except Exception as exc:
            logger.warning("Ozon barcodes fetch failed: %s", exc)
            return
        for mo in orders:
            for product in (mo.metadata or {}).get("products") or []:
                offer_id = str(product.get("offer_id") or "")
                codes = barcode_map.get(offer_id) or []
                sku = product.get("sku")
                fallback = None
                if sku is not None and str(sku).strip():
                    try:
                        fallback = f"OZN{int(sku)}"
                    except (TypeError, ValueError):
                        fallback = f"OZN{sku}"
                chosen = choose_product_barcode(codes, fallback=fallback)
                if chosen:
                    product["barcode"] = chosen
                    product["barcodes"] = codes

    @staticmethod
    async def _sync_yandex_orders(
        marketplace: Marketplace,
        db: Session,
        order_repo: OrderRepository,
        api_key: str,
        sync_source: str,
    ) -> int:
        """Заказы только из отгрузок «Готова к отправке»."""
        if not marketplace.client_id:
            logger.warning("Yandex without campaign id, skipping sync")
            return 0
        count = 0
        async with YandexMarketClient(api_key=api_key, client_id=marketplace.client_id) as client:
            ready_orders, ready_ids = await client.fetch_ready_orders()
            for mo in ready_orders:
                OrderSyncService._check_auto_cancel(sync_source, marketplace.id)
                count += OrderSyncService._upsert_order(db, order_repo, marketplace, mo)
            open_orders = (
                db.query(Order)
                .filter(
                    Order.marketplace_id == marketplace.id,
                    Order.status.notin_(
                        [OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.COMPLETED]
                    ),
                    Order.collected_in_app.is_(False),
                )
                .all()
            )
            for existing in open_orders:
                if existing.external_id in ready_ids:
                    continue
                OrderSyncService._check_auto_cancel(sync_source, marketplace.id)
                remote_status = ""
                try:
                    remote = await client.get_order(marketplace.client_id, existing.external_id)
                    remote_status = str(remote.get("status") or "")
                except Exception as exc:
                    logger.warning(
                        "Yandex order %s status check failed: %s",
                        existing.external_id,
                        exc,
                    )
                if action_for_left_order(remote_status) == "cancel":
                    if order_repo.mark_cancelled_by_marketplace(marketplace.id, existing.external_id):
                        count += 1
                elif order_repo.mark_delivered_by_marketplace(marketplace.id, existing.external_id):
                    count += 1
        return count

    @staticmethod
    def _upsert_order(
        db: Session,
        order_repo: OrderRepository,
        marketplace: Marketplace,
        mo: MarketplaceOrder,
        *,
        skip_metadata_if_exists: bool = False,
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

        # Ozon: mo.status — смапленный внутренний (awaiting_packaging и awaiting_deliver → одно значение).
        # В marketplace_status храним сырой статус API из metadata, иначе фильтр вкладки «Сборка»
        # (awaiting_deliver) не совпадает с тем, что в БД.
        mp_status_for_db = mo.status
        if marketplace.type == MarketplaceType.OZON:
            raw = (mo.metadata or {}).get("status")
            if isinstance(raw, str) and raw.strip():
                mp_status_for_db = raw.strip()

        existing = order_repo.get_by_external_id(marketplace.id, mo.external_id)
        if existing:
            # Не перезаписывать статус, если заказ уже собран локально.
            # Ozon: остаётся в awaiting_deliver до приёмки на складе Ozon — синк не сбрасывает.
            # WB: supply API не вызывается, заказ остаётся confirm на WB — синк не сбрасывает
            # COMPLETED обратно в awaiting_packaging.
            status_to_set = order_status if existing.status != OrderStatus.COMPLETED else None
            metadata_to_set = None if skip_metadata_if_exists else mo.metadata
            order_repo.update_from_marketplace(
                existing,
                status=status_to_set,
                marketplace_status=mp_status_for_db,
                warehouse_id=warehouse_id,
                warehouse_name=mo.warehouse_name,
                metadata=metadata_to_set,
            )
            return 1

        try:
            order_repo.create(
                marketplace_id=marketplace.id,
                external_id=mo.external_id,
                posting_number=mo.posting_number,
                article=mo.article,
                product_name=mo.product_name,
                quantity=mo.quantity,
                warehouse_id=warehouse_id,
                warehouse_name=mo.warehouse_name,
                marketplace_status=mp_status_for_db,
                marketplace_created_at=mo.created_at,
                metadata=mo.metadata,
                status=order_status,
            )
        except IntegrityError:
            # Защита от гонки при параллельных sync: запись уже могла появиться
            # между get_by_external_id() и create().
            db.rollback()
            existing_after_race = order_repo.get_by_external_id(marketplace.id, mo.external_id)
            if existing_after_race:
                status_to_set = (
                    order_status if existing_after_race.status != OrderStatus.COMPLETED else None
                )
                metadata_to_set = None if skip_metadata_if_exists else mo.metadata
                order_repo.update_from_marketplace(
                    existing_after_race,
                    status=status_to_set,
                    marketplace_status=mp_status_for_db,
                    warehouse_id=warehouse_id,
                    warehouse_name=mo.warehouse_name,
                    metadata=metadata_to_set,
                )
            else:
                raise
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
