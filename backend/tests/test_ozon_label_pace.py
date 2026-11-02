"""Пауза, повтор и кэш этикетки Ozon package-label."""
import pytest

from app.core.exceptions import MarketplaceAPIException
from app.services.marketplace.ozon import (
    OZON_LABEL_RATE_LIMIT_MESSAGE,
    OzonClient,
)
from app.services.ozon_distributed_pace import _redis_pace_sync, pace_wait_ms


def test_pace_wait_ms() -> None:
    assert pace_wait_ms(1_000, 0, 1500) == 0
    assert pace_wait_ms(1_000, 1_000, 1500) == 1500
    assert pace_wait_ms(2_000, 1_000, 1500) == 500
    assert pace_wait_ms(3_000, 1_000, 380) == 0


class _FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.t = 1_700_000_000.0

    def time(self):
        return (int(self.t), int((self.t - int(self.t)) * 1_000_000))

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, value, nx=False, px=None):
        if nx and key in self.kv:
            return False
        self.kv[key] = str(value)
        return True

    def delete(self, key):
        self.kv.pop(key, None)


def test_redis_pace_holds_label_gap(monkeypatch) -> None:
    fake = _FakeRedis()
    slept: list[float] = []

    def fake_sleep(sec: float) -> None:
        slept.append(sec)
        fake.t += sec

    monkeypatch.setattr("app.services.ozon_distributed_pace.get_redis_client", lambda: fake)
    monkeypatch.setattr("app.services.ozon_distributed_pace.time.sleep", fake_sleep)

    _redis_pace_sync("client", 380, 5)
    assert slept == []
    _redis_pace_sync("client", 1500, 5)
    assert sum(slept) == pytest.approx(1.5, abs=0.05)


def _rate_limit() -> MarketplaceAPIException:
    return MarketplaceAPIException(
        message="Ozon API error: HTTP 429",
        marketplace="Ozon",
        detail="You have reached request rate limit per second",
        status_code=429,
    )


@pytest.mark.asyncio
async def test_label_retries_429_then_uses_cache(monkeypatch) -> None:
    client = OzonClient(api_key="key", client_id="8816")
    calls: list[str] = []
    store: dict[str, bytes] = {}

    async def request_content(method, endpoint, json_data=None):
        calls.append(endpoint)
        if len(calls) < 3:
            raise _rate_limit()
        return b"%PDF-1.4 cached"

    monkeypatch.setattr(client, "_request_content", request_content)
    monkeypatch.setattr(
        "app.services.marketplace.ozon._load_cached_ozon_label",
        lambda client_id, posting: store.get(posting),
    )
    monkeypatch.setattr(
        "app.services.marketplace.ozon._store_cached_ozon_label",
        lambda client_id, posting, content: store.__setitem__(posting, content),
    )
    monkeypatch.setattr("app.services.marketplace.ozon.settings.OZON_LABEL_MAX_ATTEMPTS", 5)

    pdf = await client.get_order_label("0135467400-0220-1")
    assert pdf.startswith(b"%PDF")
    assert len(calls) == 3

    again = await client.get_order_label("0135467400-0220-1")
    assert again == pdf
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_label_does_not_retry_other_errors(monkeypatch) -> None:
    client = OzonClient(api_key="key", client_id="8816")
    calls = {"n": 0}

    async def request_content(method, endpoint, json_data=None):
        calls["n"] += 1
        raise MarketplaceAPIException(
            message="Ozon API error: HTTP 400",
            marketplace="Ozon",
            detail="label not allowed for delivered postings",
            status_code=400,
        )

    monkeypatch.setattr(client, "_request_content", request_content)
    monkeypatch.setattr(
        "app.services.marketplace.ozon._load_cached_ozon_label",
        lambda client_id, posting: None,
    )

    with pytest.raises(MarketplaceAPIException) as exc:
        await client.get_order_label("0135467400-0220-1")
    assert exc.value.status_code == 400
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_label_429_after_attempts_is_russian(monkeypatch) -> None:
    client = OzonClient(api_key="key", client_id="8816")
    calls = {"n": 0}

    async def request_content(method, endpoint, json_data=None):
        calls["n"] += 1
        raise _rate_limit()

    monkeypatch.setattr(client, "_request_content", request_content)
    monkeypatch.setattr(
        "app.services.marketplace.ozon._load_cached_ozon_label",
        lambda client_id, posting: None,
    )
    monkeypatch.setattr("app.services.marketplace.ozon.settings.OZON_LABEL_MAX_ATTEMPTS", 4)

    with pytest.raises(MarketplaceAPIException) as exc:
        await client.get_order_label("0135467400-0220-1")
    assert exc.value.status_code == 429
    assert exc.value.detail == OZON_LABEL_RATE_LIMIT_MESSAGE
    assert calls["n"] == 4
