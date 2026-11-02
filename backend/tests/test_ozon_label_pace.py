"""Пауза и получение этикетки Ozon через задание create/get."""
import pytest

from app.core.exceptions import MarketplaceAPIException
from app.services.marketplace.ozon import (
    OZON_LABEL_NOT_READY_MESSAGE,
    OzonClient,
    _label_file_url,
    _pick_label_task_id,
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


def test_pick_small_label_task() -> None:
    payload = {
        "tasks": [
            {"task_id": 1, "task_type": "big_label"},
            {"task_id": 2, "task_type": "small_label"},
        ]
    }
    assert _pick_label_task_id(payload) == 2


def test_file_url_waits_while_posting_unprinted() -> None:
    payload = {
        "file_url": "https://cdn.example/label.pdf",
        "status": {
            "code": "completed",
            "unprinted_postings": [{"posting_number": "0135467400-0220-1", "message": "not ready"}],
        },
    }
    assert _label_file_url(payload, "0135467400-0220-1") is None
    assert _label_file_url(payload, "other") == "https://cdn.example/label.pdf"


@pytest.mark.asyncio
async def test_label_create_get_then_cache(monkeypatch) -> None:
    client = OzonClient(api_key="key", client_id="8816")
    calls: list[str] = []
    store: dict[str, bytes] = {}

    async def request(method, endpoint, json_data=None, max_retries=3):
        calls.append(endpoint)
        if endpoint.endswith("/create"):
            assert json_data == {"posting_numbers": ["0135467400-0220-1"]}
            return {"tasks": [{"task_id": 42, "task_type": "small_label"}]}
        assert json_data == {"task_id": 42}
        return {
            "file_url": "https://cdn.ozon.ru/small_label/42.pdf",
            "status": {"code": "completed", "unprinted_postings": []},
        }

    async def download(url: str) -> bytes:
        assert url.startswith("https://")
        return b"%PDF-1.4 official"

    monkeypatch.setattr(client, "_request", request)
    monkeypatch.setattr("app.services.marketplace.ozon._download_ozon_label_pdf", download)
    monkeypatch.setattr(
        "app.services.marketplace.ozon._load_cached_ozon_label",
        lambda client_id, posting: store.get(posting),
    )
    monkeypatch.setattr(
        "app.services.marketplace.ozon._store_cached_ozon_label",
        lambda client_id, posting, content: store.__setitem__(posting, content),
    )

    pdf = await client.get_order_label("0135467400-0220-1")
    assert pdf == b"%PDF-1.4 official"
    assert calls == [
        "/v3/posting/fbs/package-label/create",
        "/v2/posting/fbs/package-label/get",
    ]

    again = await client.get_order_label("0135467400-0220-1")
    assert again == pdf
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_label_polls_until_file_is_ready(monkeypatch) -> None:
    client = OzonClient(api_key="key", client_id="8816")
    gets = {"n": 0}

    async def request(method, endpoint, json_data=None, max_retries=3):
        if endpoint.endswith("/create"):
            return {"tasks": [{"task_id": 7, "task_type": "small_label"}]}
        gets["n"] += 1
        if gets["n"] == 1:
            return {"status": {"code": "in_progress", "unprinted_postings": []}}
        return {
            "file_url": "https://cdn.ozon.ru/small_label/7.pdf",
            "status": {"code": "completed"},
        }

    async def download(url: str) -> bytes:
        return b"%PDF-ready"

    monkeypatch.setattr(client, "_request", request)
    monkeypatch.setattr("app.services.marketplace.ozon._download_ozon_label_pdf", download)
    monkeypatch.setattr("app.services.marketplace.ozon.asyncio.sleep", _no_sleep)
    monkeypatch.setattr(
        "app.services.marketplace.ozon._load_cached_ozon_label",
        lambda client_id, posting: None,
    )
    monkeypatch.setattr(
        "app.services.marketplace.ozon._store_cached_ozon_label",
        lambda client_id, posting, content: None,
    )

    pdf = await client.get_order_label("0135467400-0220-1")
    assert pdf == b"%PDF-ready"
    assert gets["n"] == 2


@pytest.mark.asyncio
async def test_label_not_ready_after_polls(monkeypatch) -> None:
    client = OzonClient(api_key="key", client_id="8816")

    async def request(method, endpoint, json_data=None, max_retries=3):
        if endpoint.endswith("/create"):
            return {"tasks": [{"task_id": 7, "task_type": "small_label"}]}
        return {"status": {"code": "in_progress"}}

    monkeypatch.setattr(client, "_request", request)
    monkeypatch.setattr("app.services.marketplace.ozon.asyncio.sleep", _no_sleep)
    monkeypatch.setattr(
        "app.services.marketplace.ozon._load_cached_ozon_label",
        lambda client_id, posting: None,
    )

    with pytest.raises(MarketplaceAPIException) as exc:
        await client.get_order_label("0135467400-0220-1")
    assert exc.value.status_code == 503
    assert exc.value.detail == OZON_LABEL_NOT_READY_MESSAGE


async def _no_sleep(_delay: float) -> None:
    return None
