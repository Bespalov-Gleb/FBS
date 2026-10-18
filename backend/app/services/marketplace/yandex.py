"""
Клиент API Яндекс Маркета (FBS).

Выгружаем только отгрузки «Готова к отправке»:
OUTBOUND_CONFIRMED и OUTBOUND_SIGNED.
Заказы «Ждут сборки» и отгрузки без подписанного акта не берём.
"""
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.core.exceptions import MarketplaceAPIException
from app.services.marketplace.base import (
    BaseMarketplaceClient,
    MarketplaceOrder,
    OrderStatus,
)
from app.services.product_barcode import choose_product_barcode
from app.utils.logger import logger

READY_SHIPMENT_STATUSES = frozenset({"OUTBOUND_CONFIRMED", "OUTBOUND_SIGNED"})
_MSK = ZoneInfo("Europe/Moscow")


def shipment_date_window(today: Optional[date] = None) -> tuple[str, str]:
    """Окно дат отгрузки: вчера … +14 дней, календарь Москвы, формат YYYY-MM-DD."""
    day = today or datetime.now(_MSK).date()
    return (day - timedelta(days=1)).isoformat(), (day + timedelta(days=14)).isoformat()


def shipment_status(shipment: dict) -> str:
    if shipment.get("status"):
        return str(shipment["status"])
    current = shipment.get("currentStatus") or {}
    return str(current.get("status") or "")


def fbs_campaigns(campaigns: list[dict]) -> list[dict]:
    return [
        campaign
        for campaign in campaigns
        if campaign.get("placementType") == "FBS"
    ]


def pick_fbs_campaign(
    campaigns: list[dict],
    requested_id: Optional[str] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """Один FBS — его и берём. Несколько — нужен явный id. FBY не рассматриваем."""
    fbs = fbs_campaigns(campaigns)
    if not fbs:
        return None, "В ключе нет магазина FBS"
    if requested_id:
        wanted = str(requested_id).strip()
        match = next((item for item in fbs if str(item.get("id")) == wanted), None)
        if not match:
            return None, "Указанная кампания не найдена среди магазинов FBS"
        return match, None
    if len(fbs) > 1:
        names = ", ".join(
            f"{item.get('id')} ({item.get('domain') or 'магазин'})" for item in fbs
        )
        return None, f"Несколько магазинов FBS, укажите client_id кампании: {names}"
    return fbs[0], None


def action_for_left_order(status: Optional[str]) -> str:
    """Заказ вышел из «Готова к отправке»: отмена или скрыть как сданный."""
    if (status or "").upper() == "CANCELLED":
        return "cancel"
    return "deliver"


def format_offer_size(params: list | None) -> Optional[str]:
    """Размер производителя и российский: «XL / 52»."""
    manufacturer = ""
    russian = ""
    for param in params or []:
        if not isinstance(param, dict):
            continue
        name = str(param.get("name") or "").strip().lower()
        value = str(param.get("value") or "").strip()
        if not value or len(value) > 40:
            continue
        if name == "размер производителя":
            manufacturer = value
        elif name == "российский размер":
            russian = value
    if manufacturer and russian and russian not in manufacturer:
        return f"{manufacturer} / {russian}"
    return manufacturer or russian or None


def _first_picture(offer: dict) -> str:
    for picture in offer.get("pictures") or []:
        if isinstance(picture, str) and picture.startswith("http"):
            return picture
        if isinstance(picture, dict):
            url = picture.get("url") or picture.get("preview") or ""
            if isinstance(url, str) and url.startswith("http"):
                return url
    return ""


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in ("%d-%m-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None)
    except ValueError:
        return None


class YandexMarketClient(BaseMarketplaceClient):
    """Partner API Яндекс Маркета. client_id — campaignId магазина FBS."""

    @property
    def base_url(self) -> str:
        return "https://api.partner.market.yandex.ru"

    @property
    def marketplace_name(self) -> str:
        return "Yandex"

    def _get_headers(self) -> dict[str, str]:
        return {
            "Api-Key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def list_campaigns(self) -> list[dict]:
        data = await self._request("GET", "/v2/campaigns")
        campaigns = data.get("campaigns")
        if campaigns is None and isinstance(data.get("result"), dict):
            campaigns = data["result"].get("campaigns")
        return campaigns or []

    async def resolve_business_id(self, campaign_id: str) -> int:
        for campaign in await self.list_campaigns():
            if str(campaign.get("id")) != str(campaign_id):
                continue
            business = campaign.get("business") or {}
            business_id = business.get("id")
            if business_id:
                return int(business_id)
        raise MarketplaceAPIException(
            message="Не найден businessId кампании Яндекс Маркета",
            marketplace=self.marketplace_name,
            detail=str(campaign_id),
        )

    async def search_shipments(
        self,
        campaign_id: str,
        date_from: str,
        date_to: str,
        statuses: list[str],
    ) -> list[dict]:
        shipments: list[dict] = []
        page_token: Optional[str] = None
        while True:
            params: dict[str, Any] = {"limit": 30}
            if page_token:
                params["pageToken"] = page_token
            data = await self._request(
                "PUT",
                f"/v2/campaigns/{campaign_id}/first-mile/shipments",
                params=params,
                json_data={
                    "dateFrom": date_from,
                    "dateTo": date_to,
                    "statuses": statuses,
                    "cancelledOrders": False,
                },
            )
            result = data.get("result") or {}
            shipments.extend(result.get("shipments") or [])
            page_token = (result.get("paging") or {}).get("nextPageToken")
            if not page_token:
                break
        return shipments

    async def get_order(self, campaign_id: str, order_id: int | str) -> dict:
        data = await self._request(
            "GET",
            f"/v2/campaigns/{campaign_id}/orders/{order_id}",
        )
        order = data.get("order")
        if order is None and isinstance(data.get("result"), dict):
            order = data["result"].get("order") or data["result"]
        if not isinstance(order, dict) or not order.get("id"):
            raise MarketplaceAPIException(
                message="Пустой ответ заказа Яндекс Маркета",
                marketplace=self.marketplace_name,
                detail=str(order_id),
            )
        return order

    async def get_offer_mappings(self, business_id: int, offer_ids: list[str]) -> dict[str, dict]:
        found: dict[str, dict] = {}
        unique = list(dict.fromkeys(offer_id for offer_id in offer_ids if offer_id))
        for offset in range(0, len(unique), 50):
            chunk = unique[offset : offset + 50]
            data = await self._request(
                "POST",
                f"/v2/businesses/{business_id}/offer-mappings",
                json_data={"offerIds": chunk},
            )
            result = data.get("result") or {}
            for mapping in result.get("offerMappings") or []:
                offer = mapping.get("offer") or {}
                offer_id = offer.get("offerId")
                if offer_id:
                    found[str(offer_id)] = offer
        return found

    async def get_order_label(self, order_id: str) -> bytes:
        if not self.client_id:
            raise ValueError("campaign id is required for Yandex labels")
        return await self._request_content(
            "GET",
            f"/v2/campaigns/{self.client_id}/orders/{order_id}/delivery/labels"
            "?format=A9_HORIZONTALLY",
        )

    async def get_orders(
        self,
        warehouse_id: Optional[str] = None,
        since: Optional[datetime] = None,
        to: Optional[datetime] = None,
    ) -> list[MarketplaceOrder]:
        orders, _ready_ids = await self.fetch_ready_orders()
        return orders

    async def fetch_ready_orders(self) -> tuple[list[MarketplaceOrder], set[str]]:
        if not self.client_id:
            raise ValueError("campaign id is required for Yandex sync")
        campaign_id = str(self.client_id)
        business_id = await self.resolve_business_id(campaign_id)
        date_from, date_to = shipment_date_window()
        shipments = await self.search_shipments(
            campaign_id,
            date_from,
            date_to,
            sorted(READY_SHIPMENT_STATUSES),
        )
        ready = [item for item in shipments if shipment_status(item) in READY_SHIPMENT_STATUSES]
        order_to_shipment: dict[int, dict] = {}
        for shipment in ready:
            for order_id in shipment.get("orderIds") or []:
                order_to_shipment[int(order_id)] = shipment
        raw_orders: list[dict] = []
        for order_id in order_to_shipment:
            raw_orders.append(await self.get_order(campaign_id, order_id))
        offer_ids = [
            str(item.get("offerId"))
            for order in raw_orders
            for item in (order.get("items") or [])
            if item.get("offerId")
        ]
        offers = await self.get_offer_mappings(business_id, offer_ids) if offer_ids else {}
        parsed = [
            self._to_marketplace_order(order, order_to_shipment[int(order["id"])], offers)
            for order in raw_orders
            if order.get("id") is not None
        ]
        logger.info(
            "Yandex campaign %s: ready shipments=%s orders=%s",
            campaign_id,
            len(ready),
            len(parsed),
        )
        return parsed, {str(order_id) for order_id in order_to_shipment}

    def _to_marketplace_order(
        self,
        order: dict,
        shipment: dict,
        offers: dict[str, dict],
    ) -> MarketplaceOrder:
        items = order.get("items") or []
        products: list[dict] = []
        total_qty = 0
        for item in items:
            offer_id = str(item.get("offerId") or item.get("shopSku") or "").strip()
            offer = offers.get(offer_id) or {}
            barcodes = offer.get("barcodes") or []
            if isinstance(barcodes, str):
                barcodes = [barcodes]
            chosen = choose_product_barcode([str(code) for code in barcodes])
            params = offer.get("params") or offer.get("parameterValues") or []
            size = format_offer_size(params if isinstance(params, list) else [])
            quantity = max(1, int(item.get("count") or 1))
            total_qty += quantity
            products.append(
                {
                    "offer_id": offer_id,
                    "name": item.get("offerName") or offer.get("name") or offer_id,
                    "quantity": quantity,
                    "barcode": chosen,
                    "barcodes": [str(code) for code in barcodes if str(code).strip()],
                    "size": size,
                    "image_url": _first_picture(offer),
                }
            )
        first = products[0] if products else {}
        warehouse = shipment.get("warehouse") or {}
        warehouse_id = warehouse.get("id")
        status = str(order.get("status") or "")
        substatus = str(order.get("substatus") or "")
        return MarketplaceOrder(
            external_id=str(order.get("id")),
            posting_number=str(order.get("id")),
            article=str(first.get("offer_id") or ""),
            product_name=str(first.get("name") or first.get("offer_id") or "Заказ Яндекс Маркета"),
            quantity=total_qty or 1,
            warehouse_name=warehouse.get("name"),
            status=OrderStatus.AWAITING_PACKAGING.value,
            created_at=_parse_datetime(order.get("creationDate")),
            metadata={
                "marketplace": "yandex",
                "status": status,
                "substatus": substatus,
                "shipment_id": shipment.get("id"),
                "shipment_date": shipment.get("planIntervalFrom"),
                "warehouse_id": warehouse_id,
                "products": products,
                "size": first.get("size"),
                "product_image_url": first.get("image_url") or "",
            },
        )

    async def update_order_status(self, order_id: str, status: OrderStatus) -> bool:
        return False

    async def test_connection(self) -> bool:
        campaigns = await self.list_campaigns()
        return bool(fbs_campaigns(campaigns))
