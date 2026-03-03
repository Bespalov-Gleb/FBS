"""Тесты безопасности (хеширование, токены)"""

import pytest
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)


def test_password_hash_and_verify() -> None:
    """Пароль хешируется и проверяется корректно"""
    password = "my-secret-password"
    hashed = get_password_hash(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("wrong", hashed) is False


def test_create_and_decode_access_token() -> None:
    """Access токен создаётся и декодируется"""
    token = create_access_token(subject="123")
    assert isinstance(token, str)
    payload = decode_token(token)
    assert payload is not None
    assert payload.get("sub") == "123"
    assert payload.get("type") == "access"


def test_create_and_decode_refresh_token() -> None:
    """Refresh токен создаётся и декодируется"""
    token = create_refresh_token(subject="456")
    assert isinstance(token, str)
    payload = decode_token(token)
    assert payload is not None
    assert payload.get("sub") == "456"
    assert payload.get("type") == "refresh"


def test_decode_invalid_token() -> None:
    """Невалидный токен возвращает None"""
    assert decode_token("invalid") is None
    assert decode_token("") is None
