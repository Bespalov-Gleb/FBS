"""Отбор FBS-кампании и отгрузок «Готова к отправке» без сети."""
from app.services.marketplace.yandex import (
    YandexMarketClient,
    action_for_left_order,
    fbs_campaigns,
    pick_fbs_campaign,
    shipment_status,
)


READY = "OUTBOUND_CONFIRMED"
SIGNED = "OUTBOUND_SIGNED"


def _ids(shipments: list[dict]) -> set[int]:
    found: set[int] = set()
    for shipment in shipments:
        if shipment_status(shipment) not in {READY, SIGNED}:
            continue
        for order_id in shipment.get("orderIds") or []:
            found.add(int(order_id))
    return found


def test_ready_shipments_skip_formed_and_accepted() -> None:
    shipments = [
        {"status": READY, "orderIds": [10]},
        {"status": SIGNED, "orderIds": [11]},
        {"status": "OUTBOUND_READY_FOR_CONFIRMATION", "orderIds": [12]},
        {"status": "OUTBOUND_CREATED", "orderIds": [13]},
        {"status": "ACCEPTED", "orderIds": [14]},
        {"currentStatus": {"status": READY}, "orderIds": [15]},
    ]
    assert _ids(shipments) == {10, 11, 15}


def test_left_order_cancel_or_deliver() -> None:
    assert action_for_left_order("CANCELLED") == "cancel"
    assert action_for_left_order("PROCESSING") == "deliver"
    assert action_for_left_order(None) == "deliver"


def test_pick_single_fbs_and_ignore_fby() -> None:
    campaigns = [
        {"id": 22174799, "domain": "основной", "placementType": "FBS"},
        {"id": 84688355, "domain": "Giston", "placementType": "FBY"},
    ]
    assert [item["id"] for item in fbs_campaigns(campaigns)] == [22174799]
    chosen, error = pick_fbs_campaign(campaigns)
    assert error is None
    assert chosen is not None
    assert chosen["id"] == 22174799


def test_pick_requires_choice_when_several_fbs() -> None:
    campaigns = [
        {"id": 1, "domain": "a", "placementType": "FBS"},
        {"id": 2, "domain": "b", "placementType": "FBS"},
    ]
    chosen, error = pick_fbs_campaign(campaigns)
    assert chosen is None
    assert error is not None
    assert "1" in error and "2" in error
    chosen, error = pick_fbs_campaign(campaigns, "2")
    assert error is None
    assert chosen is not None
    assert chosen["id"] == 2


def test_order_barcode_and_size_from_offer() -> None:
    client = YandexMarketClient(api_key="test", client_id="22174799")
    order = client._to_marketplace_order(
        {
            "id": 62872703233,
            "status": "PROCESSING",
            "substatus": "READY_TO_SHIP",
            "creationDate": "13-10-2026 10:00:00",
            "items": [
                {"offerId": "longsleeve_xl", "offerName": "Лонгслив", "count": 1},
                {"offerId": "mario", "offerName": "Футболка", "count": 1},
            ],
        },
        {
            "id": 90550605,
            "planIntervalFrom": "2026-10-13T09:00:00+03:00",
            "orderIds": [62872703233],
            "warehouse": {"id": 10036903864, "name": "Склад Королёв"},
        },
        {
            "longsleeve_xl": {
                "barcodes": ["04660759956438"],
                "params": [
                    {"name": "Размер производителя", "value": "XL"},
                    {"name": "Российский размер", "value": "52"},
                ],
            },
            "mario": {"barcodes": ["OZN2396435883"], "params": []},
        },
    )
    assert order.external_id == "62872703233"
    assert order.quantity == 2
    assert order.metadata["warehouse_id"] == 10036903864
    assert order.metadata["products"][0]["barcode"] == "04660759956438"
    assert order.metadata["products"][0]["size"] == "XL / 52"
    assert order.metadata["products"][1]["barcode"] == "OZN2396435883"
    assert order.status == "awaiting_packaging"
