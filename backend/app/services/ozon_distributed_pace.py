"""
Глобальное ограничение частоты запросов к Ozon Seller API на один Client-Id.

Локальный семафор в процессе не видит соседние Celery-воркеры и второй uvicorn —
Ozon режет по «per second» на ключ продавца, поэтому нужен общий шаг через Redis.

Механика: SET key NX PX = interval — не более одного «тикета» на interval_ms миллисекунд
на client_id во всём кластере (все процессы, использующие тот же Redis).
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from app.config import settings
from app.utils.cache import get_redis_client
from app.utils.logger import logger

_pace_fallback_logged = False
_local_guard = asyncio.Lock()
_local_next: dict[str, float] = {}


def pace_wait_ms(now_ms: int, last_ms: int, gap_ms: int) -> int:
    """Сколько миллисекунд ждать, чтобы новый запрос начался не раньше last + gap."""
    if last_ms <= 0 or gap_ms <= 0:
        return 0
    return max(0, last_ms + gap_ms - now_ms)


def _redis_now_ms(client) -> int:
    sec, micro = client.time()
    return int(sec) * 1000 + int(micro) // 1000


def _redis_pace_sync(client_id: str, interval_ms: int, spin_cap_sec: float) -> None:
    """Занять слот: следующий запрос этого Client-Id стартует не раньше чем через interval_ms."""
    r = get_redis_client()
    key = f"fbs:ozon:last:{client_id}"
    lock = f"fbs:ozon:lock:{client_id}"
    deadline = time.monotonic() + spin_cap_sec
    step = max(0.02, min(interval_ms / 4000.0, 0.12))
    while time.monotonic() < deadline:
        if not r.set(lock, "1", nx=True, px=2000):
            time.sleep(step)
            continue
        wait_ms = 0
        try:
            now_ms = _redis_now_ms(r)
            last_raw = r.get(key)
            last_ms = int(last_raw) if last_raw else 0
            wait_ms = pace_wait_ms(now_ms, last_ms, interval_ms)
            if wait_ms <= 0:
                r.set(key, str(now_ms), px=120_000)
                return
        finally:
            r.delete(lock)
        time.sleep(min(wait_ms / 1000.0, 0.2))
    raise TimeoutError(f"Ozon Redis pace: не удалось занять слот за {spin_cap_sec}s")


async def _local_pace(client_id: str, interval_ms: int) -> None:
    """Та же пауза внутри процесса, если Redis недоступен."""
    async with _local_guard:
        now = time.monotonic()
        start = max(now, _local_next.get(client_id, 0.0))
        _local_next[client_id] = start + interval_ms / 1000.0
        wait = start - now
    if wait > 0:
        await asyncio.sleep(wait)


async def acquire_ozon_pace_slot(
    client_id: Optional[str],
    min_interval_ms: Optional[int] = None,
) -> None:
    """
    Подождать глобально (Redis), пока можно сделать следующий запрос к Ozon для этого Client-Id.

    min_interval_ms — пауза именно этого вызова от предыдущего запроса кабинета.
    Этикетка package-label передаёт больший интервал, чем обычные методы.
    При ошибке Redis остаётся локальная пауза в процессе.
    """
    global _pace_fallback_logged
    if not client_id or not str(client_id).strip():
        return
    interval_ms = int(settings.OZON_REDIS_PACE_MS if min_interval_ms is None else min_interval_ms)
    interval_ms = max(80, min(interval_ms, 10_000))
    cid = str(client_id).strip()
    if not settings.OZON_REDIS_PACE_ENABLED:
        await _local_pace(cid, interval_ms)
        return
    try:
        await asyncio.to_thread(
            _redis_pace_sync,
            cid,
            interval_ms,
            float(settings.OZON_REDIS_PACE_SPIN_CAP_SEC),
        )
    except Exception as e:
        if not _pace_fallback_logged:
            logger.warning(
                "Ozon: распределённый лимит Redis недоступен (%s), только локальная пауза в процессе",
                e,
            )
            _pace_fallback_logged = True
        await _local_pace(cid, interval_ms)


def should_skip_ozon_warehouse_list(marketplace_id: int) -> bool:
    """Не дергать /v1/warehouse/list, если недавно уже успешно синхронизировали склады."""
    ttl = int(settings.OZON_WAREHOUSE_SYNC_CACHE_SEC)
    if ttl <= 0:
        return False
    try:
        return get_redis_client().exists(f"fbs:ozon:whsync:{marketplace_id}") > 0
    except Exception:
        return False


def mark_ozon_warehouse_list_synced(marketplace_id: int) -> None:
    """Пометить успешную синхронизацию складов (TTL = интервал между вызовами list)."""
    ttl = int(settings.OZON_WAREHOUSE_SYNC_CACHE_SEC)
    if ttl <= 0:
        return
    try:
        get_redis_client().setex(f"fbs:ozon:whsync:{marketplace_id}", ttl, "1")
    except Exception:
        pass


def invalidate_ozon_warehouse_list_cache(marketplace_id: int) -> None:
    """Сбросить кэш warehouse/list (например, после смены складов в кабинете)."""
    try:
        get_redis_client().delete(f"fbs:ozon:whsync:{marketplace_id}")
    except Exception:
        pass
