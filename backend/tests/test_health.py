"""Тесты health check endpoints"""

import pytest
from fastapi.testclient import TestClient


def test_health_check(client: TestClient) -> None:
    """GET /health возвращает status healthy"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "environment" in data


def test_health_db(client: TestClient) -> None:
    """GET /health/db проверяет подключение к БД"""
    response = client.get("/health/db")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_health_redis(client: TestClient) -> None:
    """GET /health/redis проверяет Redis (замокан в тестах)"""
    response = client.get("/health/redis")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_health_marketplace_missing_api_key(client: TestClient) -> None:
    """GET /health/marketplace/ozon без api_key возвращает 400"""
    response = client.get("/health/marketplace/ozon")
    assert response.status_code == 400
    assert "api_key" in response.json().get("message", "").lower()


def test_health_marketplace_ozon_missing_client_id(client: TestClient) -> None:
    """GET /health/marketplace/ozon без client_id возвращает 400"""
    response = client.get("/health/marketplace/ozon?api_key=test")
    assert response.status_code == 400
    assert "client_id" in response.json().get("message", "").lower()


def test_health_marketplace_unknown(client: TestClient) -> None:
    """GET /health/marketplace/unknown возвращает 400"""
    response = client.get("/health/marketplace/unknown?api_key=test")
    assert response.status_code == 400
