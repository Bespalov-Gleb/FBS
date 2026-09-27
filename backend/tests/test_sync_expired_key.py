"""Синк не должен превращать истёкший ключ одного магазина в 403 на весь запрос."""
import asyncio
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.exceptions import MarketplaceAPIException
from app.core.security import encrypt_api_key
from app.models.marketplace import Marketplace, MarketplaceType
from app.models.user import User
from app.services.warehouse_service import WarehouseService


def _ozon(db: Session, user: User, name: str) -> Marketplace:
    mp = Marketplace(
        user_id=user.id,
        type=MarketplaceType.OZON,
        name=name,
        api_key=encrypt_api_key("test-key"),
        client_id="12345",
        is_kiz_enabled=False,
        save_kiz_to_file=False,
        is_active=True,
    )
    db.add(mp)
    db.commit()
    db.refresh(mp)
    return mp


def _expired_key() -> MarketplaceAPIException:
    return MarketplaceAPIException(
        message="Ozon API error: HTTP 403",
        marketplace="Ozon",
        detail={"code": 7, "message": "Api-key has expired, generate a new one"},
        status_code=403,
    )


def test_sync_all_continues_when_one_ozon_key_expired(
    client: TestClient,
    db_session: Session,
    admin_user: User,
    admin_headers: dict,
) -> None:
    dead = _ozon(db_session, admin_user, "УДАЧКА")
    alive = _ozon(db_session, admin_user, "СЭР ФУТБОЛКИН")

    async def fake_sync(mp: Marketplace, db: Session, *, sync_source: str = "manual") -> int:
        if mp.id == dead.id:
            raise _expired_key()
        assert mp.id == alive.id
        return 4

    with patch(
        "app.api.v1.endpoints.orders.OrderSyncService.sync_marketplace_orders",
        new=fake_sync,
    ):
        response = client.post("/api/v1/orders/sync/all", headers=admin_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_synced"] == 4
    assert body["error_count"] == 1
    assert body["total_marketplaces"] == 2
    errors = [item for item in body["results"] if item.get("skipped") == "error"]
    assert len(errors) == 1
    assert errors[0]["marketplace_id"] == dead.id
    assert "УДАЧКА" in errors[0]["error"]
    assert "истёк" in errors[0]["error"]


def test_single_sync_expired_key_is_400_not_403(
    client: TestClient,
    db_session: Session,
    admin_user: User,
    admin_headers: dict,
) -> None:
    dead = _ozon(db_session, admin_user, "futba")

    async def fake_sync(mp: Marketplace, db: Session, *, sync_source: str = "manual") -> int:
        raise _expired_key()

    with patch(
        "app.api.v1.endpoints.orders.OrderSyncService.sync_marketplace_orders",
        new=fake_sync,
    ):
        response = client.post(
            f"/api/v1/orders/sync/marketplace/{dead.id}",
            headers=admin_headers,
        )

    assert response.status_code == 400, response.text
    assert "futba" in response.json()["detail"]
    assert "истёк" in response.json()["detail"]


def test_warehouse_list_403_does_not_abort_order_sync(
    db_session: Session,
    admin_user: User,
) -> None:
    mp = _ozon(db_session, admin_user, "test")

    class ExpiredOzon:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get_warehouses(self):
            raise _expired_key()

    with patch(
        "app.services.warehouse_service.should_skip_ozon_warehouse_list",
        return_value=False,
    ), patch(
        "app.services.warehouse_service.OzonClient",
        return_value=ExpiredOzon(),
    ):
        count = asyncio.run(WarehouseService.sync_warehouses(mp, db_session))

    assert count == 0
