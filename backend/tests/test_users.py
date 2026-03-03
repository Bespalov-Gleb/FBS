"""Тесты API пользователей (только для admin)"""

import pytest
from fastapi.testclient import TestClient


def test_list_users_forbidden_for_packer(
    client: TestClient, packer_headers: dict
) -> None:
    """Список пользователей недоступен для packer"""
    response = client.get("/api/v1/users", headers=packer_headers)
    assert response.status_code == 403


def test_list_users_admin(client: TestClient, admin_headers: dict) -> None:
    """Админ может получить список пользователей"""
    response = client.get("/api/v1/users", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_create_user_admin(client: TestClient, admin_headers: dict) -> None:
    """Админ может создать пользователя"""
    response = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "email": "newpacker@test.com",
            "password": "password123",
            "full_name": "New Packer",
            "role": "packer",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "newpacker@test.com"
    assert data["role"] == "packer"


def test_create_user_forbidden_for_packer(
    client: TestClient, packer_headers: dict
) -> None:
    """Создание пользователя недоступно для packer"""
    response = client.post(
        "/api/v1/users",
        headers=packer_headers,
        json={
            "email": "new@test.com",
            "password": "pass",
            "full_name": "New",
            "role": "packer",
        },
    )
    assert response.status_code == 403
