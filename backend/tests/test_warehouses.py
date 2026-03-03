"""Тесты API складов"""

import pytest
from fastapi.testclient import TestClient


def test_list_all_warehouses_empty(
    client: TestClient, packer_headers: dict
) -> None:
    """Список складов для пользователя без маркетплейсов — пустой"""
    response = client.get("/api/v1/warehouses", headers=packer_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_list_warehouses_forbidden_for_packer(
    client: TestClient, packer_headers: dict
) -> None:
    """Список складов маркетплейса (для настройки) — только для admin"""
    response = client.get(
        "/api/v1/warehouses/marketplace/1",
        headers=packer_headers,
    )
    assert response.status_code == 403


def test_list_warehouses_admin_not_found(
    client: TestClient, admin_headers: dict
) -> None:
    """Список складов несуществующего маркетплейса — 404"""
    response = client.get(
        "/api/v1/warehouses/marketplace/99999",
        headers=admin_headers,
    )
    assert response.status_code == 404
