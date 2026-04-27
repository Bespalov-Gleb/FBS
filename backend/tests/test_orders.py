"""Тесты API заказов"""

import pytest
from fastapi.testclient import TestClient


def test_list_orders_unauthorized(client: TestClient) -> None:
    """Список заказов без авторизации возвращает 403"""
    response = client.get("/api/v1/orders")
    assert response.status_code == 403


def test_list_orders_empty(client: TestClient, packer_headers: dict) -> None:
    """Список заказов для нового пользователя — пустой"""
    response = client.get("/api/v1/orders", headers=packer_headers)
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] == 0
    assert data["items"] == []


def test_list_orders_with_params(client: TestClient, packer_headers: dict) -> None:
    """Список заказов с параметрами пагинации"""
    response = client.get(
        "/api/v1/orders?skip=0&limit=25&sort_by=marketplace_created_at&sort_desc=true",
        headers=packer_headers,
    )
    assert response.status_code == 200


def test_get_orders_stats(client: TestClient, packer_headers: dict) -> None:
    """Статистика заказов"""
    response = client.get("/api/v1/orders/stats", headers=packer_headers)
    assert response.status_code == 200
