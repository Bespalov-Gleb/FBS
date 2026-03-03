"""
Интеграция с Wildberries API
Документация: https://dev.wildberries.ru/docs/openapi/orders-fbs
Content API: https://dev.wildberries.ru/docs/openapi/work-with-products

Основано на официальной документации Wildberries Marketplace API
"""
import asyncio
import base64
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from app.core.exceptions import MarketplaceAPIException
from app.services.marketplace.base import (
    BaseMarketplaceClient,
    MarketplaceOrder,
    OrderStatus,
)
from app.utils.logger import logger

CONTENT_API_BASE = "https://content-api.wildberries.ru"


class WildberriesClient(BaseMarketplaceClient):
    """
    Клиент для работы с Wildberries Marketplace API
    
    Endpoints (FBS Orders):
    - GET /api/v3/orders/new - Получение новых сборочных заданий
    - GET /api/v3/orders - Получение сборочных заданий
    - POST /api/v3/orders/status - Получение статусов заказов
    - POST /api/v3/orders/stickers - Получение стикеров
    - PATCH /api/marketplace/v3/supplies/{supplyId}/orders - Добавление в поставку
    - PUT /api/v3/orders/{orderId}/meta/sgtin - Добавление КИЗ
    
    Авторизация:
    - Header: Authorization (токен для Marketplace категории)
    """
    
    @property
    def base_url(self) -> str:
        """Базовый URL Wildberries Marketplace API"""
        return "https://marketplace-api.wildberries.ru"
    
    @property
    def marketplace_name(self) -> str:
        """Название маркетплейса"""
        return "Wildberries"
    
    def _get_headers(self) -> dict[str, str]:
        """
        Получение заголовков для Wildberries API
        
        Согласно документации:
        - Authorization: Bearer токен из личного кабинета (категория Marketplace)
        """
        return {
            "Authorization": self.api_key,  # Токен передается напрямую (уже содержит Bearer если нужно)
            "Content-Type": "application/json",
        }
    
    @staticmethod
    def build_product_image_url(nm_id: int | str) -> str:
        """
        Формирует URL изображения товара WB по nm_id (артикул WB).
        Использует CDN basket-*.wbbasket.ru — API не требуется.
        """
        urls = WildberriesClient.build_product_image_urls(nm_id)
        return urls[0] if urls else ""

    @staticmethod
    def build_product_image_urls(nm_id: int | str) -> list[str]:
        """
        Возвращает список URL для попытки загрузки изображения WB.
        Часть товаров использует 1.jpg вместо 1.webp, wb.ru вместо wbbasket.ru.
        Источник: https://ru.stackoverflow.com/questions/1548106/
        """
        try:
            nm = int(nm_id)
        except (ValueError, TypeError):
            return []
        if nm <= 0:
            return []
        vol = nm // 100000
        part = nm // 1000
        if vol <= 143:
            host = "01"
        elif vol <= 287:
            host = "02"
        elif vol <= 431:
            host = "03"
        elif vol <= 719:
            host = "04"
        elif vol <= 1007:
            host = "05"
        elif vol <= 1061:
            host = "06"
        elif vol <= 1115:
            host = "07"
        elif vol <= 1169:
            host = "08"
        elif vol <= 1313:
            host = "09"
        elif vol <= 1601:
            host = "10"
        elif vol <= 1655:
            host = "11"
        elif vol <= 1919:
            host = "12"
        elif vol <= 2045:
            host = "13"
        elif vol <= 2189:
            host = "14"
        elif vol <= 2405:
            host = "15"
        elif vol <= 2621:
            host = "16"
        elif vol <= 2837:
            host = "17"
        else:
            host = "18"
        base_wbbasket = f"https://basket-{host}.wbbasket.ru/vol{vol}/part{part}/{nm}/images/big"
        base_wb = f"https://basket-{host}.wb.ru/vol{vol}/part{part}/{nm}/images/big"
        # Приоритет: webp на wbbasket, затем jpg, затем wb.ru
        return [
            f"{base_wbbasket}/1.webp",
            f"{base_wbbasket}/1.jpg",
            f"{base_wb}/1.webp",
            f"{base_wb}/1.jpg",
        ]

    async def get_product_card_content_api(self, nm_id: int | str) -> Optional[dict]:
        """
        Получить карточку товара через Content API WB (для фото и размера).
        Требует токен с категорией «Контент».
        """
        try:
            nm = int(nm_id)
        except (ValueError, TypeError):
            return None
        if nm <= 0:
            return None
        url = f"{CONTENT_API_BASE}/content/v2/get/cards/list"
        body = {
            "settings": {
                "cursor": {"limit": 10},
                "filter": {
                    "textSearch": str(nm),
                    "allowedCategoriesOnly": True,
                    "withPhoto": -1,
                },
            }
        }
        auth = self.api_key
        if auth and not auth.lower().startswith("bearer "):
            auth = f"Bearer {auth}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    url,
                    json=body,
                    headers={
                        "Authorization": auth,
                        "Content-Type": "application/json",
                    },
                )
                if r.status_code != 200:
                    return None
                data = r.json()
        except Exception:
            return None
        cards = data.get("cards") or []
        return cards[0] if cards else None

    async def get_product_image_url_content_api(self, nm_id: int | str) -> str:
        """URL изображения товара через Content API."""
        card = await self.get_product_card_content_api(nm_id)
        if not card:
            return ""
        photos = card.get("photos") or card.get("mediaFiles") or []
        if not photos:
            return ""
        first = photos[0]
        if isinstance(first, str) and first.startswith("http"):
            return first
        if isinstance(first, dict):
            url = (
                first.get("big")
                or first.get("square")
                or first.get("c516x688")
                or first.get("url")
            )
            if isinstance(url, str) and url.startswith("http"):
                return url
        return ""

    def _extract_size_from_card(self, card: dict, chrt_id: Optional[int] = None) -> str:
        """
        Извлечь размер из карточки товара по chrt_id.
        Документация WB Content API: sizes[] с полями chrtId, techSize, origName.
        Поддержка вариантов: chrtID, chrtId, chrt_id (snake_case).
        """
        sizes = card.get("sizes") or []
        for s in sizes:
            sid = s.get("chrtID") or s.get("chrtId") or s.get("chrt_id")
            if chrt_id is not None and sid == chrt_id:
                return str(s.get("techSize") or s.get("origName") or "")
        if sizes and chrt_id is None:
            return str(sizes[0].get("techSize") or sizes[0].get("origName") or "")
        return ""

    def _map_wb_status_to_common(self, supplier_status: str) -> str:
        """
        Маппинг статусов Wildberries в общий формат
        
        Статусы supplierStatus в WB:
        - new - Новый заказ
        - confirm - В сборке (добавлен в поставку)
        - complete - В доставке (поставка передана)
        - cancel - Отменен продавцом
        """
        status_mapping = {
            "new": OrderStatus.AWAITING_PACKAGING.value,
            "confirm": OrderStatus.PACKAGING.value,
            "complete": OrderStatus.COMPLETED.value,
            "cancel": OrderStatus.CANCELLED.value,
        }
        return status_mapping.get(supplier_status, supplier_status)
    
    async def get_orders(
        self,
        warehouse_id: Optional[str] = None,
        since: Optional[datetime] = None,
        to: Optional[datetime] = None,
    ) -> list[MarketplaceOrder]:
        """
        Получение списка новых сборочных заданий FBS из Wildberries
        
        Endpoint: GET /api/v3/orders/new
        
        Возвращает список всех новых сборочных заданий (assembly orders).
        
        Returns:
            list[MarketplaceOrder]: Список заказов
        """
        return await self.get_new_orders()
    
    async def get_new_orders(self) -> list[MarketplaceOrder]:
        """
        Получение новых сборочных заданий
        
        Endpoint: GET /api/v3/orders/new
        
        Returns:
            list[MarketplaceOrder]: Список новых заказов (статус new)
        """
        logger.info("Fetching new FBS orders from Wildberries")
        
        try:
            response = await self._request(
                method="GET",
                endpoint="/api/v3/orders/new",
            )
            
            return self._parse_orders_response(response)
            
        except Exception as e:
            logger.error(
                "Failed to fetch new orders from Wildberries",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to fetch Wildberries new orders: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    async def get_orders_by_status(
        self,
        limit: int = 1000,
        next_cursor: int = 0,
        date_from: Optional[int] = None,
        date_to: Optional[int] = None,
    ) -> tuple[list[MarketplaceOrder], int]:
        """
        Получение сборочных заданий с пагинацией
        
        Endpoint: GET /api/v3/orders
        
        Args:
            limit: Лимит записей (1-1000, по умолчанию 1000)
            next_cursor: Курсор для пагинации (начинать с 0)
            date_from: Начало периода (Unix timestamp)
            date_to: Конец периода (Unix timestamp)
            
        Returns:
            tuple: (список заказов, следующий курсор)
            
        Note:
            Возвращает заказы без текущего статуса.
            Период максимум 30 дней за запрос.
        """
        params = {
            "limit": min(max(limit, 1), 1000),
            "next": next_cursor,
        }
        
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to
        
        logger.info(
            "Fetching FBS orders with pagination",
            extra={"limit": params["limit"], "next": next_cursor},
        )
        
        try:
            response = await self._request(
                method="GET",
                endpoint="/api/v3/orders",
                params=params,
            )
            
            orders = self._parse_orders_response(response)
            next_cursor = response.get("next", 0)
            
            logger.info(
                f"Received {len(orders)} orders, next cursor: {next_cursor}",
                extra={"orders_count": len(orders), "next_cursor": next_cursor},
            )
            
            return orders, next_cursor
            
        except Exception as e:
            logger.error(
                "Failed to fetch orders from Wildberries",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to fetch Wildberries orders: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    async def get_orders_in_assembly(
        self,
        days_back: int = 14,
        limit_per_request: int = 500,
    ) -> tuple[list[MarketplaceOrder], dict[str, str], set[str]]:
        """
        Получение заказов для вкладки «Сборка»: new + confirm.
        
        new = ещё не в поставке (заказ пришёл, но WB создаёт новую поставку каждый раз).
        confirm = уже в поставке. Показываем оба — чтобы заказы подтягивались сразу.
        GET /api/v3/orders не возвращает статус — вызываем POST /api/v3/orders/status.
        
        Returns:
            tuple: (orders, status_updates, all_external_ids)
            - orders: заказы с supplierStatus in ("new", "confirm")
            - status_updates: {external_id: "complete"|"cancel"} для complete/cancel
            - all_external_ids: все external_id из API (для _mark_cancelled)
        """
        now = datetime.utcnow()
        date_from = int((now - timedelta(days=min(days_back, 30))).timestamp())
        date_to = int(now.timestamp())
        
        result: list[MarketplaceOrder] = []
        status_updates: dict[str, str] = {}
        all_external_ids: set[str] = set()
        next_cursor = 0
        
        while True:
            orders_batch, next_cursor = await self.get_orders_by_status(
                limit=limit_per_request,
                next_cursor=next_cursor,
                date_from=date_from,
                date_to=date_to,
            )
            if not orders_batch:
                break
            
            order_ids = []
            for mo in orders_batch:
                all_external_ids.add(mo.external_id)
                try:
                    order_ids.append(int(mo.external_id))
                except (ValueError, TypeError):
                    pass
            
            if not order_ids:
                break
            
            statuses = await self.get_orders_statuses(order_ids)
            
            for mo in orders_batch:
                try:
                    oid = int(mo.external_id)
                except (ValueError, TypeError):
                    continue
                st = statuses.get(oid)
                supplier_status = (st or {}).get("supplier_status") if st else None
                if supplier_status in ("new", "confirm"):
                    # new и confirm — показываем в «Сборка» (заказ не подтягивался, т.к. раньше new не показывали)
                    if mo.metadata is None:
                        mo.metadata = {}
                    mo.metadata["supplierStatus"] = supplier_status
                    mo.status = self._map_wb_status_to_common(supplier_status)
                    result.append(mo)
                elif supplier_status in ("complete", "cancel"):
                    status_updates[mo.external_id] = supplier_status
            
            if next_cursor == 0:
                break
        
        logger.info(f"WB: got {len(result)} orders in assembly (new+confirm), {len(status_updates)} to update (complete/cancel)")
        return result, status_updates, all_external_ids
    
    async def get_orders_statuses(
        self,
        order_ids: list[int],
    ) -> dict[int, dict[str, str]]:
        """
        Получение статусов сборочных заданий
        
        Endpoint: POST /api/v3/orders/status
        
        Args:
            order_ids: Список ID сборочных заданий (1-1000)
            
        Returns:
            dict: {order_id: {"supplierStatus": "...", "wbStatus": "..."}}
            
        Note:
            supplierStatus: new, confirm, complete, cancel
            wbStatus: waiting, sorted, sold, canceled, etc.
        """
        if not order_ids:
            return {}
        
        if len(order_ids) > 1000:
            logger.warning(f"Too many order IDs: {len(order_ids)}, limiting to 1000")
            order_ids = order_ids[:1000]
        
        request_body = {
            "orders": order_ids
        }
        
        logger.info(
            f"Fetching statuses for {len(order_ids)} orders",
        )
        
        try:
            response = await self._request(
                method="POST",
                endpoint="/api/v3/orders/status",
                json_data=request_body,
            )
            
            # Парсинг ответа
            orders_data = response.get("orders", [])
            statuses = {}
            
            for order_data in orders_data:
                order_id = order_data.get("id")
                if order_id:
                    statuses[order_id] = {
                        "supplier_status": order_data.get("supplierStatus"),
                        "wb_status": order_data.get("wbStatus"),
                    }
            
            logger.info(f"Received statuses for {len(statuses)} orders")
            return statuses
            
        except Exception as e:
            logger.error(
                "Failed to fetch order statuses",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to fetch order statuses: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    def _parse_orders_response(self, response: dict[str, Any]) -> list[MarketplaceOrder]:
        """
        Парсинг ответа с заказами в унифицированный формат
        
        Args:
            response: Ответ от API
            
        Returns:
            list[MarketplaceOrder]: Список заказов
        """
        orders_data = response.get("orders", [])
        
        logger.debug(
            f"Parsing {len(orders_data)} orders from response",
            extra={"orders_count": len(orders_data)},
        )
        
        orders = []
        for order_data in orders_data:
            # Маппинг полей согласно документации WB API
            order = MarketplaceOrder(
                external_id=str(order_data.get("id", "")),  # id сборочного задания
                posting_number=order_data.get("rid", ""),  # rid - уникальный идентификатор
                article=order_data.get("article", ""),  # Артикул продавца
                product_name=order_data.get("article", "") or f"NM {order_data.get('nmId', '')}",  # WB API не возвращает название — используем артикул; fallback на nmId
                quantity=1,  # В WB каждое сборочное задание = 1 товар
                warehouse_name=", ".join(order_data.get("offices", [])),  # Склады
                status=self._map_wb_status_to_common(
                    order_data.get("supplierStatus", "new")
                ),
                created_at=self._parse_datetime(order_data.get("createdAt")),
                metadata={
                    "marketplace": "wildberries",
                    "supplierStatus": order_data.get("supplierStatus", "new"),
                    "order_uid": order_data.get("orderUid"),  # Уникальный идентификатор заказа
                    "supply_id": order_data.get("supplyId"),  # ID поставки (если есть)
                    "warehouse_id": order_data.get("warehouseId"),
                    "office_id": order_data.get("officeId"),
                    "nm_id": order_data.get("nmId"),  # Артикул WB
                    "chrt_id": order_data.get("chrtId"),  # ID характеристики товара
                    "color_code": order_data.get("colorCode"),
                    "price": order_data.get("price"),  # Цена без скидки (копейки)
                    "final_price": order_data.get("finalPrice"),  # Цена со скидкой
                    "scan_price": order_data.get("scanPrice"),
                    "converted_price": order_data.get("convertedPrice"),
                    "currency_code": order_data.get("currencyCode"),
                    "delivery_type": order_data.get("deliveryType"),  # fbs
                    "skus": order_data.get("skus", []),  # Баркоды
                    "required_meta": order_data.get("requiredMeta", []),  # Обязательные метаданные
                    "optional_meta": order_data.get("optionalMeta", []),  # Опциональные метаданные
                    "address": order_data.get("address"),  # Адрес доставки
                    "ddate": order_data.get("ddate"),  # Дата доставки до клиента
                    "seller_date": order_data.get("sellerDate"),  # Дата доставки до WB
                    "comment": order_data.get("comment"),  # Комментарий покупателя
                    "is_zero_order": order_data.get("isZeroOrder", False),
                    "is_b2b": order_data.get("options", {}).get("isB2b", False),
                },
            )
            orders.append(order)
        
        return orders
    
    async def get_order_label(
        self,
        order_id: str,
        sticker_type: str = "svg",
        width: int = 58,
        height: int = 40,
    ) -> bytes:
        """
        Получение стикера сборочного задания
        
        Endpoint: POST /api/v3/orders/stickers
        
        Args:
            order_id: ID сборочного задания
            sticker_type: Формат стикера (svg, zplv, zplh, png)
            width: Ширина (58 или 40)
            height: Высота (40 или 30)
            
        Returns:
            bytes: Данные стикера
        """
        request_body = {
            "orders": [int(order_id)]
        }
        
        params = {
            "type": sticker_type,
            "width": width,
            "height": height,
        }
        
        logger.info(
            f"Fetching sticker for WB order {order_id}",
            extra={
                "order_id": order_id,
                "type": sticker_type,
            },
        )
        
        try:
            response = await self._request(
                method="POST",
                endpoint="/api/v3/orders/stickers",
                params=params,
                json_data=request_body,
            )
            
            # Ответ содержит массив стикеров
            stickers = response.get("stickers", [])
            if not stickers:
                raise MarketplaceAPIException(
                    message=f"No sticker found for order {order_id}",
                    marketplace=self.marketplace_name,
                    detail="Стикер ещё не сформирован WB. Подтвердите заказ в личном кабинете или подождите.",
                )
            
            # Возвращаем file (Base64 encoded) первого стикера
            sticker_data = stickers[0].get("file", "")
            return base64.b64decode(sticker_data) if sticker_data else b""
            
        except Exception as e:
            logger.error(
                f"Failed to fetch sticker for WB order {order_id}",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to fetch Wildberries sticker: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    async def add_kiz_code(self, order_id: str, kiz_code: str) -> bool:
        """
        Добавление КИЗ (код маркировки) к сборочному заданию
        
        Endpoint: PUT /api/v3/orders/{orderId}/meta/sgtin
        
        Используется для товаров, требующих маркировку Честный ЗНАК.
        
        Args:
            order_id: ID сборочного задания
            kiz_code: Код маркировки (Data Matrix)
            
        Returns:
            bool: True если успешно
        """
        request_body = {
            "sgtins": [kiz_code]
        }
        
        logger.info(
            f"Adding КИЗ code to WB order {order_id}",
        )
        
        try:
            await self._request(
                method="PUT",
                endpoint=f"/api/v3/orders/{order_id}/meta/sgtin",
                json_data=request_body,
            )
            
            logger.info(f"Successfully added КИЗ to WB order {order_id}")
            return True
            
        except Exception as e:
            logger.error(
                f"Failed to add КИЗ to WB order {order_id}",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to add КИЗ: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    async def add_uin_code(self, order_id: str, uin: str) -> bool:
        """
        Добавление UIN (уникальный идентификационный номер) к сборочному заданию
        
        Endpoint: PUT /api/v3/orders/{orderId}/meta/uin
        
        Args:
            order_id: ID сборочного задания
            uin: Уникальный идентификационный номер
            
        Returns:
            bool: True если успешно
        """
        return await self._add_order_meta(order_id, "uin", {"uin": uin})
    
    async def add_imei_code(self, order_id: str, imei: str) -> bool:
        """
        Добавление IMEI к сборочному заданию
        
        Endpoint: PUT /api/v3/orders/{orderId}/meta/imei
        
        Args:
            order_id: ID сборочного задания
            imei: IMEI код (15 цифр)
            
        Returns:
            bool: True если успешно
        """
        return await self._add_order_meta(order_id, "imei", {"imei": imei})
    
    async def add_gtin_code(self, order_id: str, gtin: str) -> bool:
        """
        Добавление GTIN к сборочному заданию
        
        Endpoint: PUT /api/v3/orders/{orderId}/meta/gtin
        
        Args:
            order_id: ID сборочного задания
            gtin: GTIN код (глобальный идентификатор товара)
            
        Returns:
            bool: True если успешно
        """
        return await self._add_order_meta(order_id, "gtin", {"gtin": gtin})
    
    async def add_expiration_date(self, order_id: str, expiration: str) -> bool:
        """
        Добавление срока годности к сборочному заданию
        
        Endpoint: PUT /api/v3/orders/{orderId}/meta/expiration
        
        Args:
            order_id: ID сборочного задания
            expiration: Срок годности в формате DD.MM.YYYY (например 12.09.2030)
            
        Returns:
            bool: True если успешно
        """
        return await self._add_order_meta(order_id, "expiration", {"expiration": expiration})
    
    async def _add_order_meta(
        self,
        order_id: str,
        meta_type: str,
        request_body: dict[str, Any],
    ) -> bool:
        """
        Вспомогательный метод для добавления метаданных к заказу
        
        Args:
            order_id: ID сборочного задания
            meta_type: Тип метаданных (uin, imei, gtin, expiration)
            request_body: Тело запроса
        """
        logger.info(f"Adding {meta_type} to WB order {order_id}")
        
        try:
            await self._request(
                method="PUT",
                endpoint=f"/api/v3/orders/{order_id}/meta/{meta_type}",
                json_data=request_body,
            )
            
            logger.info(f"Successfully added {meta_type} to WB order {order_id}")
            return True
            
        except Exception as e:
            logger.error(
                f"Failed to add {meta_type} to WB order {order_id}",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to add {meta_type}: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    async def update_order_status(
        self,
        order_id: str,
        status: OrderStatus,
    ) -> bool:
        """
        Обновление статуса заказа
        
        Note: В Wildberries статусы меняются через процесс:
        1. new -> confirm: добавление в поставку (supply)
        2. confirm -> complete: передача поставки в доставку
        3. cancel: отмена заказа
        
        Args:
            order_id: ID сборочного задания
            status: Новый статус
            
        Returns:
            bool: True если успешно
        """
        if status == OrderStatus.CANCELLED:
            return await self._cancel_order(order_id)
        
        logger.warning(
            f"Direct status update to {status} is not supported for WB orders. "
            "Use supply management endpoints instead."
        )
        return False
    
    async def _cancel_order(self, order_id: str) -> bool:
        """
        Отмена сборочного задания
        
        Endpoint: PATCH /api/v3/orders/{orderId}/cancel
        """
        logger.info(f"Cancelling WB order {order_id}")
        
        try:
            await self._request(
                method="PATCH",
                endpoint=f"/api/v3/orders/{order_id}/cancel",
            )
            
            logger.info(f"Successfully cancelled WB order {order_id}")
            return True
            
        except Exception as e:
            logger.error(
                f"Failed to cancel WB order {order_id}",
                extra={"error": str(e)},
                exc_info=True,
            )
            return False
    
    # ========== Управление поставками (Supplies) ==========
    
    async def create_supply(self, name: str) -> str:
        """
        Создание новой поставки
        
        Endpoint: POST /api/v3/supplies
        
        Args:
            name: Название поставки
            
        Returns:
            str: ID созданной поставки
            
        Note:
            Поставка группирует сборочные задания для передачи на склад WB.
        """
        request_body = {
            "name": name
        }
        
        logger.info(f"Creating new supply: {name}")
        
        try:
            response = await self._request(
                method="POST",
                endpoint="/api/v3/supplies",
                json_data=request_body,
            )
            
            supply_id = response.get("id", "")
            logger.info(f"Created supply {supply_id}")
            
            return supply_id
            
        except Exception as e:
            logger.error(
                f"Failed to create supply",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to create supply: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    async def add_orders_to_supply(
        self,
        supply_id: str,
        order_ids: list[int],
    ) -> bool:
        """
        Добавление сборочных заданий в поставку
        
        Endpoint: PATCH /api/marketplace/v3/supplies/{supplyId}/orders
        
        Args:
            supply_id: ID поставки
            order_ids: Список ID сборочных заданий
            
        Returns:
            bool: True если успешно
            
        Note:
            При добавлении заказ переходит из статуса new в confirm (в сборке).
        """
        if not order_ids:
            logger.warning("Empty order_ids list provided")
            return False
        
        request_body = {
            "orders": order_ids
        }
        
        logger.info(
            f"Adding {len(order_ids)} orders to supply {supply_id}",
        )
        
        try:
            await self._request(
                method="PATCH",
                endpoint=f"/api/marketplace/v3/supplies/{supply_id}/orders",
                json_data=request_body,
            )
            
            logger.info(
                f"Successfully added {len(order_ids)} orders to supply {supply_id}"
            )
            return True
            
        except Exception as e:
            logger.error(
                f"Failed to add orders to supply {supply_id}",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to add orders to supply: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    async def deliver_supply(self, supply_id: str) -> bool:
        """
        Передача поставки в доставку
        
        Endpoint: PATCH /api/v3/supplies/{supplyId}/deliver
        
        Args:
            supply_id: ID поставки
            
        Returns:
            bool: True если успешно
            
        Note:
            При передаче все заказы в поставке переходят из статуса confirm
            в complete (в доставке).
        """
        logger.info(f"Delivering supply {supply_id}")
        
        try:
            await self._request(
                method="PATCH",
                endpoint=f"/api/v3/supplies/{supply_id}/deliver",
            )
            
            logger.info(f"Successfully delivered supply {supply_id}")
            return True
            
        except Exception as e:
            logger.error(
                f"Failed to deliver supply {supply_id}",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to deliver supply: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    async def get_supply_barcode(self, supply_id: str) -> dict[str, Any]:
        """
        Получение QR кода поставки
        
        Endpoint: GET /api/v3/supplies/{supplyId}/barcode
        
        Args:
            supply_id: ID поставки
            
        Returns:
            dict: {"barcode": "...", "file": "base64..."} - SVG QR код
            
        Note:
            QR код печатается на коробке поставки для приемки на складе WB.
        """
        logger.info(f"Fetching barcode for supply {supply_id}")
        
        try:
            response = await self._request(
                method="GET",
                endpoint=f"/api/v3/supplies/{supply_id}/barcode",
                params={"type": "svg"},  # Формат SVG
            )
            
            logger.info(f"Received barcode for supply {supply_id}")
            return response
            
        except Exception as e:
            logger.error(
                f"Failed to fetch barcode for supply {supply_id}",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to fetch supply barcode: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    async def get_supplies_list(self, limit: int = 1000, next_cursor: int = 0) -> tuple[list[dict[str, Any]], int]:
        """
        Получение списка поставок
        
        Endpoint: GET /api/v3/supplies
        
        Args:
            limit: Лимит записей (1-1000)
            next_cursor: Курсор для пагинации
            
        Returns:
            tuple: (список поставок, следующий курсор)
        """
        params = {
            "limit": min(max(limit, 1), 1000),
            "next": next_cursor,
        }
        
        logger.info("Fetching supplies list")
        
        try:
            response = await self._request(
                method="GET",
                endpoint="/api/v3/supplies",
                params=params,
            )
            
            supplies = response.get("supplies", [])
            next_cursor = response.get("next", 0)
            
            logger.info(
                f"Received {len(supplies)} supplies",
                extra={"supplies_count": len(supplies)},
            )
            
            return supplies, next_cursor
            
        except Exception as e:
            logger.error(
                "Failed to fetch supplies list",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to fetch supplies list: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    async def get_supply_details(self, supply_id: str) -> dict[str, Any]:
        """
        Получение детальной информации о поставке
        
        Endpoint: GET /api/v3/supplies/{supplyId}
        
        Args:
            supply_id: ID поставки
            
        Returns:
            dict: Информация о поставке
        """
        logger.info(f"Fetching details for supply {supply_id}")
        
        try:
            response = await self._request(
                method="GET",
                endpoint=f"/api/v3/supplies/{supply_id}",
            )
            
            return response
            
        except Exception as e:
            logger.error(
                f"Failed to fetch supply details for {supply_id}",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to fetch supply details: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    async def delete_supply(self, supply_id: str) -> bool:
        """
        Удаление поставки
        
        Endpoint: DELETE /api/v3/supplies/{supplyId}
        
        Args:
            supply_id: ID поставки
            
        Returns:
            bool: True если успешно
            
        Note:
            Можно удалить только поставку, которая еще не передана в доставку.
        """
        logger.info(f"Deleting supply {supply_id}")
        
        try:
            await self._request(
                method="DELETE",
                endpoint=f"/api/v3/supplies/{supply_id}",
            )
            
            logger.info(f"Successfully deleted supply {supply_id}")
            return True
            
        except Exception as e:
            logger.error(
                f"Failed to delete supply {supply_id}",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to delete supply: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    # ========== Работа с метаданными ==========
    
    async def get_orders_metadata(
        self,
        order_ids: list[int],
    ) -> dict[int, dict[str, Any]]:
        """
        Получение метаданных сборочных заданий
        
        Endpoint: POST /api/marketplace/v3/orders/meta
        
        Args:
            order_ids: Список ID сборочных заданий (до 100)
            
        Returns:
            dict: {order_id: {"imei": {...}, "uin": {...}, "sgtin": {...}, ...}}
            
        Note:
            Возвращает все метаданные: КИЗ, UIN, IMEI, GTIN, сроки годности и др.
        """
        if not order_ids:
            return {}
        
        if len(order_ids) > 100:
            logger.warning(f"Too many order IDs: {len(order_ids)}, limiting to 100")
            order_ids = order_ids[:100]
        
        request_body = {
            "orders": order_ids
        }
        
        logger.info(f"Fetching metadata for {len(order_ids)} orders")
        
        try:
            response = await self._request(
                method="POST",
                endpoint="/api/marketplace/v3/orders/meta",
                json_data=request_body,
            )
            
            # Парсинг ответа
            orders_data = response.get("orders", [])
            metadata = {}
            
            for order_data in orders_data:
                order_id = order_data.get("id")
                if order_id:
                    metadata[order_id] = order_data.get("meta", {})
            
            logger.info(f"Received metadata for {len(metadata)} orders")
            return metadata
            
        except Exception as e:
            logger.error(
                "Failed to fetch orders metadata",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to fetch orders metadata: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    async def delete_order_metadata(
        self,
        order_id: int,
        key: str,
    ) -> bool:
        """
        Удаление метаданных сборочного задания
        
        Endpoint: DELETE /api/v3/orders/{orderId}/meta
        
        Args:
            order_id: ID сборочного задания
            key: Ключ метаданных (imei, uin, gtin, sgtin, customsDeclaration)
            
        Returns:
            bool: True если успешно
        """
        params = {"key": key}
        
        logger.info(f"Deleting metadata {key} for order {order_id}")
        
        try:
            await self._request(
                method="DELETE",
                endpoint=f"/api/v3/orders/{order_id}/meta",
                params=params,
            )
            
            logger.info(f"Successfully deleted metadata {key} for order {order_id}")
            return True
            
        except Exception as e:
            logger.error(
                f"Failed to delete metadata for order {order_id}",
                extra={"error": str(e), "key": key},
                exc_info=True,
            )
            return False
    
    async def get_warehouses(self) -> list[dict[str, Any]]:
        """
        Получение списка складов из заказов.
        
        WB Marketplace API не имеет отдельного endpoint для складов.
        Извлекаем уникальные warehouse_id из заказов.
        
        Returns:
            list: Список складов [{"warehouse_id": ..., "name": ...}]
        """
        logger.info("Fetching warehouses from Wildberries orders")
        
        try:
            orders, _ = await self.get_orders_by_status(limit=500)
            seen: dict[str, str] = {}
            for order in orders:
                wh_id = order.metadata.get("warehouse_id") if order.metadata else None
                if wh_id is not None:
                    wh_id_str = str(wh_id)
                    if wh_id_str not in seen:
                        seen[wh_id_str] = order.warehouse_name or f"Склад {wh_id}"
            
            warehouses = [
                {"warehouse_id": wh_id, "name": name}
                for wh_id, name in seen.items()
            ]
            logger.info(f"Extracted {len(warehouses)} warehouses from WB orders")
            return warehouses
            
        except Exception as e:
            logger.error(
                "Failed to fetch WB warehouses from orders",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"Failed to fetch Wildberries warehouses: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    # ========== Утилиты ==========
    
    async def test_connection(self) -> bool:
        """
        Тестирование подключения к API Wildberries
        
        Выполняет простой запрос для проверки валидности токена.
        
        Returns:
            bool: True если подключение успешно
        """
        logger.info("Testing Wildberries API connection")
        
        try:
            # Простой запрос - получение новых заказов с лимитом 1
            await self._request(
                method="GET",
                endpoint="/api/v3/orders/new",
            )
            
            logger.info("✓ Wildberries API connection successful")
            return True
            
        except Exception as e:
            logger.error(
                "✗ Wildberries API connection failed",
                extra={"error": str(e)},
                exc_info=True,
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
