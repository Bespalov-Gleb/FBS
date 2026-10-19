"""Списки отправлений Ozon ходят в v4 и читают курсор из корня ответа."""
import pytest

from app.services.marketplace.ozon import OzonClient


def _posting(status: str = "awaiting_deliver") -> dict:
    return {
        "order_id": 1001,
        "posting_number": "1001-1",
        "status": status,
        "products": [{"offer_id": "ART", "name": "Футболка", "quantity": 1, "sku": 5}],
    }


@pytest.mark.asyncio
async def test_unfulfilled_list_uses_v4_cursor() -> None:
    client = OzonClient(api_key="key", client_id="1")
    captured: dict = {}

    async def fake_request(method, endpoint, params=None, json_data=None, max_retries=3):
        captured["method"] = method
        captured["endpoint"] = endpoint
        captured["body"] = json_data
        return {
            "postings": [_posting()],
            "has_next": True,
            "cursor": "page-2",
            "count": 1,
        }

    client._request = fake_request
    orders, has_next, cursor = await client.get_orders_unfulfilled_by_status(
        "awaiting_deliver",
        limit=1000,
        cursor="page-1",
    )

    assert captured["endpoint"] == "/v4/posting/fbs/unfulfilled/list"
    assert captured["body"]["limit"] == 100
    assert captured["body"]["cursor"] == "page-1"
    assert captured["body"]["sort_dir"] == "ASC"
    assert "offset" not in captured["body"]
    assert captured["body"]["filter"]["statuses"] == ["awaiting_deliver"]
    assert "cutoff_from" in captured["body"]["filter"]
    assert has_next is True
    assert cursor == "page-2"
    assert orders[0].posting_number == "1001-1"


@pytest.mark.asyncio
async def test_delivered_list_uses_v4_statuses() -> None:
    client = OzonClient(api_key="key", client_id="1")
    captured: dict = {}

    async def fake_request(method, endpoint, params=None, json_data=None, max_retries=3):
        captured["endpoint"] = endpoint
        captured["body"] = json_data
        return {"postings": [_posting("delivered")], "has_next": False}

    client._request = fake_request
    orders, has_next, cursor = await client.get_orders_delivered_or_delivering(limit=1000)

    assert captured["endpoint"] == "/v4/posting/fbs/list"
    assert captured["body"]["limit"] == 100
    assert captured["body"]["filter"]["statuses"] == ["delivering", "delivered"]
    assert "since" in captured["body"]["filter"]
    assert "to" in captured["body"]["filter"]
    assert has_next is False
    assert cursor is None
    assert orders[0].external_id == "1001"
