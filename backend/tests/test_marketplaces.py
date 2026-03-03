"""Тесты API маркетплейсов"""

import pytest
from fastapi.testclient import TestClient


def test_list_marketplaces_empty(client: TestClient, packer_headers: dict) -> None:
    """Список маркетплейсов для нового пользователя — пустой"""
    response = client.get("/api/v1/marketplaces", headers=packer_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_create_marketplace_wildberries(
    client: TestClient, packer_headers: dict
) -> None:
    """Создание маркетплейса WB"""
    response = client.post(
        "/api/v1/marketplaces",
        headers=packer_headers,
        json={
            "type": "wildberries",
            "name": "Test WB",
            "api_key": "test-api-key",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "wildberries"
    assert data["name"] == "Test WB"
    assert data["is_active"] is True


def test_create_marketplace_ozon_without_client_id(
    client: TestClient, packer_headers: dict
) -> None:
    """Создание Ozon без client_id возвращает 400"""
    response = client.post(
        "/api/v1/marketplaces",
        headers=packer_headers,
        json={
            "type": "ozon",
            "name": "Test Ozon",
            "api_key": "test-key",
        },
    )
    assert response.status_code == 400


def test_create_marketplace_ozon(
    client: TestClient, packer_headers: dict
) -> None:
    """Создание маркетплейса Ozon"""
    response = client.post(
        "/api/v1/marketplaces",
        headers=packer_headers,
        json={
            "type": "ozon",
            "name": "Test Ozon",
            "api_key": "test-key",
            "client_id": "12345",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "ozon"


def test_create_marketplace_invalid_type(
    client: TestClient, packer_headers: dict
) -> None:
    """Создание с неверным типом возвращает 400"""
    response = client.post(
        "/api/v1/marketplaces",
        headers=packer_headers,
        json={
            "type": "unknown",
            "name": "Test",
            "api_key": "key",
        },
    )
    assert response.status_code == 400
