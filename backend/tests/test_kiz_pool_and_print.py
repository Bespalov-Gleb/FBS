"""Тесты пула КИЗ: ручная печать и списание, список товаров WB color/size."""

import sys
import types
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.kiz_group import KizGroup
from app.models.kiz_pool_item import KizCodeStatus, KizPoolItem
from app.models.marketplace import Marketplace, MarketplaceType
from app.models.order import Order, OrderStatus
from app.models.user import User
from app.services.kiz_pool_service import take_free_kiz_codes_for_manual_print


def _make_wb_marketplace(db: Session, user: User, name: str = "GISTON") -> Marketplace:
    mp = Marketplace(
        user_id=user.id,
        type=MarketplaceType.WILDBERRIES,
        name=name,
        api_key="test-key",
        is_kiz_enabled=True,
    )
    db.add(mp)
    db.flush()
    return mp


def _make_ozon_marketplace(db: Session, user: User, name: str = "OzonShop") -> Marketplace:
    mp = Marketplace(
        user_id=user.id,
        type=MarketplaceType.OZON,
        name=name,
        api_key="test-key",
        client_id="123",
    )
    db.add(mp)
    db.flush()
    return mp


def _make_group(db: Session, user: User, name: str = "group-1") -> KizGroup:
    group = KizGroup(user_id=user.id, name=name, is_active=True)
    db.add(group)
    db.flush()
    return group


def _add_free_codes(db: Session, group_id: int, codes: list[str]) -> None:
    for code in codes:
        db.add(
            KizPoolItem(
                code=code,
                group_id=group_id,
                status=KizCodeStatus.FREE,
                source_filename="test.pdf",
                source_page=1,
            )
        )
    db.flush()


def test_take_free_kiz_codes_fifo_and_mark_used(
    db_session: Session,
    admin_user: User,
) -> None:
    group = _make_group(db_session, admin_user)
    _add_free_codes(db_session, group.id, ["CODE_A", "CODE_B", "CODE_C"])
    db_session.commit()

    taken = take_free_kiz_codes_for_manual_print(
        db_session,
        group=group,
        count=2,
        used_by_user_id=admin_user.id,
    )
    db_session.commit()

    assert [item.code for item in taken] == ["CODE_A", "CODE_B"]
    items = (
        db_session.query(KizPoolItem)
        .filter(KizPoolItem.group_id == group.id)
        .order_by(KizPoolItem.id.asc())
        .all()
    )
    assert items[0].status == KizCodeStatus.USED
    assert items[0].used_order_id is None
    assert items[0].used_by_user_id == admin_user.id
    assert items[1].status == KizCodeStatus.USED
    assert items[2].status == KizCodeStatus.FREE


def test_take_free_kiz_codes_insufficient(
    db_session: Session,
    admin_user: User,
) -> None:
    group = _make_group(db_session, admin_user)
    _add_free_codes(db_session, group.id, ["ONLY_ONE"])
    db_session.commit()

    with pytest.raises(ValueError, match="недостаточно КИЗ"):
        take_free_kiz_codes_for_manual_print(
            db_session,
            group=group,
            count=2,
            used_by_user_id=admin_user.id,
        )


def test_print_from_group_api_deducts_and_returns_pdf(
    client: TestClient,
    db_session: Session,
    admin_user: User,
    admin_headers: dict,
) -> None:
    group = _make_group(db_session, admin_user, name="print-grp")
    _add_free_codes(
        db_session,
        group.id,
        [
            "010460406000000021ABCDE1234567890",
            "010460406000000021ABCDE1234567891",
            "010460406000000021ABCDE1234567892",
        ],
    )
    db_session.commit()

    fake_page_pdf = b"%PDF-1.4 one-page"
    fake_pypdf = types.ModuleType("pypdf")

    class _FakeReader:
        def __init__(self, *_a, **_k):
            self.pages = [object()]

    class _FakeWriter:
        def add_page(self, _page):
            return None

        def write(self, buf):
            buf.write(b"%PDF-1.4 merged-labels")

    fake_pypdf.PdfReader = _FakeReader
    fake_pypdf.PdfWriter = _FakeWriter

    with patch.dict(sys.modules, {"pypdf": fake_pypdf}), patch(
        "app.api.v1.endpoints.orders._generate_kiz_label_pdf",
        return_value=fake_page_pdf,
    ), patch(
        "app.api.v1.endpoints.orders._normalize_kiz_for_label",
        side_effect=lambda x: x,
    ), patch(
        "app.api.v1.endpoints.orders._kiz_31",
        side_effect=lambda x: (x or "")[:31],
    ), patch(
        "app.api.v1.endpoints.orders._rotate_pdf",
        side_effect=lambda pdf, _rot: pdf,
    ):
        response = client.post(
            f"/api/v1/kiz-groups/{group.id}/print",
            headers=admin_headers,
            json={"count": 2},
        )

    assert response.status_code == 200, response.text
    assert response.headers.get("content-type", "").startswith("application/pdf")
    assert response.headers.get("X-Printed-Count") == "2"
    assert response.headers.get("X-Skipped-Count") == "0"
    assert b"%PDF-1.4 merged-labels" in response.content

    db_session.expire_all()
    free_left = (
        db_session.query(KizPoolItem)
        .filter(
            KizPoolItem.group_id == group.id,
            KizPoolItem.status == KizCodeStatus.FREE,
        )
        .count()
    )
    used = (
        db_session.query(KizPoolItem)
        .filter(
            KizPoolItem.group_id == group.id,
            KizPoolItem.status == KizCodeStatus.USED,
        )
        .count()
    )
    assert free_left == 1
    assert used == 2


def test_print_from_group_skips_bad_codes_and_keeps_good(
    client: TestClient,
    db_session: Session,
    admin_user: User,
    admin_headers: dict,
) -> None:
    group = _make_group(db_session, admin_user, name="print-skip")
    _add_free_codes(
        db_session,
        group.id,
        [
            "010460406000000021GOODCODE0000001",
            "010460406000000021BADCODE00000002",
            "010460406000000021GOODCODE0000003",
        ],
    )
    db_session.commit()

    fake_pypdf = types.ModuleType("pypdf")

    class _FakeReader:
        def __init__(self, *_a, **_k):
            self.pages = [object()]

    class _FakeWriter:
        def add_page(self, _page):
            return None

        def write(self, buf):
            buf.write(b"%PDF-1.4 partial")

    fake_pypdf.PdfReader = _FakeReader
    fake_pypdf.PdfWriter = _FakeWriter

    def _gen(kiz, *_a, **_k):
        if "BADCODE" in kiz:
            raise ValueError("bwipp.GS1aiMissingCloseParen AIs must end with ')'")
        return b"%PDF-1.4 ok"

    with patch.dict(sys.modules, {"pypdf": fake_pypdf}), patch(
        "app.api.v1.endpoints.orders._generate_kiz_label_pdf",
        side_effect=_gen,
    ), patch(
        "app.api.v1.endpoints.orders._normalize_kiz_for_label",
        side_effect=lambda x: x,
    ), patch(
        "app.api.v1.endpoints.orders._kiz_31",
        side_effect=lambda x: (x or "")[:31],
    ), patch(
        "app.api.v1.endpoints.orders._rotate_pdf",
        side_effect=lambda pdf, _rot: pdf,
    ):
        response = client.post(
            f"/api/v1/kiz-groups/{group.id}/print",
            headers=admin_headers,
            json={"count": 3},
        )

    assert response.status_code == 200, response.text
    assert response.headers.get("X-Printed-Count") == "2"
    assert response.headers.get("X-Skipped-Count") == "1"

    db_session.expire_all()
    items = (
        db_session.query(KizPoolItem)
        .filter(KizPoolItem.group_id == group.id)
        .order_by(KizPoolItem.id.asc())
        .all()
    )
    assert items[0].status == KizCodeStatus.USED
    assert items[1].status == KizCodeStatus.FREE  # кривой вернули
    assert items[2].status == KizCodeStatus.USED


def test_print_from_group_api_not_enough(
    client: TestClient,
    db_session: Session,
    admin_user: User,
    admin_headers: dict,
) -> None:
    group = _make_group(db_session, admin_user)
    _add_free_codes(db_session, group.id, ["ONLY"])
    db_session.commit()

    response = client.post(
        f"/api/v1/kiz-groups/{group.id}/print",
        headers=admin_headers,
        json={"count": 5},
    )
    assert response.status_code == 400
    assert "недостаточно" in response.json()["detail"].lower()


def test_print_from_group_forbidden_for_packer(
    client: TestClient,
    db_session: Session,
    admin_user: User,
    packer_headers: dict,
) -> None:
    group = _make_group(db_session, admin_user)
    _add_free_codes(db_session, group.id, ["CODE"])
    db_session.commit()

    response = client.post(
        f"/api/v1/kiz-groups/{group.id}/print",
        headers=packer_headers,
        json={"count": 1},
    )
    assert response.status_code in (401, 403)


def test_list_products_wb_splits_color_and_size(
    client: TestClient,
    db_session: Session,
    admin_user: User,
    admin_headers: dict,
) -> None:
    mp = _make_wb_marketplace(db_session, admin_user)
    db_session.add(
        Order(
            marketplace_id=mp.id,
            external_id="wb-1",
            posting_number="rid-1",
            article="ALCOHOLICA_manblack",
            product_name="ALCOHOLICA_manblack",
            quantity=1,
            status=OrderStatus.AWAITING_PACKAGING,
            extra_data={"size": "L"},
        )
    )
    db_session.add(
        Order(
            marketplace_id=mp.id,
            external_id="wb-2",
            posting_number="rid-2",
            article="Always_relative_white",
            product_name="Always_relative_white",
            quantity=1,
            status=OrderStatus.AWAITING_PACKAGING,
            extra_data={"size": "XL"},
        )
    )
    db_session.commit()

    response = client.get("/api/v1/kiz-groups/products", headers=admin_headers)
    assert response.status_code == 200, response.text
    rows = response.json()
    by_article = {r["article"]: r for r in rows}

    assert by_article["ALCOHOLICA"]["color"] == "black"
    assert by_article["ALCOHOLICA"]["size"] == "L"
    assert by_article["Always_relative"]["color"] == "white"
    assert by_article["Always_relative"]["size"] == "XL"


def test_list_products_ozon_size_from_suffix_no_color(
    client: TestClient,
    db_session: Session,
    admin_user: User,
    admin_headers: dict,
) -> None:
    mp = _make_ozon_marketplace(db_session, admin_user)
    db_session.add(
        Order(
            marketplace_id=mp.id,
            external_id="oz-1",
            posting_number="post-1",
            article="SHIRT_42",
            product_name="Shirt",
            quantity=1,
            status=OrderStatus.AWAITING_PACKAGING,
            extra_data={},
        )
    )
    db_session.commit()

    response = client.get("/api/v1/kiz-groups/products", headers=admin_headers)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["article"] == "SHIRT"
    assert rows[0]["size"] == "42"
    assert rows[0]["color"] == ""


def test_list_products_ozon_color_from_settings_markers(
    client: TestClient,
    db_session: Session,
    admin_user: User,
    admin_headers: dict,
) -> None:
    mp = _make_ozon_marketplace(db_session, admin_user)
    db_session.add(
        Order(
            marketplace_id=mp.id,
            external_id="oz-2",
            posting_number="post-2",
            article="cepi_cepi_white_L",
            product_name="Футболка",
            quantity=1,
            status=OrderStatus.AWAITING_PACKAGING,
            extra_data={},
        )
    )
    db_session.commit()

    put = client.put(
        "/api/v1/kiz-groups/color-markers",
        headers=admin_headers,
        json={"color_markers": ["white", "black"]},
    )
    assert put.status_code == 200, put.text

    response = client.get("/api/v1/kiz-groups/products", headers=admin_headers)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["color"] == "white"
    assert rows[0]["size"] == "L"
    assert rows[0]["article"] == "cepi_cepi"


def test_color_markers_get_defaults(
    client: TestClient,
    admin_headers: dict,
) -> None:
    response = client.get("/api/v1/kiz-groups/color-markers", headers=admin_headers)
    assert response.status_code == 200
    markers = response.json()["color_markers"]
    assert "white" in markers
    assert "black" in markers
