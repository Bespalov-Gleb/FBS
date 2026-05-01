"""Тесты API настроек печати"""

import pytest
from fastapi.testclient import TestClient


def test_get_print_settings_empty(
    client: TestClient, packer_headers: dict
) -> None:
    """Настройки печати для нового пользователя — пустые"""
    response = client.get("/api/v1/print-settings", headers=packer_headers)
    assert response.status_code == 200
    data = response.json()
    assert data.get("default_printer") is None or data.get("default_printer") == ""
    assert data.get("auto_kiz_autofill") is True


def test_update_print_settings(client: TestClient, packer_headers: dict) -> None:
    """Обновление настроек печати"""
    response = client.patch(
        "/api/v1/print-settings",
        headers=packer_headers,
        json={
            "default_printer": "Zebra",
            "auto_print_on_click": True,
            "auto_kiz_autofill": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("default_printer") == "Zebra"
    assert data.get("auto_print_on_click") is True
    assert data.get("auto_kiz_autofill") is False


def test_get_test_label(client: TestClient, packer_headers: dict) -> None:
    """Тестовая этикетка возвращает PNG"""
    response = client.get("/api/v1/print-settings/test-label", headers=packer_headers)
    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("image/")
