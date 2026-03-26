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


def _redis_pace_sync(client_id: str, interval_ms: int, spin_cap_sec: float) -> None:
    r = get_redis_client()
    key = f"fbs:ozon:pace:{client_id}"
    deadline = time.monotonic() + spin_cap_sec
    step = max(0.02, min(interval_ms / 4000.0, 0.12))
    while time.monotonic() < deadline:
        ok = r.set(name=key, value="1", nx=True, px=interval_ms)
        if ok:
            return
        time.sleep(step)
    raise TimeoutError(f"Ozon Redis pace: не удалось занять слот за {spin_cap_sec}s")


async def acquire_ozon_pace_slot(client_id: Optional[str]) -> None:
    """
    Подождать глобально (Redis), пока можно сделать следующий запрос к Ozon для этого Client-Id.
    При ошибке Redis — один warning и продолжаем (остаётся только локальный лимит в OzonClient).
    """
    global _pace_fallback_logged
    if not client_id or not str(client_id).strip():
        return
    if not settings.OZON_REDIS_PACE_ENABLED:
        return
    interval_ms = max(80, min(int(settings.OZON_REDIS_PACE_MS), 10_000))
    cid = str(client_id).strip()
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
