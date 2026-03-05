"""
Интеграция с Ozon Seller API
Документация: https://docs.ozon.ru/api/seller/

Основано на официальной документации и библиотеке ozon-seller
https://github.com/irenicaa/ozon-seller
"""
import json
from datetime import datetime, timedelta
from typing import Any, Optional

from app.core.exceptions import MarketplaceAPIException
from app.services.marketplace.base import (
    BaseMarketplaceClient,
    MarketplaceOrder,
    OrderStatus,
)
from app.utils.logger import logger


class OzonClient(BaseMarketplaceClient):
    """
    Клиент для работы с Ozon Seller API
    
    Endpoints:
    - POST /v3/posting/fbs/unfulfilled/list - Список необработанных отправлений
    - POST /v3/posting/fbs/get - Детали заказа + штрихкоды (upper_barcode, lower_barcode)
    - POST /v2/posting/fbs/package-label - Этикетка ФБС (PDF, стикер отправления)
    - POST /v3/posting/fbs/ship - Подтверждение отгрузки
    - POST /v1/warehouse/list - Список складов

    Штрихкод товара: Ozon НЕ даёт отдельный API для PDF штрихкода товара.
    - /v1/barcode/generate, /v1/barcode/add — для каталога (создание/привязка штрихкодов к товарам).
    - package-label — только этикетка ФБС (отправление).
    - Штрихкод товара берём из posting/fbs/get (barcodes.upper_barcode, products[].sku).
    
    Авторизация:
    - Header: Client-Id
    - Header: Api-Key
    """
    
    @property
    def base_url(self) -> str:
        """Базовый URL Ozon API"""
        return "https://api-seller.ozon.ru"
    
    @property
    def marketplace_name(self) -> str:
        """Название маркетплейса"""
        return "Ozon"
    
    def _get_headers(self) -> dict[str, str]:
        """
        Получение заголовков для Ozon API
        
        Согласно документации:
        - Client-Id: ID клиента из личного кабинета
        - Api-Key: API ключ с правами администратора
        """
        if not self.client_id:
            raise ValueError("Client ID is required for Ozon API")
        
        return {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }
    
    def _map_ozon_status_to_common(self, ozon_status: str) -> str:
        """
        Маппинг статусов Ozon в общий формат.
        Документация: docs.ozon.ru, Posting FBS statuses.
        
        Статусы Ozon FBS:
        - awaiting_packaging - Ожидает упаковки
        - awaiting_approve - Ожидает подтверждения
        - awaiting_deliver - Ожидает отгрузки
        - delivering - В доставке (скрываем)
        - delivered - Доставлен (скрываем)
        - cancelled - Отменён
        """
        status_mapping = {
            "awaiting_packaging": OrderStatus.AWAITING_PACKAGING.value,
            "awaiting_approve": OrderStatus.AWAITING_PACKAGING.value,
            "awaiting_deliver": OrderStatus.AWAITING_PACKAGING.value,
            "delivering": OrderStatus.COMPLETED.value,
            "delivered": OrderStatus.COMPLETED.value,
            "cancelled": OrderStatus.CANCELLED.value,
        }
        return status_mapping.get(ozon_status, ozon_status)
    
    def _parse_postings_to_orders(self, postings: list[dict[str, Any]]) -> list[MarketplaceOrder]:
        """Преобразование postings в MarketplaceOrder"""
        orders = []
        for posting in postings:
            products = posting.get("products", [])
            if not products:
                logger.warning(
                    f"Ozon posting {posting.get('posting_number')} has no products"
                )
                continue
            
            first_product = products[0]
            delivery_method = posting.get("delivery_method") or {}
            total_qty = sum(p.get("quantity", 1) for p in products)
            
            order = MarketplaceOrder(
                external_id=str(posting.get("order_id", "")),
                posting_number=posting.get("posting_number", ""),
                article=first_product.get("offer_id", ""),
                product_name=first_product.get("name", ""),
                quantity=total_qty,
                warehouse_name=delivery_method.get("warehouse"),
                status=self._map_ozon_status_to_common(posting.get("status", "")),
                created_at=self._parse_datetime(posting.get("in_process_at")),
                metadata={
                    "marketplace": "ozon",
                    "posting_number": posting.get("posting_number"),
                    "order_number": posting.get("order_number"),
                    "warehouse_id": delivery_method.get("warehouse_id"),
                    "is_express": posting.get("is_express", False),
                    "tracking_number": posting.get("tracking_number"),
                    "products": products,
                    "delivery_method": delivery_method,
                    "barcodes": posting.get("barcodes"),
                    "status": posting.get("status"),  # raw Ozon status для различения delivered/delivering
                },
            )
            orders.append(order)
        return orders
    
    async def get_orders(
        self,
        warehouse_id: Optional[str] = None,
        since: Optional[datetime] = None,
        to: Optional[datetime] = None,
        status: Optional[str] = None,
    ) -> list[MarketplaceOrder]:
        """
        Получение списка FBS заказов из Ozon
        
        Endpoint: POST /v3/posting/fbs/unfulfilled/list
        
        Args:
            warehouse_id: ID склада для фильтрации
            since: Начало периода
            to: Конец периода
            status: Статус (awaiting_deliver для ТЗ "Ожидают отгрузки")
            
        Returns:
            list[MarketplaceOrder]: Список заказов
        """
        return await self.get_orders_with_pagination(
            warehouse_id=warehouse_id,
            since=since,
            to=to,
            status=status,
            limit=1000,
        )[0]
    
    async def get_orders_awaiting_deliver(
        self,
        warehouse_id: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[list[MarketplaceOrder], bool]:
        """
        Получение заказов в статусе "Ожидают отгрузки"
        
        Согласно ТЗ: для вкладки "Сборка" показываем только эти заказы.
        
        Endpoint: POST /v3/posting/fbs/unfulfilled/list
        
        Args:
            warehouse_id: ID склада для фильтрации
            limit: Лимит записей (max 1000)
            offset: Смещение для пагинации
            
        Returns:
            tuple: (список заказов, has_next)
        """
        orders, has_next = await self.get_orders_with_pagination(
            warehouse_id=warehouse_id,
            status="awaiting_deliver",
            limit=limit,
            offset=offset,
        )
        return orders, has_next

    async def get_orders_delivered_or_delivering(
        self,
        limit: int = 1000,
        offset: int = 0,
        days_back: int = 30,
    ) -> tuple[list[MarketplaceOrder], bool]:
        """
        Получение заказов в статусе delivered или delivering.
        Используется при синхронизации: unfulfilled/list не возвращает доставленные,
        поэтому их нужно помечать DELIVERED (скрыть).
        Endpoint: POST /v3/posting/fbs/list
        Ozon API: PERIOD_IS_TOO_LONG при периоде >30 дней — days_back не более 30.
        """
        now = datetime.utcnow()
        period_from = now - timedelta(days=days_back)
        iso_format = "%Y-%m-%dT%H:%M:%S.000Z"
        # По док. irenicaa/ozon-seller: filter.since, filter.to (GetPostingFBSListFilter)
        filter_data: dict[str, Any] = {
            "since": period_from.strftime(iso_format),
            "to": now.strftime(iso_format),
        }
        request_body = {
            "dir": "asc",
            "filter": filter_data,
            "limit": min(max(limit, 1), 1000),
            "offset": offset,
            "with": {
                "analytics_data": False,
                "barcodes": False,
                "financial_data": False,
                "translit": False,
            },
        }
        logger.info(
            "Fetching delivered/delivering orders from Ozon (fbs/list)",
            extra={"filter": filter_data, "offset": offset},
        )
        try:
            response = await self._request(
                method="POST",
                endpoint="/v3/posting/fbs/list",
                json_data=request_body,
            )
            result = response.get("result", {})
            postings = result.get("postings", [])
            postings = [
                p for p in postings
                if p.get("status") in ("delivered", "delivering")
            ]
            has_next = len(postings) >= limit
            orders = self._parse_postings_to_orders(postings)
            logger.info(
                f"Received {len(orders)} delivered/delivering orders from Ozon",
                extra={"orders_count": len(orders)},
            )
            return orders, has_next
        except Exception as e:
            logger.warning(
                f"Could not fetch delivered orders from Ozon (fbs/list): {e}. "
                "Delivered orders may not be marked as completed.",
            )
            return [], False

    async def get_orders_with_pagination(
        self,
        warehouse_id: Optional[str] = None,
        since: Optional[datetime] = None,
        to: Optional[datetime] = None,
        status: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
        dir: str = "asc",
    ) -> tuple[list[MarketplaceOrder], bool]:
        """
        Получение FBS заказов с пагинацией
        
        Endpoint: POST /v3/posting/fbs/unfulfilled/list (официальная док. docs.ozon.ru)
        Список необработанных отправлений. Период — не больше 1 года.
        
        Фильтр: cutoff_from/cutoff_to (дедлайн сборки). cutoff_to в будущем — новые заказы.
        
        Args:
            warehouse_id: ID склада
            since, to: Период (по умолчанию 365 дней назад, to = +30 дней)
            status: Статус — фильтрация на нашей стороне (API не поддерживает)
            limit: Лимит (max 1000)
            offset: Смещение
            dir: asc | desc
            
        Returns:
            tuple: (список заказов, has_next)
        """
        now = datetime.utcnow()
        period_from = since or (now - timedelta(days=365))  # макс. 1 год по док. Ozon
        period_to = to or (now + timedelta(days=30))  # +30 дней: новые заказы с дедлайном в будущем
        iso_format = "%Y-%m-%dT%H:%M:%S.000Z"

        # cutoff_from/cutoff_to — фильтр по времени сборки (дедлайн). cutoff_to в будущем — новые заказы.
        filter_data: dict[str, Any] = {
            "cutoff_from": period_from.strftime(iso_format),
            "cutoff_to": period_to.strftime(iso_format),
        }
        
        request_body = {
            "dir": dir.lower() if dir else "asc",
            "filter": filter_data,
            "limit": min(max(limit, 1), 1000),
            "offset": offset,
            "with": {
                "analytics_data": False,
                "barcodes": False,
                "financial_data": False,
                "translit": False,
            },
        }
        
        logger.info(
            "Fetching FBS orders from Ozon (unfulfilled list)",
            extra={"filter": filter_data, "offset": offset},
        )
        
        try:
            response = await self._request(
                method="POST",
                endpoint="/v3/posting/fbs/unfulfilled/list",
                json_data=request_body,
            )
            
            result = response.get("result", {})
            postings = result.get("postings", [])
            # unfulfilled/list возвращает count, не has_next — считаем по количеству
            has_next = len(postings) >= limit
            
            # API не поддерживает filter.status и filter.warehouse_id — фильтруем на нашей стороне
            if status:
                postings = [p for p in postings if p.get("status") == status]
            if warehouse_id:
                try:
                    wh_id = int(warehouse_id)
                    postings = [
                        p for p in postings
                        if (p.get("delivery_method") or {}).get("warehouse_id") == wh_id
                    ]
                except ValueError:
                    logger.warning(f"Invalid warehouse_id: {warehouse_id}")
            
            logger.info(
                f"Received {len(postings)} orders from Ozon",
                extra={"orders_count": len(postings), "has_next": has_next},
            )
            
            orders = self._parse_postings_to_orders(postings)
            return orders, has_next
            
        except Exception as e:
            logger.error(
                "Failed to fetch orders from Ozon",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to fetch Ozon orders: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    async def get_posting_details(
        self,
        posting_number: str,
        with_barcodes: bool = True,
    ) -> dict[str, Any]:
        """
        Получение детальной информации о заказе
        
        Endpoint: POST /v3/posting/fbs/get
        
        Args:
            posting_number: Номер отправления
            with_barcodes: Включить штрихкоды (upper_barcode, lower_barcode)
            
        Returns:
            dict: Полные данные заказа включая barcodes для печати
        """
        request_body = {
            "posting_number": posting_number,
            "with": {
                "analytics_data": False,
                "barcodes": with_barcodes,
                "financial_data": False,
                "translit": False,
            }
        }
        
        logger.info(f"Fetching details for Ozon posting {posting_number}")
        
        try:
            response = await self._request(
                method="POST",
                endpoint="/v3/posting/fbs/get",
                json_data=request_body,
            )
            
            result = response.get("result", {})
            logger.info(f"Received details for posting {posting_number}")
            return result
            
        except Exception as e:
            logger.error(
                f"Failed to fetch Ozon posting details for {posting_number}",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to fetch posting details: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    async def get_order_label(self, posting_number: str) -> bytes:
        """
        Получение этикетки FBS заказа (PDF)
        
        Endpoint: POST /v2/posting/fbs/package-label
        
        Args:
            posting_number: Номер отправления
            
        Returns:
            bytes: PDF файл этикетки
        """
        request_body = {
            "posting_number": [posting_number]
        }
        
        logger.info(f"Fetching label for Ozon posting {posting_number}")
        
        try:
            content = await self._request_content(
                method="POST",
                endpoint="/v2/posting/fbs/package-label",
                json_data=request_body,
            )
            
            logger.info(
                f"Received label for posting {posting_number}",
                extra={"size_bytes": len(content)},
            )
            return content
            
        except MarketplaceAPIException:
            raise  # Сохраняем detail от Ozon API
        except Exception as e:
            logger.error(
                f"Failed to fetch label for Ozon posting {posting_number}",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to fetch Ozon label: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    async def ship_posting(
        self,
        posting_number: str,
        products: list[dict[str, Any]],
        mandatory_marks: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """
        Подтверждение отгрузки ("Собрано")
        
        Endpoint: POST /v3/posting/fbs/ship
        
        Args:
            posting_number: Номер отправления
            products: Список товаров [{"product_id": int, "quantity": int, "sku": int}]
            mandatory_marks: Коды маркировки (если требуется)
            
        Returns:
            dict: Результат ответа API
            
        Note:
            Для товаров без маркировки: exemplar_info с is_gtd_absent=True
        """
        packages_products = []
        
        for i, product in enumerate(products):
            product_id = product.get("product_id") or product.get("sku")
            quantity = product.get("quantity", 1)
            sku = product.get("sku", product_id)
            
            exemplar_info = []
            if mandatory_marks and i < len(mandatory_marks):
                exemplar_info.append({
                    "mandatory_mark": mandatory_marks[i],
                    "is_gtd_absent": False,
                })
            else:
                exemplar_info.append({
                    "is_gtd_absent": True,
                })
            
            packages_products.append({
                "product_id": product_id,
                "quantity": quantity,
                "exemplar_info": exemplar_info,
            })
        
        request_body = {
            "posting_number": posting_number,
            "packages": [{
                "products": packages_products
            }]
        }
        
        logger.info(f"Shipping Ozon posting {posting_number}")
        
        try:
            response = await self._request(
                method="POST",
                endpoint="/v3/posting/fbs/ship",
                json_data=request_body,
            )
            
            logger.info(f"Successfully shipped posting {posting_number}")
            return response
            
        except Exception as e:
            logger.error(
                f"Failed to ship Ozon posting {posting_number}",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to ship Ozon posting: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    async def get_product_images(
        self,
        offer_ids: Optional[list[str]] = None,
        product_ids: Optional[list[int]] = None,
        sku_to_article: Optional[dict[int, str]] = None,
    ) -> dict[str, str]:
        """
        Получение URL фото товаров.
        
        Endpoint: POST /v3/product/info/list (docs.ozon.ru)
        Пробует product_id (sku), затем offer_id.
        
        Args:
            offer_ids: Артикулы (offer_id)
            product_ids: ID товаров (sku из posting)
            sku_to_article: {sku: article} для маппинга при запросе по product_id
            
        Returns:
            dict: { article: image_url } — ключи всегда article для единообразия
        """
        result: dict[str, str] = {}
        if product_ids:
            result = await self._fetch_product_images_batch(
                "product_id", [int(x) for x in product_ids], sku_to_article
            )
        if not result and offer_ids:
            result = await self._fetch_product_images_batch("offer_id", offer_ids, None)
        return result

    async def _fetch_product_images_batch(
        self,
        req_key: str,
        ids: list,
        sku_to_article: Optional[dict[int, str]] = None,
    ) -> dict[str, str]:
        """Один запрос к product/info/list"""
        if not ids:
            return {}
        result: dict[str, str] = {}
        batch_size = 100
        for i in range(0, len(ids), batch_size):
            batch = ids[i : i + batch_size]
            try:
                req_val = batch
                logger.info(
                    "Fetching product images from Ozon",
                    extra={"key": req_key, "count": len(batch), "sample": batch[:3]},
                )
                response = await self._request(
                    method="POST",
                    endpoint="/v3/product/info/list",
                    json_data={req_key: req_val},
                )
                # Ozon: items на верхнем уровне ИЛИ result.items[]
                items = response.get("items")
                res = response.get("result")
                if items is None:
                    items = res.get("items", []) if isinstance(res, dict) else (res if isinstance(res, list) else [])
                items = items or []
                if not items:
                    logger.warning(
                        "Ozon product/info/list returned 0 items",
                        extra={
                            "response_keys": list(response.keys()),
                            "result_type": type(res).__name__ if res is not None else "None",
                            "result_sample": str(res)[:500] if res else None,
                            "request_key": req_key,
                            "request_sample": batch[:3],
                        },
                    )
                for item in items:
                    primary = item.get("primary_image")
                    url = ""
                    if isinstance(primary, str) and primary:
                        url = primary
                    elif isinstance(primary, dict):
                        url = primary.get("url") or primary.get("file_name") or ""
                    elif item.get("images"):
                        imgs = item["images"]
                        first = imgs[0] if imgs else ""
                        url = first if isinstance(first, str) else (first.get("url") or first.get("file_name") or "")
                    # Ключ результата — article (для единообразия с sync)
                    if req_key == "product_id" and sku_to_article:
                        pid = item.get("id")
                        if pid is not None:
                            map_key = sku_to_article.get(int(pid))
                            if map_key:
                                result[map_key] = url
                    else:
                        map_key = item.get("offer_id")
                        if map_key:
                            result[map_key] = url
                logger.info(
                    f"Got {len(result)} product images from Ozon",
                    extra={"fetched": len([u for u in result.values() if u])},
                )
            except Exception as e:
                logger.warning(
                    f"Failed to fetch product images for batch: {e}",
                    extra={"offer_ids": batch[:5]},
                )
        return result

    # Fallback: attribute_id 8229 — «Размер» (из неофициальных источников, может отличаться по категориям)
    OZON_SIZE_ATTRIBUTE_ID_FALLBACK = 8229

    @staticmethod
    def _parse_tctable_size(raw_val: Any) -> Optional[str]:
        """
        Парсит значение атрибута «Размер» от Ozon, когда оно приходит как tcTable (размерная сетка).
        Возвращает читаемую строку вместо сырого JSON.
        """
        if not raw_val:
            return None
        obj = raw_val
        if isinstance(raw_val, str):
            raw_val = raw_val.strip()
            if not raw_val or "tcTable" not in raw_val:
                return raw_val if raw_val and not raw_val.startswith("{") else None
            try:
                obj = json.loads(raw_val)
            except json.JSONDecodeError:
                return None
        if not isinstance(obj, dict):
            return str(obj) if obj else None
        content = obj.get("content")
        if not isinstance(content, list) or not content:
            return None
        for item in content:
            if not isinstance(item, dict) or item.get("widgetName") != "tcTable":
                continue
            table = item.get("table")
            if not isinstance(table, dict):
                continue
            title = table.get("title") or "Размерная сетка"
            body = table.get("body") or []
            for row in body:
                if not isinstance(row, dict):
                    continue
                data = row.get("data")
                if isinstance(data, list) and len(data) >= 2:
                    label = str(data[0] or "").lower()
                    vals = [str(v) for v in data[1:7] if v]
                    if "международный" in label and vals:
                        return f"{title}: {', '.join(vals)}"
                    if "российский" in label and vals:
                        return f"{title}: {', '.join(vals)}"
            return title
        return None

    async def _get_category_size_attribute_id(
        self,
        description_category_id: int,
        type_id: int,
    ) -> Optional[int]:
        """
        Получить attribute_id размера для категории через POST /v1/description-category/attribute.
        Ищет атрибут с именем «Размер» (без учёта регистра).
        """
        try:
            response = await self._request(
                method="POST",
                endpoint="/v1/description-category/attribute",
                json_data={
                    "type_id": type_id,
                    "description_category_id": description_category_id,
                },
            )
            attrs = response.get("result") or response.get("attributes") or []
            if not isinstance(attrs, list):
                attrs = []
            for a in attrs:
                name = (a.get("name") or a.get("title") or "").strip().lower()
                if "размер" in name:
                    aid = a.get("id") or a.get("attribute_id")
                    if aid is not None:
                        logger.info(f"Ozon category attr 'Размер' found: id={aid} (cat={description_category_id} type={type_id})")
                        return int(aid)
            logger.info(
                f"Ozon category attr 'Размер' not found: cat={description_category_id} type={type_id} "
                f"attrs_sample={[(a.get('name'), a.get('id')) for a in attrs[:5]]}",
            )
            return None
        except Exception as e:
            logger.warning(f"Ozon _get_category_size_attribute_id failed: {e}")
            return None

    async def get_product_sizes(
        self,
        offer_ids: Optional[list[str]] = None,
    ) -> dict[str, str]:
        """
        Получение размера товаров через Ozon Attributes API.
        Endpoint: POST /v4/product/info/attributes (ozon-api-client)
        Динамически определяет attribute_id размера через /v1/description-category/attribute.
        Returns: { offer_id: size }
        """
        if not offer_ids:
            return {}
        result: dict[str, str] = {}
        batch_size = 100
        # Кэш: (description_category_id, type_id) -> size_attribute_id
        size_attr_cache: dict[tuple[int, int], Optional[int]] = {}

        for i in range(0, len(offer_ids), batch_size):
            batch = offer_ids[i : i + batch_size]
            try:
                # docs.ozon.ru: GetProductAttributesV4 — filter, limit (1–1000), last_id
                response = await self._request(
                    method="POST",
                    endpoint="/v4/product/info/attributes",
                    json_data={
                        "filter": {
                            "offer_id": batch,
                            "visibility": "ALL",
                        },
                        "limit": max(1, min(len(batch), 1000)),
                    },
                )
                items = response.get("result") or response.get("items") or []
                if isinstance(items, dict):
                    items = items.get("items", [])
                if not isinstance(items, list):
                    items = []
                logger.info(
                    f"Ozon get_product_sizes: got {len(items)} items, response keys: {list(response.keys())}",
                )
                for item in items:
                    oid = item.get("offer_id")
                    if not oid:
                        continue
                    desc_cat = item.get("description_category_id")
                    type_id = item.get("type_id")
                    attrs = item.get("attributes") or []
                    size_attr_id = None
                    if desc_cat is not None and type_id is not None:
                        key = (int(desc_cat), int(type_id))
                        if key not in size_attr_cache:
                            size_attr_cache[key] = await self._get_category_size_attribute_id(
                                int(desc_cat), int(type_id)
                            )
                        size_attr_id = size_attr_cache[key]
                    if size_attr_id is None:
                        size_attr_id = self.OZON_SIZE_ATTRIBUTE_ID_FALLBACK
                    size_val = ""
                    for a in attrs:
                        aid = a.get("attribute_id") or a.get("id")
                        if aid is not None and int(aid) == size_attr_id:
                            vals = a.get("values") or []
                            raw = vals[0] if vals else None
                            if isinstance(raw, dict):
                                raw = raw.get("value", raw)
                            if raw is not None:
                                if isinstance(raw, dict):
                                    parsed = self._parse_tctable_size(raw)
                                    size_val = parsed or ""
                                else:
                                    s = str(raw).strip()
                                    parsed = self._parse_tctable_size(s)
                                    size_val = parsed if parsed else s
                            break
                    if size_val:
                        result[oid] = size_val
                        logger.info(f"Ozon size for {oid}: {size_val} (attr_id={size_attr_id})")
                    else:
                        attr_ids = [a.get("attribute_id") or a.get("id") for a in attrs]
                        logger.info(
                            f"Ozon no size for {oid}: desc_cat={desc_cat} type_id={type_id} "
                            f"size_attr_id={size_attr_id} product_attr_ids={attr_ids[:10]}",
                        )
            except Exception as e:
                logger.warning(
                    f"Ozon get_product_sizes failed: {e}",
                    extra={"batch_size": len(batch)},
                )
        return result
    
    async def get_warehouses(self) -> list[dict[str, Any]]:
        """
        Получение списка складов компании
        
        Endpoint: POST /v1/warehouse/list
        
        Returns:
            list: Список складов для настроек цветов
        """
        logger.info("Fetching Ozon warehouses list")
        
        try:
            response = await self._request(
                method="POST",
                endpoint="/v1/warehouse/list",
                json_data={},
            )
            
            warehouses = response.get("result", [])
            logger.info(f"Received {len(warehouses)} warehouses from Ozon")
            return warehouses
            
        except Exception as e:
            logger.error(
                "Failed to fetch Ozon warehouses",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to fetch Ozon warehouses: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    async def test_connection(self) -> bool:
        """
        Тестирование подключения к API Ozon
        
        Returns:
            bool: True если подключение успешно
        """
        logger.info("Testing Ozon API connection")
        
        try:
            # Простой запрос - список складов
            await self._request(
                method="POST",
                endpoint="/v1/warehouse/list",
                json_data={},
            )
            
            logger.info("✓ Ozon API connection successful")
            return True
            
        except Exception as e:
            logger.error(
                "✗ Ozon API connection failed",
                extra={"error": str(e)},
                exc_info=True,
            )
            return False
    
    async def update_order_status(
        self,
        posting_number: str,
        status: OrderStatus,
    ) -> bool:
        """
        Обновление статуса заказа в Ozon
        
        Note: Для подтверждения отгрузки используйте ship_posting()
        """
        if status == OrderStatus.COMPLETED:
            # Получить данные заказа и вызвать ship
            details = await self.get_posting_details(posting_number)
            products = details.get("products", [])
            products_data = [
                {
                    "product_id": p.get("sku"),
                    "sku": p.get("sku"),
                    "quantity": p.get("quantity", 1),
                }
                for p in products
            ]
            await self.ship_posting(posting_number, products_data)
            return True
        
        logger.warning(
            f"Direct status update to {status} not supported for Ozon. "
            "Use ship_posting() for confirming shipment."
        )
        return False
    
    def _parse_datetime(self, dt_string: Optional[str]) -> Optional[datetime]:
        """Парсинг datetime из строки ISO формата"""
        if not dt_string:
            return None
        try:
            return datetime.fromisoformat(dt_string.replace("Z", "+00:00"))
        except Exception:
            return None
