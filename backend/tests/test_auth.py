"""Тесты аутентификации"""

import pytest
from fastapi.testclient import TestClient


def test_register(client: TestClient) -> None:
    """Регистрация создаёт пользователя и возвращает токены"""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "newuser@test.com",
            "password": "password123",
            "full_name": "New User",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


def test_register_duplicate_email(client: TestClient, packer_user) -> None:
    """Регистрация с существующим email возвращает 400"""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": packer_user.email,
            "password": "password123",
            "full_name": "Duplicate",
        },
    )
    assert response.status_code == 400


def test_login(client: TestClient, packer_user) -> None:
    """Вход по email и паролю возвращает токены"""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": packer_user.email, "password": "password123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


def test_login_wrong_password(client: TestClient, packer_user) -> None:
    """Вход с неверным паролем возвращает 401"""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": packer_user.email, "password": "wrong"},
    )
    assert response.status_code == 401


def test_login_nonexistent_user(client: TestClient) -> None:
    """Вход с несуществующим email возвращает 401"""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@test.com", "password": "password123"},
    )
    assert response.status_code == 401


def test_me(client: TestClient, packer_headers: dict, packer_user) -> None:
    """GET /auth/me возвращает текущего пользователя"""
    response = client.get("/api/v1/auth/me", headers=packer_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == packer_user.email
    assert data["full_name"] == packer_user.full_name
    assert data["role"] == "packer"


def test_me_unauthorized(client: TestClient) -> None:
    """GET /auth/me без токена возвращает 401"""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 403  # HTTPBearer returns 403 when no auth


def test_refresh_token(client: TestClient, packer_user) -> None:
    """Обновление access токена по refresh"""
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": packer_user.email, "password": "password123"},
    )
    refresh_token = login_resp.json()["refresh_token"]

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_refresh_invalid_token(client: TestClient) -> None:
    """Обновление с невалидным refresh возвращает 401"""
    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "invalid-token"},
    )
    assert response.status_code == 401
