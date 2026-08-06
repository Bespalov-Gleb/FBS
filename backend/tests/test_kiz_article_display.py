"""Тесты разбора артикула: цвет / размер для WB и Ozon."""

import pytest
from sqlalchemy.orm import Session

from app.api.v1.endpoints.kiz_groups import (
    _article_display_parts,
    _find_product_mapping,
    _is_wildberries,
    _split_article_and_size,
)
from app.models.kiz_group import KizGroup
from app.models.kiz_product_mapping import KizProductMapping
from app.models.marketplace import Marketplace, MarketplaceType
from app.models.user import User


@pytest.mark.parametrize(
    "article, expected",
    [
        ("ALCOHOLICA_manblack", ("ALCOHOLICA", "manblack")),
        ("Always_relative_white", ("Always_relative", "white")),
        ("NOSUFFIX", ("NOSUFFIX", "")),
        ("", ("", "")),
        ("_onlytail", ("_onlytail", "")),
    ],
)
def test_split_article_and_size(article: str, expected: tuple[str, str]) -> None:
    assert _split_article_and_size(article) == expected


def test_is_wildberries() -> None:
    assert _is_wildberries(MarketplaceType.WILDBERRIES) is True
    assert _is_wildberries("wildberries") is True
    assert _is_wildberries(MarketplaceType.OZON) is False
    assert _is_wildberries("ozon") is False
    assert _is_wildberries(None) is False


def test_article_display_parts_wb_color_and_real_size() -> None:
    base, size, color = _article_display_parts(
        "ALCOHOLICA_manblack",
        marketplace_type=MarketplaceType.WILDBERRIES,
        size_from_order="L",
    )
    assert base == "ALCOHOLICA"
    assert color == "manblack"
    assert size == "L"


def test_article_display_parts_wb_without_order_size() -> None:
    base, size, color = _article_display_parts(
        "Zad_Mentality_black",
        marketplace_type="wildberries",
        size_from_order=None,
    )
    assert base == "Zad_Mentality"
    assert color == "black"
    assert size == ""


def test_article_display_parts_ozon_keeps_size_in_suffix() -> None:
    base, size, color = _article_display_parts(
        "SHIRT_XL",
        marketplace_type=MarketplaceType.OZON,
        size_from_order=None,
    )
    assert base == "SHIRT"
    assert size == "XL"
    assert color == ""


def test_article_display_parts_ozon_prefers_order_size() -> None:
    base, size, color = _article_display_parts(
        "SHIRT_XL",
        marketplace_type=MarketplaceType.OZON,
        size_from_order="48-50",
    )
    assert base == "SHIRT"
    assert size == "48-50"
    assert color == ""


def test_find_product_mapping_prefers_real_size_then_color_fallback(
    db_session: Session,
    admin_user: User,
) -> None:
    mp = Marketplace(
        user_id=admin_user.id,
        type=MarketplaceType.WILDBERRIES,
        name="GISTON",
        api_key="test-key",
    )
    group = KizGroup(user_id=admin_user.id, name="grp-L", is_active=True)
    db_session.add_all([mp, group])
    db_session.flush()

    legacy = KizProductMapping(
        user_id=admin_user.id,
        marketplace_id=mp.id,
        group_id=group.id,
        article="ALCOHOLICA",
        size="manblack",  # старый маппинг: цвет в size
    )
    db_session.add(legacy)
    db_session.commit()

    # По реальному размеру пока нет — фолбэк на цвет
    found = _find_product_mapping(
        db_session,
        user_id=admin_user.id,
        marketplace_id=mp.id,
        article="ALCOHOLICA",
        size="L",
        color="manblack",
    )
    assert found is not None
    assert found[0].size == "manblack"

    modern = KizProductMapping(
        user_id=admin_user.id,
        marketplace_id=mp.id,
        group_id=group.id,
        article="ALCOHOLICA",
        size="L",
    )
    db_session.add(modern)
    db_session.commit()

    found2 = _find_product_mapping(
        db_session,
        user_id=admin_user.id,
        marketplace_id=mp.id,
        article="ALCOHOLICA",
        size="L",
        color="manblack",
    )
    assert found2 is not None
    assert found2[0].size == "L"
